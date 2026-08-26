"""
分析服务
统一管理分析流程，整合流水线、缓冲区、触发系统
支持三种分析模式：实时(Type A)、窗口(Type B)、会话(Type C)
"""
import threading
import time
import base64
from typing import Optional, Dict, Any, List, Callable, Tuple
import numpy as np
import cv2

from app.core.models import (
    AnalysisMode,
    AnalysisContext,
    AnalysisResult,
    MatchResult
)
from app.core.buffer import get_buffer_manager
from app.core.accumulator import get_accumulator_manager
from app.core.trigger import get_trigger_system, TriggerFactory
from app.core.pipelines import VisionPipeline, AudioPipeline, get_pipeline_manager
from app.utils.logger import setup_logger

logger = setup_logger('analysis_service')


class WindowAnalysisScheduler:
    """
    窗口分析调度器
    
    每秒触发一次窗口分析（Type B）
    """
    
    def __init__(self, analysis_service: 'AnalysisService'):
        """
        初始化调度器
        
        Args:
            analysis_service: 分析服务实例
        """
        self._service = analysis_service
        self._threads: Dict[str, threading.Thread] = {}
        self._stop_flags: Dict[str, bool] = {}
        self._lock = threading.Lock()
        self._interval = 0.5  # 教师端注意力响应：0.5s 一轮
        
        logger.info("窗口分析调度器已创建")
    
    def start(self, session_id: str) -> bool:
        """
        启动指定会话的窗口分析
        
        Args:
            session_id: 会话ID
        
        Returns:
            是否成功启动
        """
        with self._lock:
            if session_id in self._threads and self._threads[session_id].is_alive():
                logger.warning(f"窗口分析已在运行: {session_id}")
                return True
            
            self._stop_flags[session_id] = False
            thread = threading.Thread(
                target=self._schedule_loop,
                args=(session_id,),
                daemon=True,
                name=f"WindowScheduler-{session_id[:8]}"
            )
            self._threads[session_id] = thread
            thread.start()
            
            logger.info(f"窗口分析调度启动: {session_id}")
            return True
    
    def stop(self, session_id: str) -> None:
        """
        停止指定会话的窗口分析
        
        Args:
            session_id: 会话ID
        """
        with self._lock:
            if session_id in self._stop_flags:
                self._stop_flags[session_id] = True
                logger.info(f"窗口分析调度停止: {session_id}")

    def is_running(self, session_id: str) -> bool:
        with self._lock:
            t = self._threads.get(session_id)
            return bool(t and t.is_alive() and not self._stop_flags.get(session_id, True))
    
    def _schedule_loop(self, session_id: str) -> None:
        """
        调度循环
        
        Args:
            session_id: 会话ID
        """
        logger.debug(f"窗口调度循环启动: {session_id}")
        
        while not self._stop_flags.get(session_id, True):
            try:
                # 触发窗口分析
                self._service._run_window_analysis(session_id)
                
                # 等待下一次触发
                time.sleep(self._interval)
                
            except Exception as e:
                logger.error(f"窗口分析调度出错: {session_id}, {e}")
                time.sleep(self._interval)
        
        logger.debug(f"窗口调度循环结束: {session_id}")
    
    def cleanup(self) -> None:
        """清理所有调度"""
        with self._lock:
            for session_id in list(self._stop_flags.keys()):
                self._stop_flags[session_id] = True
            self._threads.clear()
            self._stop_flags.clear()


class SessionAnalysisState:
    """
    会话分析状态
    
    跟踪每个会话的分析配置和状态
    """
    
    def __init__(
        self,
        session_id: str,
        course_config: Optional[Dict[str, Any]] = None
    ):
        self.session_id = session_id
        self.course_config = course_config or {}
        self.start_time = time.time()
        self.frame_count = 0
        self.chunk_count = 0
        self.is_active = True
        
        # 目标配置
        self.pose_target_set = False
        self.speech_target_set = False
        
        # 分析模式
        self.enable_realtime = course_config.get('enable_realtime', True) if course_config else True
        self.enable_window = course_config.get('enable_window', True) if course_config else True
        self.enable_triggers = course_config.get('enable_triggers', True) if course_config else True
        self.system_audio_active = False
        self.ignore_audio_until = 0.0
        
        # 课程类型
        self.course_type = course_config.get('course_type', 'default') if course_config else 'default'


