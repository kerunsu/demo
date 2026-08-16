"""
真实语音分析器 (Analyzer) - ASR 识别模式 (Paraformer)
不再使用脆弱的强制对齐，改用健壮的语音识别模型。
只要识别出的文字和目标一致，就给高分。
"""
import os
import time
import io
import logging
import numpy as np
import soundfile as sf
# 引入 difflib 用于对比文本相似度
import difflib 
import threading
from typing import Optional, Dict, Any, Union

# ------------------------------------------------------
# 1. 本地定义基类
# ------------------------------------------------------
class LocalBaseAnalyzer:
    def __init__(self, analyzer_type, mode, config):
        self._analyzer_type = analyzer_type
        self._mode = mode
        self._config = config
        self._is_initialized = False
    
    @property
    def is_ready(self) -> bool:
        return self._is_initialized

    def analyze_chunk(self, chunk, context):
        raise NotImplementedError

try:
    from app.core.base_analyzer import BaseAudioAnalyzer
    ParentClass = BaseAudioAnalyzer
except ImportError:
    ParentClass = LocalBaseAnalyzer

from app.core.models import (
    AnalysisMode, 
    AnalyzerType, 
    AnalysisResult, 
    AnalysisContext,
    AnalyzerStatus,
)
from app.utils.logger import setup_logger

logger = setup_logger('real_speech_analyzer')

class RealSpeechAnalyzer(ParentClass):
    """
    真实语音分析器 (ASR 模式)
    """
    # [核心更改] 切换为更强大的 Paraformer 模型
    DEFAULT_MODEL_NAME = "paraformer-zh" 
    DEFAULT_SAMPLE_RATE = 16000
    
    def __init__(
        self,
        mode: AnalysisMode = AnalysisMode.REALTIME,
        config: Optional[Dict[str, Any]] = None
    ):
        try:
            super().__init__(AnalyzerType.SPEECH, mode, config)
        except:
            super().__init__("speech", mode, config)
        
        self._config = config or {}
        # 强制使用 paraformer-zh
        self._model_name = "paraformer-zh"
        self._device = self._config.get('device', 'cuda') 
        # analyzers.yaml 的 sample_rate 是“抽样频率”，不是音频 Hz；真实音频采样率
        # 使用 sample_rate_audio。旧代码把 sample_rate=1 写进 WAV，FunASR 会把几秒
        # 音频误判成数小时并尝试申请数十 GB 的注意力矩阵。
        configured_rate = self._config.get('sample_rate_audio', self.DEFAULT_SAMPLE_RATE)
        try:
            configured_rate = int(configured_rate)
        except (TypeError, ValueError):
            configured_rate = self.DEFAULT_SAMPLE_RATE
        self._target_sample_rate = (
            configured_rate if 8000 <= configured_rate <= 48000 else self.DEFAULT_SAMPLE_RATE
        )
        try:
            accumulation_duration = float(self._config.get('accumulation_duration', 2.0))
        except (TypeError, ValueError):
            accumulation_duration = 2.0
        self._accumulation_duration = max(0.5, min(accumulation_duration, 5.0))
        self._buffer_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._audio_buffer = []
        self._buffered_samples = 0
        self._model = None
        # local = 本进程 FunASR；voice-service = HTTP 回退（主 venv 无 torch 时）
        self._backend = None
        self._last_error = None
        self._unready_log_at = 0.0
        
        logger.info(
            "真实语音分析器 (ASR模式) 已创建: model=%s sample_rate=%sHz accumulation=%.1fs",
            self._model_name,
            self._target_sample_rate,
            self._accumulation_duration,
        )

    def initialize(self) -> bool:
        if self._is_initialized:
            return True
        local_error = None
        try:
            import torch
            from funasr import AutoModel
            
            if self._device == 'cuda' and not torch.cuda.is_available():
                self._device = 'cpu'

            logger.info(f"正在加载语音识别模型 {self._model_name} 到 {self._device}...")
            
            # 加载 Paraformer 模型
            self._model = AutoModel(
                model=self._model_name,
                # paraformer 不需要特定 revision，默认即可，或者指定最新
                device=self._device,
                disable_update=True
            )
            
            self._backend = 'local'
            self._is_initialized = True
            self._status = AnalyzerStatus.READY
            self._last_error = None
            logger.info(f"模型加载成功: {self._model_name}")
            return True
            
        except Exception as e:
            local_error = str(e)
            self._last_error = local_error
            logger.warning(
                "本进程 FunASR 不可用，尝试 voice-service 回退: %s",
                local_error,
            )

        # 与对话 STT 对齐：主进程缺 torch/funasr 时走本地 voice-service
        try:
            from app.dialogue.stt import voice_service_ready

            if voice_service_ready():
                self._backend = 'voice-service'
                self._model = None
                self._is_initialized = True
                self._status = AnalyzerStatus.READY
                self._last_error = None
                logger.info(
                    "语音分析器已回退到 voice-service STT（本进程缺少 FunASR 依赖）"
                )
                return True
            self._last_error = (
                f"local_funasr_failed:{local_error}; voice_service_not_ready"
            )
            self._status = AnalyzerStatus.ERROR
            logger.error(
                "语音分析器初始化失败: 本进程 FunASR=%s，且 voice-service 未 READY",
                local_error,
            )
            return False
        except Exception as vs_err:  # noqa: BLE001
            self._last_error = (
                f"local_funasr_failed:{local_error}; voice_service_probe:{vs_err}"
            )
            self._status = AnalyzerStatus.ERROR
            logger.error("语音分析器 voice-service 探测失败: %s", vs_err)
            return False

    def _preprocess_audio(self, audio_data):
        """音频预处理"""
        try:
            import soundfile as sf
            
            if isinstance(audio_data, bytes):
                audio, sr = sf.read(io.BytesIO(audio_data))
            elif isinstance(audio_data, np.ndarray):
                audio = audio_data
                sr = self._target_sample_rate
            else:
                return None

            if len(audio.shape) > 1:
                audio = np.mean(audio, axis=1)

            if sr != self._target_sample_rate:
                try:
                    import librosa
                except ImportError:
                    logger.error(
                        "音频采样率 %s≠%s 且未安装 librosa，无法重采样",
                        sr,
                        self._target_sample_rate,
                    )
                    return None
                audio = audio.astype(np.float32)
                audio = librosa.resample(
                    audio, orig_sr=sr, target_sr=self._target_sample_rate
                )
            
            # 音量标准化 (ASR 模型对音量不敏感，但放大一点更稳)
            max_val = np.abs(audio).max()
            if max_val > 0:
                audio = audio / max_val * 0.95
            
            return audio
            
        except Exception as e:
            logger.error(f"音频预处理失败: {e}")
            return None

    def _recognize_text(self, audio_int16: np.ndarray) -> tuple:
        """返回 (text, provider)。优先本进程模型，否则 WAV → voice-service。"""
        if self._backend == 'local' and self._model is not None:
            temp_filename = f"temp_asr_{int(time.time()*1000)}.wav"
            try:
                sf.write(
                    temp_filename,
                    audio_int16,
                    self._target_sample_rate,
                    subtype='PCM_16',
                )
                logger.info("正在识别音频(local): %s", temp_filename)
                res = self._model.generate(
                    input=temp_filename,
                    batch_size=1,
                    disable_pbar=True,
                )
                result_data = res[0] if isinstance(res, list) else res
                rec_text = str(result_data.get('text', '') or '').replace(" ", "")
                return rec_text, 'local-funasr'
            finally:
                if os.path.exists(temp_filename):
                    try:
                        os.remove(temp_filename)
                    except Exception:
                        pass

        wav_buf = io.BytesIO()
        sf.write(
            wav_buf,
            audio_int16,
            self._target_sample_rate,
            format='WAV',
            subtype='PCM_16',
        )
        from app.dialogue.stt import transcribe_wav_bytes

        result = transcribe_wav_bytes(wav_buf.getvalue())
        if result.get('ok') and result.get('transcript'):
            return str(result['transcript']).replace(" ", ""), str(
                result.get('provider') or 'voice-service'
            )
        # 空结果 / EMPTY_RESULT：无有效语音，不当成硬失败
        err = result.get('error') or ''
        if err and 'empty' not in str(err).lower():
            logger.debug("ASR 无文本: %s", err)
        return '', str(result.get('provider') or self._backend or 'none')

    def analyze_audio(self, audio_data, context):
        """全量分析接口；无 target_text 时仍产出 transcript + 表达性语言特征。"""
        if not self.is_ready:
            if not self.initialize(): return None

        aux = getattr(context, 'aux_data', None) or {}
        if not isinstance(aux, dict):
            aux = {}
        target_text = aux.get('target_text')

        try:
            start_time = time.time()
            audio_input = self._preprocess_audio(audio_data)
            if audio_input is None: return None

            # 简易能量 VAD
            rms = float(np.sqrt(np.mean(np.square(audio_input.astype(np.float32))))) if len(audio_input) else 0.0
            is_speech = rms > 0.01
            chunk_duration = len(audio_input) / float(self._target_sample_rate or 16000)

            # 明显静音块不打 ASR，降低 voice-service 压力
            if not is_speech:
                return AnalysisResult(
                    session_id=getattr(context, 'session_id', None),
                    analyzer_type="speech",
                    mode=self._mode,
                    timestamp=time.time(),
                    data={
                        'transcript': '',
                        'tokens': [],
                        'scores': [],
                        'timestamps': [],
                        'latency_ms': 0,
                        'detection_time_ms': 0,
                        'vad': {'is_speech': False, 'energy': rms, 'confidence': 0.0},
                        'asr': {
                            'text': '',
                            'confidence': 0.0,
                            'word_count': 0,
                            'is_final': True,
                            'provider': self._backend,
                        },
                        'speech_ratio': 0.0,
                        'word_count': 0,
                        'speech_duration': 0.0,
                        'clarity_proxy': 0.0,
                        'is_speech': False,
                        'data_quality': 'DEGRADED',
                        'speaker_assumption': 'child',
                    },
                    confidence=0.0,
                    frame_index=getattr(context, 'frame_index', None),
                )
            
            audio_int16 = (audio_input * 32767).astype(np.int16)
            rec_text, provider = self._recognize_text(audio_int16)
            detection_time = (time.time() - start_time) * 1000
            word_count = len(rec_text)
            
            logger.info(
                "🗣️ ASR[%s] 识别结果: '%s' (目标: '%s')",
                provider,
                rec_text,
                target_text,
            )

            final_score = 0.0
            scores = []
            if target_text:
                matcher = difflib.SequenceMatcher(None, rec_text, target_text)
                similarity = matcher.ratio()
                if similarity >= 0.6 or target_text in rec_text:
                    final_score = 95.0 + (similarity * 5)
                    scores = [0.99] * len(target_text)
                else:
                    final_score = similarity * 50
                    scores = [0.1] * len(target_text)
            else:
                # 表达性语言路径：有识别文本则给中等置信
                final_score = min(100.0, 40.0 + word_count * 5) if rec_text else (30.0 if is_speech else 0.0)
                scores = [0.5] * max(1, word_count)

            clarity_proxy = max(0.0, min(1.0, rms * 5.0))
            data = {
                'transcript': rec_text,
                'tokens': list(target_text) if target_text else list(rec_text),
                'scores': scores,
                'timestamps': [],
                'latency_ms': 0,
                'detection_time_ms': round(detection_time, 1),
                'vad': {'is_speech': is_speech, 'energy': rms, 'confidence': min(1.0, rms * 10)},
                'asr': {
                    'text': rec_text,
                    'confidence': final_score / 100.0,
                    'word_count': word_count,
                    'is_final': True,
                    'provider': provider,
                },
                'speech_ratio': 1.0 if is_speech else 0.0,
                'word_count': word_count,
                'speech_duration': round(chunk_duration if is_speech else 0.0, 3),
                'clarity_proxy': round(clarity_proxy, 3),
                'is_speech': is_speech,
                'data_quality': 'VALID' if (is_speech or rec_text) else 'DEGRADED',
                'speaker_assumption': 'child',
            }

            if target_text:
                processed_details = []
                tokens = list(target_text)
                for i, _ in enumerate(tokens):
                    processed_details.append({
                        'token': tokens[i],
                        'score': round(final_score, 1)
                    })
                data['details'] = processed_details

            return AnalysisResult(
                session_id=context.session_id,
                analyzer_type="speech",
                mode=self._mode,
                timestamp=time.time(),
                data=data,
                confidence=final_score / 100.0,
                frame_index=getattr(context, 'frame_index', None)
            )

        except Exception as e:
            logger.exception(f"语音分析失败: {e}")
            return None

    def analyze_chunk(self, chunk_data, context):
        """累积短 PCM 块并串行执行 ASR，避免每 4096 样本启动一次重模型。"""
        try:
            chunk = np.asarray(chunk_data, dtype=np.float32).reshape(-1)
        except Exception:
            return None
        if chunk.size == 0:
            return None

        required = int(self._target_sample_rate * self._accumulation_duration)
        max_samples = int(self._target_sample_rate * 5.0)
        with self._buffer_lock:
            self._audio_buffer.append(chunk.copy())
            self._buffered_samples += int(chunk.size)
            while self._buffered_samples > max_samples and self._audio_buffer:
                removed = self._audio_buffer.pop(0)
                self._buffered_samples -= int(removed.size)
            if self._buffered_samples < required:
                return None
            if not self._inference_lock.acquire(blocking=False):
                return None
            audio = np.concatenate(self._audio_buffer)
            self._audio_buffer.clear()
            self._buffered_samples = 0

        try:
            return self.analyze_audio(audio, context)
        finally:
            self._inference_lock.release()

    def reset_buffer(self) -> None:
        """丢弃系统播音期间累积的回声音频，不影响当前语音目标。"""
        with self._buffer_lock:
            self._audio_buffer.clear()
            self._buffered_samples = 0

    def reset_statistics(self) -> None:
        self.reset_buffer()
        return None

    def get_statistics(self) -> Dict[str, Any]:
        return {}