class AnalysisService:
    """
    分析服务
    
    统一管理分析流程：
    - 整合视觉和音频流水线
    - 管理数据缓冲区和累积器
    - 协调触发系统
    - 支持三种分析模式
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化分析服务
        
        Args:
            config: 配置参数
        """
        self._config = config or {}
        
        # 流水线
        self._vision_pipeline: Optional[VisionPipeline] = None
        self._audio_pipeline: Optional[AudioPipeline] = None
        
        # 管理器
        self._buffer_manager = get_buffer_manager()
        self._accumulator_manager = get_accumulator_manager()
        self._trigger_system = get_trigger_system()
        
        # 窗口分析调度器
        self._window_scheduler = WindowAnalysisScheduler(self)
        
        # 会话状态
        self._sessions: Dict[str, SessionAnalysisState] = {}
        self._lock = threading.RLock()
        
        # 诊断指标（按 analyzer/source 聚合）
        self._diag_lock = threading.RLock()
        self._diag_started_at = time.time()
        self._diag_metrics: Dict[str, Dict[str, Any]] = {}
        self._pipeline_health: Dict[str, Any] = {}
        self._pipeline_health_lock = threading.RLock()
        self._audio_init_thread: Optional[threading.Thread] = None
        
        # 回调函数
        self._on_analysis_result: Optional[Callable[[str, AnalysisResult], None]] = None
        self._on_match_result: Optional[Callable[[str, MatchResult], None]] = None
        self._on_trigger_action: Optional[Callable[[str, str, Any], None]] = None
        
        # 初始化流水线
        self._init_pipelines()
        
        health = self.get_pipeline_health()
        if health['ready']:
            logger.info("分析服务已初始化，全部必需分析器健康")
        elif health.get('status') == 'initializing':
            logger.info("分析服务已启动，音频模型正在后台预热")
        else:
            logger.error(
                "分析服务降级启动，必需分析器不可用: %s",
                health['requiredFailures'],
            )
    
    def _init_pipelines(self) -> None:
        """Initialize vision now and warm the heavy ASR model in background."""
        vision_config = self._config.get('vision', {})
        audio_config = self._config.get('audio', {})
        
        self._vision_pipeline = VisionPipeline(vision_config)
        self._audio_pipeline = AudioPipeline(audio_config)
        
        vision_ok = self._vision_pipeline.initialize()
        if not vision_ok:
            logger.error("视觉流水线初始化失败")

        # Paraformer may download/load close to 1 GB on first boot.  Doing that
        # before socketio.run meant 8080 remained unavailable for many minutes.
        # Keep the state explicit and let the web/control plane come up first.
        self._refresh_pipeline_health(audio_pending=True)
        self._audio_init_thread = threading.Thread(
            target=self._initialize_audio_pipeline,
            daemon=True,
            name="analysis-audio-warmup",
        )
        self._audio_init_thread.start()

    def _initialize_audio_pipeline(self) -> None:
        logger.info("音频流水线后台预热开始（服务端启动不等待模型下载）")
        audio_ok = self._audio_pipeline.initialize()
        if not audio_ok:
            logger.error("音频流水线后台初始化失败")
        self._refresh_pipeline_health(audio_pending=False)
        logger.info(
            "音频流水线后台预热结束: initialized=%s",
            bool(audio_ok),
        )

    def _refresh_pipeline_health(self, *, audio_pending: bool) -> None:
        pipelines = {
            'vision': self._vision_pipeline.get_info(),
            'audio': self._audio_pipeline.get_info(),
        }
        failures = []
        for pipeline_name, info in pipelines.items():
            for failure in info.get('initialization_failures') or []:
                failures.append({'pipeline': pipeline_name, **failure})
        if audio_pending:
            failures.append({
                'pipeline': 'audio',
                'component': 'speech',
                'required': True,
                'stage': 'background_initialize',
                'error': 'model_initializing',
            })
        required_failures = [item for item in failures if item.get('required')]
        ready = bool(
            getattr(self._vision_pipeline, 'is_initialized', False)
            and getattr(self._audio_pipeline, 'is_initialized', False)
            and not required_failures
        )
        health = {
            'ready': ready,
            'degraded': bool(failures),
            'status': (
                'initializing' if audio_pending
                else 'unhealthy' if required_failures
                else 'degraded' if failures
                else 'ready'
            ),
            'audioInitializing': bool(audio_pending),
            'pipelines': pipelines,
            'failures': failures,
            'requiredFailures': required_failures,
        }
        with self._pipeline_health_lock:
            self._pipeline_health = health

    def get_pipeline_health(self) -> Dict[str, Any]:
        with self._pipeline_health_lock:
            health = dict(self._pipeline_health)
        return {
            **health,
            'pipelines': {
                key: dict(value)
                for key, value in (health.get('pipelines') or {}).items()
            },
            'failures': [dict(item) for item in health.get('failures', [])],
            'requiredFailures': [
                dict(item) for item in health.get('requiredFailures', [])
            ],
        }

    def wait_for_audio_initialization(self, timeout: Optional[float] = None) -> bool:
        thread = self._audio_init_thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        return bool(
            self._audio_pipeline
            and getattr(self._audio_pipeline, 'is_initialized', False)
        )
    
    def set_callbacks(
        self,
        on_analysis: Optional[Callable[[str, AnalysisResult], None]] = None,
        on_match: Optional[Callable[[str, MatchResult], None]] = None,
        on_trigger: Optional[Callable[[str, str, Any], None]] = None
    ) -> None:
        """
        设置回调函数
        
        Args:
            on_analysis: 分析结果回调 (session_id, result)
            on_match: 匹配结果回调 (session_id, result)
            on_trigger: 触发动作回调 (session_id, action_type, data)
        """
        self._on_analysis_result = on_analysis
        self._on_match_result = on_match
        self._on_trigger_action = on_trigger
    
    def start_session(
        self,
        session_id: str,
        course_config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        启动分析会话
        
        Args:
            session_id: 会话ID
            course_config: 课程配置
        
        Returns:
            是否成功
        """
        with self._lock:
            if session_id in self._sessions:
                logger.warning(f"会话已存在: {session_id}")
                return True
            
            # 创建会话状态
            state = SessionAnalysisState(session_id, course_config)
            self._sessions[session_id] = state
            
            # 初始化缓冲区（get_buffer会自动创建）
            window_size = course_config.get('window_size', 10.0) if course_config else 10.0
            self._buffer_manager.get_buffer(session_id, window_size)
            
            # 初始化累积器（get_accumulator会自动创建）
            self._accumulator_manager.get_accumulator(session_id)
            
            # 注册默认触发器
            if state.enable_triggers:
                self._register_default_triggers(session_id, course_config)
            
            # 启动窗口分析调度
            if state.enable_window:
                self._window_scheduler.start(session_id)
            
            # 重置流水线会话
            self._vision_pipeline.reset_session()
            self._audio_pipeline.reset_session()
            
            logger.info(f"分析会话已启动: {session_id}, type={state.course_type}")
            return True

    def reconfigure_session(
        self,
        session_id: str,
        course_config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        切题时更新分析目标/触发器，不清空 buffer（连续录制方案 B）。

        若会话尚不存在则等价于 start_session。
        """
        with self._lock:
            if session_id not in self._sessions:
                return self.start_session(session_id, course_config)

            state = self._sessions[session_id]
            cfg = course_config or {}
            state.course_config = cfg
            state.course_type = cfg.get('course_type', state.course_type)
            state.enable_realtime = cfg.get('enable_realtime', state.enable_realtime)
            state.enable_window = cfg.get('enable_window', state.enable_window)
            state.enable_triggers = cfg.get('enable_triggers', state.enable_triggers)
            state.pose_target_set = False
            state.speech_target_set = False
            # Remove the previous item's target before the new target is
            # resolved. Camera frames may arrive concurrently with a teacher
            # item switch and must never score against the prior card.
            self._vision_pipeline.reset_pose_target()

            self._trigger_system.clear_session_triggers(session_id)
            if state.enable_triggers:
                self._register_default_triggers(session_id, cfg)

            if state.enable_window and not self._window_scheduler.is_running(session_id):
                self._window_scheduler.start(session_id)

            logger.info(
                "分析会话已重配置（保留 buffer）: session=%s type=%s",
                session_id, state.course_type,
            )
            return True
    
    def _register_default_triggers(
        self,
        session_id: str,
        course_config: Optional[Dict[str, Any]]
    ) -> None:
        """注册默认触发器"""
        course_type = course_config.get('course_type', 'default') if course_config else 'default'
        
        # 根据课程类型注册触发器
        if course_type in ['mimic', 'imitation', 'pose']:
            # 姿态答对由 PoseAutoPraiseService 统一走与拟声课程相同的
            # 表扬、教师评分上下文和审计链路；旧 pose trigger 只播放
            # 一段 MP3，且会与完整表扬包重复，因此不再注册。
            pass
        
        if course_type in ['naming', 'speech', 'onomatopoeia']:
            # 答对自动表扬改由 keyword_listen（提问 TTS 结束后武装，
            # 命中走教师同路 multimodal praise）。不再注册旧
            # speech_match_success → 预录 MP3 / 双通路触发。
            pass
        
        # 注意力低触发器（暂时禁用，因为注意力分析器尚未完善）
        # TODO: 当注意力分析器完善后，重新启用此功能
        # if course_config and course_config.get('enable_attention_trigger', True):
        #     attention_threshold = course_config.get('attention_threshold', 0.3)
        #     trigger = TriggerFactory.attention_low(threshold=attention_threshold)
        #     self._trigger_system.register_trigger(trigger, session_id)
        
        logger.debug(f"已注册触发器: session={session_id}, type={course_type}")
    
    def set_pose_target(
        self,
        session_id: str,
        target_keypoints: List[Dict],
        name: str = "target"
    ) -> bool:
        """
        设置姿态比对目标
        
        Args:
            session_id: 会话ID
            target_keypoints: 目标关键点
            name: 目标名称
        
        Returns:
            是否成功
        """
        with self._lock:
            if session_id not in self._sessions:
                logger.warning(f"会话不存在: {session_id}")
                return False
            
            success = self._vision_pipeline.set_pose_target(target_keypoints, name)
            self._sessions[session_id].pose_target_set = bool(success)
            
            logger.info(f"设置姿态目标: {session_id}, name={name}")
            return bool(success)
    
    def set_pose_target_from_image(
        self,
        session_id: str,
        image: np.ndarray
    ) -> bool:
        """
        从图片设置姿态比对目标
        
        Args:
            session_id: 会话ID
            image: 目标图片
        
        Returns:
            是否成功
        """
        with self._lock:
            if session_id not in self._sessions:
                logger.warning(f"会话不存在: {session_id}")
                return False
            
            success = self._vision_pipeline.set_pose_target_from_image(image)
            if success:
                self._sessions[session_id].pose_target_set = True
            
            return success
    
    def set_pose_target_from_path(
        self,
        session_id: str,
        image_path: str
    ) -> bool:
        """
        从图片路径设置姿态比对目标
        
        Args:
            session_id: 会话ID
            image_path: 目标图片路径
        
        Returns:
            是否成功
        """
        with self._lock:
            if session_id not in self._sessions:
                logger.warning(f"会话不存在: {session_id}")
                return False
            
            success = self._vision_pipeline.set_pose_target_from_path(image_path)
            if success:
                self._sessions[session_id].pose_target_set = True
                logger.info(f"从路径设置姿态目标: {session_id}, path={image_path}")
            
            return success
    
    def set_speech_target(
        self,
        session_id: str,
        text: str,
        phonemes: Optional[List[str]] = None
    ) -> bool:
        """
        设置语音比对目标
        
        Args:
            session_id: 会话ID
            text: 目标文字
            phonemes: 目标音素（可选）
        
        Returns:
            是否成功
        """
        with self._lock:
            if session_id not in self._sessions:
                logger.warning(f"会话不存在: {session_id}")
                return False
            
            self._audio_pipeline.set_speech_target(text, phonemes)
            self._sessions[session_id].speech_target_set = True
            
            logger.info(f"设置语音目标: {session_id}, text={text}")
            return True

    def update_system_audio_state(
        self,
        session_id: str,
        entry_id: Optional[str],
        status: Optional[str],
    ) -> None:
        """系统提问/提示/表扬播音期间暂停 ASR，避免扬声器回声被当成儿童回答。"""
        if session_id not in self._sessions:
            return
        entry = str(entry_id or '').lower()
        if entry not in ('question', 'hint', 'praise'):
            return
        normalized = {
            'finished': 'ended',
            'complete': 'ended',
            'completed': 'ended',
            'cancelled': 'ended',
            'canceled': 'ended',
            'interrupted': 'ended',
            'dropped': 'ended',
        }.get(str(status or '').lower(), str(status or '').lower())
        state = self._sessions[session_id]
        analyzer = getattr(self._audio_pipeline, 'speech_analyzer', None)
        if normalized == 'playing':
            state.system_audio_active = True
            state.ignore_audio_until = float('inf')
            if (state.course_type or '').lower() in ('mimic', 'imitation', 'pose'):
                self._vision_pipeline.reset_pose_stability(session_id)
            # Dump robot echo so it cannot be recognized as a child answer.
            if analyzer and hasattr(analyzer, 'reset_buffer'):
                analyzer.reset_buffer()
        elif normalized in ('ended', 'stopped', 'error'):
            state.system_audio_active = False
            # Only cover the speaker tail. A 0.75s mute plus buffer reset was
            # dropping answers that started as soon as the question ended.
            state.ignore_audio_until = time.time() + 0.18
        else:
            return

        logger.info(
            "系统播音 ASR 门控: session=%s entry=%s status=%s active=%s",
            session_id, entry, normalized, state.system_audio_active
        )
    
    def process_video_frame(
        self,
        session_id: str,
        frame_data: str,
        timestamp: Optional[float] = None
    ) -> Tuple[List[AnalysisResult], List[MatchResult]]:
        """
        处理视频帧
        
        Args:
            session_id: 会话ID
            frame_data: base64编码的视频帧
            timestamp: 时间戳
        
        Returns:
            (分析结果列表, 匹配结果列表)
        """
        if session_id not in self._sessions:
            return [], []
        
        state = self._sessions[session_id]
        if not state.is_active or not state.enable_realtime:
            return [], []
        try:
            # 解码帧
            frame = self._decode_frame(frame_data)
            if frame is None:
                return [], []
            
            ts = timestamp or time.time()
            state.frame_count += 1
            
            # 添加到缓冲区（用于窗口分析）
            buffer = self._buffer_manager.get_buffer(session_id)
            if buffer:
                buffer.add_video_frame(frame, ts)
            
            # 创建上下文
            context = AnalysisContext(
                session_id=session_id,
                course_type=state.course_type,
                frame_index=state.frame_count,
                start_time=state.start_time
            )
            
            # 实时分析（Type A）
            video_start = time.time()
            analysis_results, match_results = self._run_realtime_video_analysis(
                frame, context
            )
            # The target card is visible while the robot asks the question, but
            # the child must actually hold the action after the prompt. Never
            # accumulate/emit a pose success during question, hint or praise TTS.
            if (
                state.system_audio_active
                and (state.course_type or '').lower()
                in ('mimic', 'imitation', 'pose')
            ):
                self._vision_pipeline.reset_pose_stability(session_id)
                for result in match_results:
                    if getattr(result, 'matcher_type', '') == 'pose_matcher':
                        result.passed = False
                        result.details['stable_passed'] = False
                        result.details['gated_by_system_audio'] = True
            elapsed_ms = (time.time() - video_start) * 1000.0
            self._record_diagnostics(analysis_results, elapsed_ms, source='video_realtime')
            
            # 累积结果
            accumulator = self._accumulator_manager.get_accumulator(session_id)
            if accumulator:
                accumulator.add_frame_count(1)
                # 处理匹配结果
                for result in match_results:
                    accumulator.add_key_event('pose_match', {
                        'score': result.score,
                        'passed': result.passed
                    })
            
            # 检查触发器
            if state.enable_triggers:
                self._check_triggers(session_id, match_results, analysis_results)
            
            # 回调
            self._emit_results(session_id, analysis_results, match_results)
            
            return analysis_results, match_results
            
        except Exception as e:
            self._record_error_diagnostics('video_realtime', str(e))
            logger.error(f"处理视频帧失败: {session_id}, {e}")
            return [], []
    
    def process_audio_chunk(
        self,
        session_id: str,
        chunk_data: str,
        timestamp: Optional[float] = None
    ) -> Tuple[List[AnalysisResult], List[MatchResult]]:
        """
        处理音频块
        
        Args:
            session_id: 会话ID
            chunk_data: base64编码的音频块
            timestamp: 时间戳
        
        Returns:
            (分析结果列表, 匹配结果列表)
        """
        if session_id not in self._sessions:
            return [], []
        
        state = self._sessions[session_id]
        if not state.is_active or not state.enable_realtime:
            return [], []
        if state.system_audio_active:
            return [], []
        if time.time() < state.ignore_audio_until:
            # Keep a short preroll during the speaker-tail gate so a child
            # answer that starts immediately after TTS is still recognized.
            audio_chunk = self._decode_audio(chunk_data)
            if audio_chunk is not None:
                analyzer = getattr(self._audio_pipeline, 'speech_analyzer', None)
                ingest = getattr(analyzer, 'ingest_preroll', None)
                if callable(ingest):
                    ingest(audio_chunk, max_seconds=1.0)
            return [], []
        
        try:
            # 解码音频
            audio_chunk = self._decode_audio(chunk_data)
            if audio_chunk is None:
                return [], []
            
            ts = timestamp or time.time()
            state.chunk_count += 1
            
            # 添加到缓冲区
            buffer = self._buffer_manager.get_buffer(session_id)
            if buffer:
                buffer.add_audio_chunk(audio_chunk, ts)
            
            # 创建上下文
            context = AnalysisContext(
                session_id=session_id,
                course_type=state.course_type,
                audio_chunk_index=state.chunk_count,
                start_time=state.start_time
            )
            
            # 实时分析（Type A）
            audio_start = time.time()
            analysis_results, match_results = self._run_realtime_audio_analysis(
                audio_chunk, context
            )
            elapsed_ms = (time.time() - audio_start) * 1000.0
            self._record_diagnostics(analysis_results, elapsed_ms, source='audio_realtime')
            
            # 累积结果
            accumulator = self._accumulator_manager.get_accumulator(session_id)
            if accumulator:
                accumulator.add_audio_chunk_count(1)
                # 处理语音分析结果
                for result in analysis_results:
                    if result.analyzer_type == 'speech':
                        word_count = result.data.get('asr', {}).get('word_count', 0)
                        if word_count > 0:
                            accumulator.add_word_count(word_count)
                # 处理匹配结果
                for result in match_results:
                    accumulator.add_key_event('speech_match', {
                        'score': result.score,
                        'passed': result.passed
                    })
                    if result.passed:
                        try:
                            from app.monitor.events import append_monitor_event
                            from app.behavior import get_behavior_service

                            ctx = get_behavior_service().get_current_context_for_runtime(session_id)
                            append_monitor_event(
                                "speech_match",
                                f"语音匹配成功 score={round(float(result.score or 0), 2)}",
                                training_session_id=ctx.get("training_session_id"),
                                question_id=ctx.get("question_id"),
                                level="info",
                            )
                        except Exception:
                            pass

            # 表达性语言观测入库（默认人声=儿童）
            try:
                from app.behavior import get_behavior_service
                behavior = get_behavior_service()
                ctx = behavior.get_current_context_for_runtime(session_id)
                ts_id = ctx.get('training_session_id')
                qid = ctx.get('question_id')
                if ts_id and qid:
                    for result in analysis_results:
                        if result.analyzer_type != 'speech':
                            continue
                        data = result.data or {}
                        is_speech = data.get('is_speech')
                        if is_speech is None:
                            is_speech = (data.get('vad') or {}).get('is_speech')
                        # 静音块也记一条低活动观测，便于 speech_ratio 统计
                        behavior.record_language(
                            ts_id,
                            qid,
                            kind='speech_activity' if is_speech else 'silence',
                            value=data.get('transcript') or (data.get('asr') or {}).get('text'),
                            speech_ratio=data.get('speech_ratio', 1.0 if is_speech else 0.0),
                            word_count=data.get('word_count') or (data.get('asr') or {}).get('word_count'),
                            speech_duration=data.get('speech_duration'),
                            clarity_proxy=data.get('clarity_proxy'),
                            is_speech=bool(is_speech),
                            transcript=data.get('transcript') or (data.get('asr') or {}).get('text'),
                            confidence=result.confidence,
                            data_quality=data.get('data_quality', 'VALID' if is_speech else 'DEGRADED'),
                            runtime_session_id=session_id,
                            features=data,
                        )
                    # 接受性语言：命名/拟声课写入，避免覆盖配对/排序 metrics
                    if (state.course_type or '').lower() in ('naming', 'speech', 'onomatopoeia'):
                        for mr in match_results:
                            matcher_type = getattr(mr, 'matcher_type', None) or getattr(mr, 'type', None)
                            if matcher_type and matcher_type != 'speech' and matcher_type != 'speech_matcher':
                                continue
                            behavior.record_task_metrics(ts_id, qid, {
                                'type': 'receptive',
                                'pass_rate': 100.0 if mr.passed else 0.0,
                                'score': float(mr.score) * 100.0 if mr.score is not None and mr.score <= 1 else float(mr.score or 0),
                                'passed': bool(mr.passed),
                            })
            except Exception as e:
                logger.warning("写入语言观测失败: %s", e)
            
            # 命名/拟声：提问结束后关键词命中 → 教师同路表扬（非对话唤醒）
            try:
                from app.services.keyword_listen import get_keyword_listen_service

                transcript = ''
                for result in analysis_results:
                    if getattr(result, 'analyzer_type', None) != 'speech':
                        continue
                    data = result.data or {}
                    transcript = str(
                        data.get('transcript')
                        or (data.get('asr') or {}).get('text')
                        or ''
                    ).strip()
                    if transcript:
                        break
                if transcript:
                    get_keyword_listen_service().try_auto_praise_from_transcript(
                        session_id,
                        transcript,
                    )
            except Exception as kw_err:  # noqa: BLE001
                logger.debug('keyword_listen evaluate failed: %s', kw_err)

            # 检查触发器
            if state.enable_triggers:
                self._check_triggers(session_id, match_results, analysis_results)
            
            # 回调
            self._emit_results(session_id, analysis_results, match_results)
            
            return analysis_results, match_results
            
        except Exception as e:
            self._record_error_diagnostics('audio_realtime', str(e))
            logger.error(f"处理音频块失败: {session_id}, {e}")
            return [], []
    
    def _run_realtime_video_analysis(
        self,
        frame: np.ndarray,
        context: AnalysisContext
    ) -> Tuple[List[AnalysisResult], List[MatchResult]]:
        """执行实时视频分析（Type A）"""
        return self._vision_pipeline.process_realtime(frame, context)
    
    def _run_realtime_audio_analysis(
        self,
        audio_chunk: np.ndarray,
        context: AnalysisContext
    ) -> Tuple[List[AnalysisResult], List[MatchResult]]:
        """执行实时音频分析（Type A）"""
        return self._audio_pipeline.process_realtime(audio_chunk, context)
    
    def _run_window_analysis(self, session_id: str) -> List[AnalysisResult]:
        """
        执行窗口分析（Type B）
        
        由调度器定时触发
        """
        if session_id not in self._sessions:
            return []
        
        state = self._sessions[session_id]
        if not state.is_active:
            return []
        
        try:
            # 获取缓冲区数据
            buffer = self._buffer_manager.get_buffer(session_id)
            if not buffer:
                return []
            
            video_frames = buffer.get_video_frames()
            audio_chunks = buffer.get_audio_chunks()
            
            if not video_frames and not audio_chunks:
                # 节流：避免刷屏，但要能发现无帧问题
                if state.frame_count % 30 == 0:
                    logger.warning(
                        "窗口分析无缓冲帧: session=%s frame_count=%s",
                        session_id, state.frame_count
                    )
                return []
            
            # 创建上下文
            context = AnalysisContext(
                session_id=session_id,
                course_type=state.course_type,
                frame_index=state.frame_count,
                start_time=state.start_time,
                metadata={'window_analysis': True}
            )
            
            # 窗口分析
            window_start = time.time()
            results = self._vision_pipeline.process_window(
                video_frames, audio_chunks, context
            )
            elapsed_ms = (time.time() - window_start) * 1000.0
            self._record_diagnostics(results, elapsed_ms, source='window')
            
            # 累积结果
            accumulator = self._accumulator_manager.get_accumulator(session_id)
            if accumulator:
                for result in results:
                    # 累积注意力分数
                    if result.analyzer_type == 'attention':
                        score = result.data.get('score', 0)
                        accumulator.add_attention_score(score)
            
            # 写入行为观测（注意力 + 情绪）
            # browser 联调且 prefer_browser 时跳过服务端写分，避免与 C2 双源；
            # agent（robot_runtime）路径必须写入服务端观测。
            try:
                from app.behavior.camera_config import should_prefer_browser_for_report
                skip_server_attn = should_prefer_browser_for_report()
            except Exception:
                skip_server_attn = False

            try:
                from app.behavior import get_behavior_service
                from app.behavior.emotion_scoring import (
                    map_label_to_emotion_scores,
                    emotion_quality_from_scores,
                )
                behavior = get_behavior_service()
                ctx = behavior.get_current_context_for_runtime(session_id)
                ts_id = ctx.get('training_session_id')
                qid = ctx.get('question_id')
                if not ts_id or not qid:
                    logger.warning(
                        "跳过注意力写入：缺少训练上下文 session=%s training=%s question=%s",
                        session_id, ts_id, qid
                    )
                elif skip_server_attn:
                    pass
                else:
                    for result in results:
                        if result.analyzer_type != 'attention':
                            continue
                        data = result.data or {}
                        score = data.get('score')
                        if score is None and result.confidence is not None:
                            score = float(result.confidence) * 100.0
                        score_f = float(score or 0)
                        # Mock 注意力常为 0–1，报告维度按 0–100
                        if score_f <= 1.0:
                            score_f *= 100.0
                        dq = data.get('data_quality', 'VALID')
                        if isinstance(dq, (int, float)):
                            dq = 'VALID' if float(dq) >= 0.3 else ('DEGRADED' if float(dq) > 0 else 'MISSING')
                        elif not isinstance(dq, str):
                            dq = 'VALID'
                        face_present = bool(data.get('face_present', data.get('has_face')))
                        behavior.record_attention(
                            ts_id,
                            qid,
                            score=score_f,
                            state=data.get('state', 'unknown'),
                            trend=data.get('trend', 'stable'),
                            data_quality=dq,
                            face_present=face_present,
                            runtime_session_id=session_id,
                            provider='server',
                            algorithm_version=data.get('algorithm_version') or 'server-window-attention',
                            features=data,
                        )
                        # 服务端情绪：有脸时从几何情绪/标签映射写入
                        emo = data.get('emotion_scores')
                        if not emo and face_present and data.get('emotion'):
                            emo = map_label_to_emotion_scores(
                                str(data.get('emotion')),
                                smile_ratio=float(data.get('smile_ratio') or 0),
                                mar=float(data.get('mar') or 0),
                            )
                        if emo and face_present and dq != 'MISSING':
                            eq = emotion_quality_from_scores(emo, face_present)
                            if eq != 'MISSING' and not emo.get('unavailable'):
                                behavior.record_emotion(
                                    ts_id,
                                    qid,
                                    positive=float(emo.get('positiveScore') or 0),
                                    focused=float(emo.get('focusedScore') or 0),
                                    frustrated=float(emo.get('frustratedScore') or 0),
                                    confidence=float(emo.get('confidence') or 0),
                                    data_quality=eq,
                                    degraded=bool(emo.get('degraded')),
                                    algorithm_version=emo.get('algorithmVersion') or 'server-emotion-v1',
                                    provider='server',
                                    runtime_session_id=session_id,
                                    features={'source': 'real_attention', 'label': data.get('emotion')},
                                )
                    # 若已有报告，轻量刷新（节流：每约 5 次窗口一次）
                    try:
                        if state.frame_count % 5 == 0:
                            from app.behavior.store import get_behavior_store
                            if get_behavior_store().get_report(ts_id):
                                from app.report import get_report_service
                                get_report_service().refresh(ts_id)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("写入注意力观测失败: %s", e)

            # 检查触发器（注意力等）
            if state.enable_triggers and results:
                self._check_analysis_triggers(session_id, results)
            
            # 回调
            for result in results:
                if self._on_analysis_result:
                    self._on_analysis_result(session_id, result)
            
            return results
            
        except Exception as e:
            self._record_error_diagnostics('window', str(e))
            logger.error(f"窗口分析失败: {session_id}, {e}")
            return []
    
    def end_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        结束分析会话
        
        执行会话总结分析（Type C）
        
        Args:
            session_id: 会话ID
        
        Returns:
            会话总结数据
        """
        with self._lock:
            if session_id not in self._sessions:
                logger.warning(f"会话不存在: {session_id}")
                return None
            
            state = self._sessions[session_id]
            state.is_active = False
            
            # 停止窗口分析调度
            self._window_scheduler.stop(session_id)
            
            try:
                # 获取累积器统计
                accumulator = self._accumulator_manager.get_accumulator(session_id)
                
                # 从流水线获取分析结果
                all_results = self._vision_pipeline.get_analysis_results() + \
                              self._audio_pipeline.get_analysis_results()
                
                # 创建会话上下文
                session_duration = time.time() - state.start_time
                context = AnalysisContext(
                    session_id=session_id,
                    course_type=state.course_type,
                    start_time=state.start_time,
                    metadata={'session_duration': session_duration}
                )
                
                # 会话总结分析（Type C）
                vision_summary = self._vision_pipeline.process_session(all_results, context)
                audio_summary = self._audio_pipeline.process_session(all_results, context)
                
                # 构建总结
                summary = {
                    'session_id': session_id,
                    'course_type': state.course_type,
                    'duration': round(session_duration, 2),
                    'total_frames': state.frame_count,
                    'total_chunks': state.chunk_count,
                    'vision_summary': [r.data for r in vision_summary] if vision_summary else [],
                    'audio_summary': [r.data for r in audio_summary] if audio_summary else [],
                    'statistics': accumulator.get_statistics() if accumulator else {}
                }
                
                # 清理资源
                self._cleanup_session(session_id)
                
                logger.info(
                    f"分析会话已结束: {session_id}, "
                    f"duration={session_duration:.2f}s, "
                    f"frames={state.frame_count}"
                )
                
                return summary
                
            except Exception as e:
                logger.error(f"结束会话失败: {session_id}, {e}")
                self._cleanup_session(session_id)
                return None
    
    def _cleanup_session(self, session_id: str) -> None:
        """清理会话资源"""
        # 清理缓冲区
        self._buffer_manager.remove_buffer(session_id)
        
        # 清理累积器
        self._accumulator_manager.remove_accumulator(session_id)
        
        # 清理触发器
        self._trigger_system.clear_session_triggers(session_id)

        try:
            from app.services.keyword_listen import get_keyword_listen_service

            get_keyword_listen_service().clear(session_id)
        except Exception:
            pass

        try:
            from app.services.pose_auto_praise import get_pose_auto_praise_service

            get_pose_auto_praise_service().clear(session_id)
        except Exception:
            pass
        
        # 移除会话状态
        if session_id in self._sessions:
            del self._sessions[session_id]
    
    def _check_triggers(
        self,
        session_id: str,
        match_results: List[MatchResult],
        analysis_results: List[AnalysisResult]
    ) -> None:
        """检查并执行触发器。未通过的匹配结果不得触发表扬等动作。"""
        for result in match_results:
            if not getattr(result, 'passed', False):
                continue
            actions = self._trigger_system.check_match_result(result)
            for action_result in actions:
                if self._on_trigger_action:
                    self._on_trigger_action(
                        session_id,
                        action_result.action_type,
                        action_result.metadata
                    )
    
    def _check_analysis_triggers(
        self,
        session_id: str,
        analysis_results: List[AnalysisResult]
    ) -> None:
        """检查分析结果触发器（如注意力）"""
        for result in analysis_results:
            if result.analyzer_type == 'attention':
                actions = self._trigger_system.check_analysis_result(result)
                for action_result in actions:
                    if self._on_trigger_action:
                        self._on_trigger_action(
                            session_id,
                            action_result.action_type,
                            action_result.metadata
                        )
    
    def _emit_results(
        self,
        session_id: str,
        analysis_results: List[AnalysisResult],
        match_results: List[MatchResult]
    ) -> None:
        """发送结果回调"""
        if self._on_analysis_result:
            for result in analysis_results:
                self._on_analysis_result(session_id, result)
        
        if self._on_match_result:
            for result in match_results:
                self._on_match_result(session_id, result)
    
    def _decode_frame(self, frame_data: str) -> Optional[np.ndarray]:
        """解码base64视频帧"""
        try:
            # 移除data URL前缀（如果有）
            if ',' in frame_data:
                frame_data = frame_data.split(',')[1]
            
            # base64解码
            img_bytes = base64.b64decode(frame_data)
            
            # 转换为numpy数组
            nparr = np.frombuffer(img_bytes, np.uint8)
            
            # 解码图像
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            return frame
            
        except Exception as e:
            logger.error(f"解码视频帧失败: {e}")
            return None
    
    def _decode_audio(self, chunk_data: str) -> Optional[np.ndarray]:
        """解码base64音频块"""
        try:
            # base64解码
            audio_bytes = base64.b64decode(chunk_data)
            
            # 转换为numpy数组（假设是PCM Int16格式）
            audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
            
            # 转换为float32
            audio_float = audio_array.astype(np.float32) / 32768.0
            
            return audio_float
            
        except Exception as e:
            logger.error(f"解码音频块失败: {e}")
            return None
    
    def get_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话状态"""
        if session_id not in self._sessions:
            return None
        
        state = self._sessions[session_id]
        return {
            'session_id': session_id,
            'course_type': state.course_type,
            'is_active': state.is_active,
            'frame_count': state.frame_count,
            'chunk_count': state.chunk_count,
            'duration': time.time() - state.start_time,
            'pose_target_set': state.pose_target_set,
            'speech_target_set': state.speech_target_set
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取服务统计"""
        return {
            'active_sessions': len([s for s in self._sessions.values() if s.is_active]),
            'total_sessions': len(self._sessions),
            'vision_pipeline': self._vision_pipeline.get_info() if self._vision_pipeline else None,
            'audio_pipeline': self._audio_pipeline.get_info() if self._audio_pipeline else None
        }
    
    def probe_attention(
        self,
        frame_data: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        就绪门探针：对单帧跑注意力/情绪，不 open_window、不写报告。

        注意：注意力分析器挂在 VisionPipeline 的「窗口」路径，不在 process_realtime 里。
        因此这里直接调用 attention_analyzer.analyze_frame。
        """
        try:
            if not self._vision_pipeline:
                return {"ok": False, "detail": "vision_pipeline_unavailable"}

            frame = self._decode_frame(frame_data)
            if frame is None:
                return {"ok": False, "detail": "frame_decode_failed"}

            attention_analyzer = getattr(self._vision_pipeline, "attention_analyzer", None)
            if attention_analyzer is None:
                info = self._vision_pipeline.get_info() if self._vision_pipeline else {}
                return {
                    "ok": False,
                    "detail": "attention_analyzer_missing",
                    "pipeline": info,
                }

            if hasattr(attention_analyzer, "initialize") and not getattr(attention_analyzer, "is_ready", True):
                attention_analyzer.initialize()

            sid = session_id or f"probe_{int(time.time() * 1000)}"
            context = AnalysisContext(
                session_id=sid,
                course_type="probe",
                frame_index=0,
                start_time=time.time(),
            )

            attention = attention_analyzer.analyze_frame(frame, context)
            if attention is None:
                return {"ok": False, "detail": "no_attention_result"}

            data = attention.data or {}
            score = data.get("score")
            if score is None:
                score = data.get("attention_score")
            emotion = data.get("emotion")
            emotion_scores = data.get("emotion_scores")
            face_present = data.get("face_present")
            if face_present is None:
                face_present = data.get("facePresent") or data.get("has_face")

            # 就绪门必须反映课中真实通路：无人脸时服务端不会推送 attention_update，
            # 教师端也不会显示注意力/情绪。因此 face=missing 不能标绿。
            detail = f"attention={score}"
            if emotion:
                detail += f", emotion={emotion}"

            if face_present is False:
                attention_ok = False
                emotion_ok = False
                detail += ", face=missing（未检出人脸，课中也不会有注意力/情绪推送）"
            else:
                attention_ok = score is not None
                emotion_ok = bool(emotion) or bool(emotion_scores)
                if face_present is True:
                    detail += ", face=ok"
                elif face_present is None and score is not None:
                    detail += ", face=unknown"

            return {
                "ok": bool(attention_ok),
                "attentionOk": bool(attention_ok),
                "emotionOk": bool(emotion_ok),
                "attentionScore": score,
                "emotion": emotion,
                "emotionScores": emotion_scores,
                "facePresent": face_present,
                "detail": detail,
            }
        except Exception as e:
            logger.error("probe_attention 失败: %s", e, exc_info=True)
            return {"ok": False, "detail": str(e)}

    def get_diagnostics(self) -> Dict[str, Any]:
        """获取诊断指标（按 analyzer/source 聚合）。"""
        with self._diag_lock:
            now = time.time()
            runtime_s = max(now - self._diag_started_at, 1e-6)
            analyzers: Dict[str, Any] = {}
            
            for key, metric in self._diag_metrics.items():
                success = metric.get('success_count', 0)
                errors = metric.get('error_count', 0)
                total = success + errors
                avg_latency = (
                    metric.get('total_latency_ms', 0.0) / success
                    if success > 0 else None
                )
                analyzers[key] = {
                    'success_count': success,
                    'error_count': errors,
                    'total_count': total,
                    'error_rate': round(errors / total, 4) if total > 0 else 0.0,
                    'avg_latency_ms': round(avg_latency, 3) if avg_latency is not None else None,
                    'throughput_per_sec': round(success / runtime_s, 4),
                    'last_error': metric.get('last_error')
                }

            vision_pipeline_ok = bool(
                self._vision_pipeline and getattr(self._vision_pipeline, 'is_initialized', False)
            )
            audio_pipeline_ok = bool(
                self._audio_pipeline and getattr(self._audio_pipeline, 'is_initialized', False)
            )
            health = self.get_pipeline_health()
            
            return {
                'runtime_sec': round(runtime_s, 3),
                'analyzers': analyzers,
                'visionPipelineInitialized': vision_pipeline_ok,
                'audioPipelineInitialized': audio_pipeline_ok,
                'pipelineHealth': health,
                'ready': bool(health.get('ready')),
                'degraded': bool(health.get('degraded')),
                'status': health.get('status') or 'unhealthy',
            }
    
    def get_all_session_states(self) -> List[Dict[str, Any]]:
        """获取所有会话状态快照"""
        with self._lock:
            snapshots: List[Dict[str, Any]] = []
            for session_id, state in self._sessions.items():
                snapshots.append({
                    'session_id': session_id,
                    'course_type': state.course_type,
                    'is_active': state.is_active,
                    'frame_count': state.frame_count,
                    'chunk_count': state.chunk_count,
                    'duration': round(time.time() - state.start_time, 3),
                    'enable_realtime': state.enable_realtime,
                    'enable_window': state.enable_window,
                    'enable_triggers': state.enable_triggers
                })
            return snapshots
    
    def reload_pipelines(self) -> bool:
        """
        重新加载分析流水线。
        
        用于在配置更新后应用到运行时。当前实现会重建视觉/音频流水线，
        已存在会话继续保留，但其正在使用的目标状态可能被重置。
        """
        with self._lock:
            try:
                if self._vision_pipeline:
                    self._vision_pipeline.cleanup()
                if self._audio_pipeline:
                    self._audio_pipeline.cleanup()
                
                self._init_pipelines()
                logger.info("分析流水线重载成功")
                return True
            except Exception as e:
                self._record_error_diagnostics('pipeline_reload', str(e))
                logger.error(f"分析流水线重载失败: {e}")
                return False
    
    def _record_diagnostics(
        self,
        analysis_results: List[AnalysisResult],
        elapsed_ms: float,
        source: str
    ) -> None:
        """
        记录诊断成功指标。
        
        当存在多个分析结果时，将本次耗时平均分配到各 analyzer。
        """
        with self._diag_lock:
            if not analysis_results:
                metric = self._diag_metrics.setdefault(source, {
                    'success_count': 0,
                    'error_count': 0,
                    'total_latency_ms': 0.0,
                    'last_error': None
                })
                metric['success_count'] += 1
                metric['total_latency_ms'] += float(elapsed_ms)
                return
            
            unit_latency = float(elapsed_ms) / max(len(analysis_results), 1)
            for result in analysis_results:
                key = result.analyzer_type or source
                metric = self._diag_metrics.setdefault(key, {
                    'success_count': 0,
                    'error_count': 0,
                    'total_latency_ms': 0.0,
                    'last_error': None
                })
                metric['success_count'] += 1
                metric['total_latency_ms'] += unit_latency
    
    def _record_error_diagnostics(self, key: str, error_message: str) -> None:
        """记录诊断错误指标。"""
        with self._diag_lock:
            metric = self._diag_metrics.setdefault(key, {
                'success_count': 0,
                'error_count': 0,
                'total_latency_ms': 0.0,
                'last_error': None
            })
            metric['error_count'] += 1
            metric['last_error'] = error_message
    
    def cleanup(self) -> None:
        """清理服务"""
        # 停止所有会话
        for session_id in list(self._sessions.keys()):
            self.end_session(session_id)
        
        # 清理调度器
        self._window_scheduler.cleanup()
        
        # 清理流水线
        if self._vision_pipeline:
            self._vision_pipeline.cleanup()
        if self._audio_pipeline:
            self._audio_pipeline.cleanup()
        
        logger.info("分析服务已清理")


# 全局分析服务实例
_analysis_service: Optional[AnalysisService] = None
_service_lock = threading.Lock()


def get_analysis_service() -> AnalysisService:
    """获取全局分析服务实例（单例模式）"""
    global _analysis_service
    if _analysis_service is None:
        with _service_lock:
            if _analysis_service is None:
                _analysis_service = AnalysisService()
    return _analysis_service

