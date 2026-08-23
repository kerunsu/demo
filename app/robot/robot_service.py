"""
机械臂服务
整合层，管理录制器、播放器、映射解析器
提供统一接口供其他模块调用
"""
import json
import os
import queue
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import asdict, replace
from pathlib import Path
from typing import Dict, List, Optional, Any

from app.robot.config import (
    IDLE_POSE_DELAY,
    ROBOT_CONTROL_MODE,
    ROBOT_CHILD_ROOM,
    ROBOT_RUNTIME_KEY,
    ROBOT_RUNTIME_HTTP_TIMEOUT,
    VALID_ROBOT_CONTROL_MODES,
    STUDENTS_FILE,
    COURSES_FILE,
    ensure_data_files,
)
from app.robot.motion_recorder import MotionRecorder
from app.robot.motion_player import MotionPlayer
from app.robot.motion_storage import get_motion_metadata, get_scaled_motion_frames, load_motions
from app.robot.neutral_pose import complete_pose, get_neutral_pose
from app.robot.mapping_resolver import MappingResolver
from app.robot.runtime_registry import get_primary_runtime
from app.utils.logger import setup_logger
from app.storage.process_lock import InterProcessMutex

logger = setup_logger('robot_service')

try:
    import requests as _requests
except ImportError:  # pragma: no cover
    _requests = None

# WebSocket实例（用于发送表情事件）
_socketio = None


def _positive_env_ms(name: str, default: int) -> int:
    """Read a positive millisecond timeout without making startup fragile."""
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


BEHAVIOR_RESERVATION_TIMEOUT_MS = _positive_env_ms(
    "BEHAVIOR_RESERVATION_TIMEOUT_MS",
    8000,
)
BEHAVIOR_AUDIO_DECISION_TIMEOUT_MS = _positive_env_ms(
    "BEHAVIOR_AUDIO_DECISION_TIMEOUT_MS",
    3000,
)
BEHAVIOR_AUDIO_TIMEOUT_MS = _positive_env_ms(
    "BEHAVIOR_AUDIO_TIMEOUT_MS",
    30000,
)
BEHAVIOR_ANIMATION_TIMEOUT_MS = _positive_env_ms(
    "BEHAVIOR_ANIMATION_TIMEOUT_MS",
    60000,
)
BEHAVIOR_START_LEAD_MS = _positive_env_ms(
    "BEHAVIOR_START_LEAD_MS",
    700,
)
BEHAVIOR_FEEDBACK_START_LEAD_MS = _positive_env_ms(
    "BEHAVIOR_FEEDBACK_START_LEAD_MS",
    400,
)
BEHAVIOR_COMMIT_MIN_LEAD_MS = _positive_env_ms(
    "BEHAVIOR_COMMIT_MIN_LEAD_MS",
    200,
)
COMMAND_STATUS_HISTORY_LIMIT = 100
COMMAND_TERMINAL_PHASES = {'completed', 'degraded', 'failed', 'cancelled'}


def set_socketio(socketio):
    """设置SocketIO实例（在app.py中调用）"""
    global _socketio
    _socketio = socketio
    logger.info("SocketIO已绑定到RobotService")


class RobotService:
    """
    机械臂服务
    
    提供动作录制、播放、映射管理的统一接口
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        # 避免重复初始化
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        # 确保数据文件存在
        ensure_data_files()
        
        # 初始化组件
        self._recorder = MotionRecorder()
        self._player = MotionPlayer()
        self._mapping_resolver = MappingResolver()
        try:
            from app.runtime_modes import load_runtime_modes
            self._control_mode = load_runtime_modes()["robot_control_mode"]
        except Exception:
            self._control_mode = ROBOT_CONTROL_MODE
        self._child_room = ROBOT_CHILD_ROOM or None
        # 单事件互斥：行为播放期间的新触发直接失效，不进入等待队列。
        self._sequence_queue: queue.Queue = queue.Queue(maxsize=1)
        self._idle_state_lock = threading.RLock()
        self._idle_generation = 0
        self._idle_timer: Optional[threading.Timer] = None
        self._idle_motion_active = False
        self._idle_motion_request_id: Optional[str] = None
        self._active_sequence_id: Optional[str] = None
        self._active_sequence_deadline = 0.0
        self._behavior_busy = False
        self._busy_event_id: Optional[str] = None
        self._process_behavior_lock = InterProcessMutex(
            Path('.runtime') / 'coordination' / 'robot_behavior.lock'
        )
        # behaviorId -> coordination state. Audio is emitted by a different
        # subsystem/thread, so the worker waits for its dispatch decision and
        # real terminal callback before releasing the single-behavior lock.
        self._behavior_audio_waiters: Dict[str, Dict[str, Any]] = {}
        self._command_status_lock = threading.RLock()
        self._command_status: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._sequence_worker = threading.Thread(
            target=self._sequence_loop,
            daemon=True,
            name='RobotBehaviorSequence',
        )
        self._sequence_worker.start()
        threading.Thread(
            target=self._warm_expression_durations,
            daemon=True,
            name='RobotExpressionDurationWarmup',
        ).start()
        
        self._initialized = True
        logger.info("机械臂服务已初始化，控制模式=%s", self._control_mode)

    @staticmethod
    def _warm_expression_durations() -> None:
        try:
            from app.robot.emotion_assets import warm_expression_duration_cache
            warm_expression_duration_cache()
        except Exception as exc:
            logger.warning('表情时长缓存预热失败: %s', exc)

    def get_control_mode(self) -> str:
        """获取当前机械臂控制模式。"""
        return getattr(self, '_control_mode', ROBOT_CONTROL_MODE)

    def set_control_mode(self, mode: str, *, persist: bool = True) -> None:
        """设置机械臂控制模式；默认写入 runtime_modes.yaml。"""
        if mode not in VALID_ROBOT_CONTROL_MODES:
            raise ValueError(
                "mode must be one of: " + ", ".join(VALID_ROBOT_CONTROL_MODES)
            )
        self._control_mode = mode
        if persist:
            from app.runtime_modes import save_runtime_modes
            save_runtime_modes(robot_control_mode=mode)
        logger.info("机械臂控制模式已切换: %s", mode)
    
    # ========== 录制相关 ==========
    
    @property
    def is_recording(self) -> bool:
        """是否正在录制"""
        return self._recorder.is_recording
    
    def start_recording(self) -> None:
        """开始录制"""
        self._recorder.start()
    
    def add_frame(self, pose_data: Dict[str, float]) -> None:
        """添加录制帧"""
        self._recorder.add_frame(pose_data)
    
    def stop_recording(self, motion_name: Optional[str] = None) -> Dict[str, Any]:
        """
        停止录制并保存
        
        Args:
            motion_name: 动作名称，为空则自动生成
            
        Returns:
            {saved: bool, motionName: str, frameCount: int}
        """
        frames = self._recorder.stop()
        
        if not motion_name:
            motion_name = f"motion_{int(time.time())}"
        
        saved = self._recorder.save(motion_name, frames)
        
        return {
            'saved': saved,
            'motionName': motion_name,
            'frameCount': len(frames)
        }
    
    # ========== 动作管理 ==========
    
    def get_motion_list(self) -> List[Dict[str, Any]]:
        """获取动作列表"""
        return self._recorder.get_motion_list()
    
    def get_motion(self, motion_name: str) -> Optional[List[Dict]]:
        """获取动作详情"""
        return self._recorder.get_motion(motion_name)
    
    def save_motion(self, motion_name: str, frames: List[Dict]) -> bool:
        """保存动作"""
        return self._recorder.save(motion_name, frames)
    
    def delete_motion(self, motion_name: str) -> bool:
        """删除动作"""
        return self._recorder.delete_motion(motion_name)
    
    # ========== 播放相关 ==========
    
    @property
    def is_playing(self) -> bool:
        """是否正在播放"""
        return self._player.is_playing
    
    def play_motion(self, motion_name: str, on_complete: Optional[callable] = None) -> bool:
        """
        播放动作
        
        Args:
            motion_name: 动作名称
            on_complete: 播放完成回调
            
        Returns:
            是否成功开始播放
        """
        if self._control_mode == 'robot_runtime':
            # In the deployed topology Runtime registers outbound to Server,
            # while Windows commonly blocks Server -> Runtime:19091. The child
            # page is on the Runtime machine and can always reach localhost.
            if self._child_agent_online():
                return self._emit_motion_to_child_agent(motion_name, on_complete)
            return self._play_motion_via_runtime(motion_name, on_complete)
        if self._control_mode == 'child_agent':
            return self._emit_motion_to_child_agent(motion_name, on_complete)
        return self._player.play(motion_name, on_complete)
    
    def stop_playback(self) -> bool:
        """停止播放"""
        if self.get_control_mode() == 'robot_runtime':
            return self._runtime_osc_post('/osc/stop', {})
        if self.get_control_mode() == 'child_agent':
            return self._emit_robot_command({
                'type': 'stop_motion',
                'source': 'robot_service',
            })
        self._player.stop()
        return True
    
    def send_realtime(self, pose_data: Dict[str, float]) -> None:
        """实时发送姿态数据"""
        safe_pose = complete_pose(pose_data)
        if self._control_mode == 'robot_runtime':
            self._runtime_osc_post('/osc/frame', {
                'pose': safe_pose,
                'neutralPose': get_neutral_pose(),
            })
            return
        if self._control_mode == 'child_agent':
            self._emit_robot_command({
                'type': 'realtime_pose',
                'source': 'robot_service',
                'payload': {
                    'pose': safe_pose,
                },
            })
            return
        self._player.send_realtime(pose_data)
    
    # ========== 课程事件触发（核心接口） ==========

    def _sequence_loop(self) -> None:
        while True:
            plan = self._sequence_queue.get()
            command_id = str(plan.get('id') or '')
            terminal_phase = 'completed'
            terminal_message = '所有已配置模态均已完成'
            terminal_error = None
            try:
                should_run = self._wait_for_behavior_commit(plan)
                if should_run:
                    self._update_command_status(
                        command_id,
                        phase='running',
                        message='行为正在执行',
                    )
                    with self._idle_state_lock:
                        self._active_sequence_id = plan.get('id')
                        waiter = (
                            self._behavior_audio_waiters.get(plan.get('id'))
                            or {}
                        )
                        visual_deadline = (
                            float(plan.get('startAtMonotonic') or time.monotonic())
                            + self._as_ms(plan.get('durationMs')) / 1000.0
                        )
                        waiter['visualDeadline'] = visual_deadline
                        self._active_sequence_deadline = max(
                            visual_deadline,
                            float(waiter.get('audioDeadline') or 0),
                        )
                    if not plan.get('audioOnly'):
                        self._run_sequence(plan)
                    self._wait_for_behavior_motion(plan)
                    self._wait_for_behavior_expression(plan)
                    self._wait_for_behavior_audio(plan)
                    self._wait_for_behavior_animation(plan)
                else:
                    terminal_phase = 'failed'
                    terminal_message = '行为在输出前被取消或下发决策超时'
                    terminal_error = 'behavior_not_committed'
            except Exception as exc:
                terminal_phase = 'failed'
                terminal_message = '行为执行异常'
                terminal_error = str(exc)
                logger.error('行为序列执行异常: %s', exc, exc_info=True)
                # Commit can fail after speech/animation were already staged.
                # Retract the exact transaction instead of allowing partial
                # output to continue after the worker has failed.
                self.abort_behavior(command_id)
            finally:
                completed_payload = None
                with self._idle_state_lock:
                    if self._active_sequence_id == plan.get('id'):
                        self._active_sequence_id = None
                        self._active_sequence_deadline = 0.0
                    if self._busy_event_id == plan.get('id'):
                        self._behavior_busy = False
                        self._busy_event_id = None
                        self._process_behavior_lock.release()
                    waiter = self._behavior_audio_waiters.pop(plan.get('id'), None)
                    if waiter:
                        expected_audio = int(waiter.get('expectedAudioCount') or 0)
                        completed_audio = int(waiter.get('completedAudioCount') or 0)
                        if expected_audio > 0:
                            audio_status = (
                                'timeout' if waiter.get('audioTimedOut')
                                else 'completed' if completed_audio >= expected_audio
                                else 'incomplete'
                            )
                            self._update_command_status(
                                command_id,
                                component='audio',
                                component_status=audio_status,
                                component_detail=f'{completed_audio}/{expected_audio}',
                            )
                            if audio_status != 'completed' and terminal_phase == 'completed':
                                terminal_phase = 'degraded'
                                terminal_message = '行为已结束，但语音完成回执不完整'
                        else:
                            self._update_command_status(
                                command_id,
                                component='audio',
                                component_status='skipped',
                                component_detail='本次行为无语音输出',
                            )
                        animation_status = str(waiter.get('animationStatus') or 'skipped')
                        self._update_command_status(
                            command_id,
                            component='childAnimation',
                            component_status=animation_status,
                        )
                        if waiter.get('animationDegraded') and terminal_phase == 'completed':
                            terminal_phase = 'degraded'
                            terminal_message = '行为已结束，但儿童端动画降级'
                        completed_payload = {
                            'behaviorId': plan.get('id'),
                            'interactionId': plan.get('id'),
                            'requestId': waiter.get('requestId'),
                            'sessionId': waiter.get('sessionId'),
                            'busy': False,
                            'remainingMs': 0,
                            'animationExpected': bool(
                                waiter.get('animationExpected')
                            ),
                            'animationStatus': waiter.get('animationStatus'),
                            'motionStatus': waiter.get('motionStatus'),
                            'expressionStatus': waiter.get('expressionStatus'),
                            'requiredModalities': sorted(
                                waiter.get('requiredModalities') or []
                            ),
                            'degraded': bool(waiter.get('animationDegraded')) or any(
                                status in ('failed', 'timeout', 'stopped', 'unverified')
                                for status in (
                                    waiter.get('motionStatus'),
                                    waiter.get('expressionStatus'),
                                )
                            ),
                        }
                current_status = self.get_command_status(command_id) or {}
                if current_status.get('phase') in ('cancelled', 'failed'):
                    terminal_phase = current_status.get('phase')
                    terminal_message = current_status.get('message') or '行为已由控制端停止'
                    terminal_error = current_status.get('error')
                component_states = [
                    str(item.get('status') or '')
                    for item in (current_status.get('components') or {}).values()
                    if isinstance(item, dict)
                ]
                if terminal_phase == 'completed' and any(
                    status in ('failed', 'timeout', 'incomplete', 'unverified')
                    for status in component_states
                ):
                    terminal_phase = 'degraded'
                    terminal_message = '行为已结束，但存在未成功执行的模态'
                self._update_command_status(
                    command_id,
                    phase=terminal_phase,
                    message=terminal_message,
                    error=terminal_error,
                )
                if completed_payload is not None:
                    completed_payload.update({
                        'protocolVersion': str(plan.get('protocolVersion') or '1'),
                        'modality': 'multimodal',
                        'status': terminal_phase,
                        'terminalStatus': terminal_phase,
                        'message': terminal_message,
                        'error': terminal_error,
                        'components': {
                            name: {
                                'required': bool(component.get('required')),
                                'status': component.get('status'),
                                'detail': component.get('detail'),
                            }
                            for name, component in (
                                current_status.get('components') or {}
                            ).items()
                            if isinstance(component, dict)
                        },
                    })
                self._sequence_queue.task_done()
                self._emit_behavior_completed(completed_payload)
                self._schedule_idle_pose_if_quiet()

    @staticmethod
    def _as_ms(value: Any, default: int = 0) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return default

    def _ensure_behavior_coordination_state(self) -> None:
        """Keep tests/legacy object construction compatible with new state."""
        if not hasattr(self, '_behavior_audio_waiters'):
            self._behavior_audio_waiters = {}
        if not hasattr(self, '_process_behavior_lock'):
            self._process_behavior_lock = InterProcessMutex(
                Path('.runtime') / 'coordination' / 'robot_behavior.lock'
            )
        for waiter in self._behavior_audio_waiters.values():
            waiter.setdefault('animationDone', threading.Event())
            waiter.setdefault('animationExpected', False)
            waiter.setdefault('animationStatus', 'skipped')
            waiter.setdefault('animationDegraded', False)
            waiter.setdefault('animationDeadline', 0.0)
            waiter.setdefault('motionDone', threading.Event())
            waiter.setdefault('motionExpected', False)
            waiter.setdefault('motionStatus', 'skipped')
            waiter.setdefault('expressionDone', threading.Event())
            waiter.setdefault('expressionExpected', False)
            waiter.setdefault('expressionStatus', 'skipped')
            waiter.setdefault('requiredModalities', frozenset())
            waiter.setdefault('modalitiesFrozen', False)
            waiter.setdefault('cancelDispatched', False)
            waiter.setdefault('startAtServerMs', 0)
            waiter.setdefault('runtimeMotionPrepared', False)
            waiter.setdefault('runtimePrepareAttempted', False)
            waiter.setdefault('runtimeMotionEnvelope', None)
            waiter.setdefault('runtimeBaseUrl', None)
            waiter.setdefault('modalityReady', threading.Event())
            waiter.setdefault('readyModalities', set())
            waiter.setdefault('speechReadyKeys', set())
            waiter.setdefault('animationExpectationDecided', False)

    def _ensure_command_status_state(self) -> None:
        if not hasattr(self, '_command_status_lock'):
            self._command_status_lock = threading.RLock()
        if not hasattr(self, '_command_status'):
            self._command_status = OrderedDict()

    @staticmethod
    def _command_now_ms() -> int:
        return int(time.time() * 1000)

    def _record_command(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Freeze the exact plan accepted by the scheduler for operator review."""
        self._ensure_command_status_state()
        command_id = str(plan.get('id') or '')
        now_ms = self._command_now_ms()
        record = {
            'commandId': command_id,
            'behaviorId': command_id,
            'protocolVersion': str(plan.get('protocolVersion') or '1'),
            'requestId': plan.get('requestId'),
            'sessionId': plan.get('sessionId'),
            'source': str(plan.get('source') or 'runtime'),
            'phase': 'queued',
            'message': '命令已接收，等待执行',
            'controlMode': self.get_control_mode(),
            'motion': plan.get('motion'),
            'emotion': plan.get('emotion'),
            'durationMs': self._as_ms(plan.get('durationMs')),
            'scheduledDelayMs': self._as_ms(plan.get('scheduledDelayMs')),
            'startAtEpochMs': plan.get('startAtEpochMs'),
            'queuedAtMs': now_ms,
            'startedAtMs': None,
            'completedAtMs': None,
            'updatedAtMs': now_ms,
            'components': {
                'expression': {
                    'required': bool(plan.get('emotion')),
                    'status': 'queued' if plan.get('emotion') else 'skipped',
                },
                'motion': {
                    'required': bool(plan.get('motion')),
                    'status': 'queued' if plan.get('motion') else 'skipped',
                },
                'audio': {'required': False, 'status': 'pending_decision'},
                'childAnimation': {'required': False, 'status': 'pending_decision'},
            },
            'warnings': list(plan.get('warnings') or []),
            'error': None,
        }
        with self._command_status_lock:
            self._command_status[command_id] = record
            self._command_status.move_to_end(command_id)
            while len(self._command_status) > COMMAND_STATUS_HISTORY_LIMIT:
                self._command_status.popitem(last=False)
        try:
            from app.behavior.audit_timeline import record_audit_event
            record_audit_event(
                'robot_behavior_queued',
                runtime_session_id=record.get('sessionId'),
                request_id=record.get('requestId'),
                behavior_id=command_id,
                actor='robot_service',
                source=record.get('source') or 'runtime',
                category='robot_execution',
                phase='queued',
                status='queued',
                modality='multimodal',
                details=record,
            )
        except Exception:
            pass
        return dict(record)

    def _update_command_status(
        self,
        command_id: Optional[str],
        *,
        phase: Optional[str] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        component: Optional[str] = None,
        component_required: Optional[bool] = None,
        component_status: Optional[str] = None,
        component_detail: Optional[str] = None,
        component_actual_at_ms: Optional[int] = None,
    ) -> None:
        if not command_id:
            return
        self._ensure_command_status_state()
        now_ms = self._command_now_ms()
        terminal_event = None
        audit_event = None
        with self._command_status_lock:
            record = self._command_status.get(str(command_id))
            if not record:
                return
            previous_phase = record.get('phase')
            if phase:
                record['phase'] = phase
                if phase == 'running' and record.get('startedAtMs') is None:
                    record['startedAtMs'] = now_ms
                if phase in COMMAND_TERMINAL_PHASES:
                    record['completedAtMs'] = now_ms
            if message is not None:
                record['message'] = str(message)
            if error is not None:
                record['error'] = str(error) if error else None
            if component:
                item = record.setdefault('components', {}).setdefault(
                    component, {'required': True}
                )
                if component_required is not None:
                    item['required'] = bool(component_required)
                if component_status:
                    item['status'] = component_status
                    if component_status in ('playing', 'started'):
                        item.setdefault(
                            'actualStartedAtServerMs',
                            int(component_actual_at_ms or now_ms),
                        )
                    if component_status in (
                        'completed', 'failed', 'timeout', 'stopped', 'dropped',
                        'cancelled', 'unverified', 'incomplete',
                    ):
                        item.setdefault(
                            'actualEndedAtServerMs',
                            int(component_actual_at_ms or now_ms),
                        )
                if component_detail is not None:
                    item['detail'] = str(component_detail)
                started_values = [
                    int(value.get('actualStartedAtServerMs'))
                    for value in record.get('components', {}).values()
                    if isinstance(value, dict)
                    and value.get('required')
                    and value.get('actualStartedAtServerMs') is not None
                ]
                if len(started_values) >= 2:
                    record['actualStartSpreadMs'] = max(started_values) - min(started_values)
            record['updatedAtMs'] = now_ms
            audit_event = {
                'event': f"robot_{component or 'behavior'}_status",
                'sessionId': record.get('sessionId'),
                'requestId': record.get('requestId'),
                'behaviorId': str(command_id),
                'source': record.get('source'),
                'phase': phase or record.get('phase'),
                'status': component_status or phase or record.get('phase'),
                'modality': component or 'multimodal',
                'degraded': (
                    (component_status or phase) in (
                        'failed', 'timeout', 'incomplete', 'unverified', 'degraded', 'cancelled'
                    )
                ),
                'error': error,
                'details': {
                    'message': message,
                    'componentDetail': component_detail,
                    'component': component,
                    'components': record.get('components'),
                    'controlMode': record.get('controlMode'),
                    'updatedAtMs': now_ms,
                    'componentActualAtMs': component_actual_at_ms,
                },
            }
            self._command_status.move_to_end(str(command_id))
            if (
                phase in COMMAND_TERMINAL_PHASES
                and phase != previous_phase
            ):
                terminal_event = {
                    'commandId': str(command_id),
                    'phase': phase,
                    'message': record.get('message'),
                    'error': record.get('error'),
                    'source': record.get('source'),
                }
        if audit_event:
            try:
                from app.behavior.audit_timeline import record_audit_event
                record_audit_event(
                    audit_event.pop('event'),
                    runtime_session_id=audit_event.pop('sessionId'),
                    request_id=audit_event.pop('requestId'),
                    behavior_id=audit_event.pop('behaviorId'),
                    actor='robot_service',
                    category='robot_execution',
                    **audit_event,
                )
            except Exception:
                pass
        if terminal_event:
            try:
                from app.monitor.events import append_monitor_event
                append_monitor_event(
                    'robot_command',
                    f"{terminal_event['commandId']} · {terminal_event['message'] or terminal_event['phase']}",
                    level=(
                        'error' if terminal_event['phase'] == 'failed'
                        else 'warn' if terminal_event['phase'] == 'degraded'
                        else 'info'
                    ),
                    extra=terminal_event,
                )
            except Exception:
                pass

    def get_command_status(self, command_id: Optional[str]) -> Optional[Dict[str, Any]]:
        self._ensure_command_status_state()
        if not command_id:
            return None
        with self._command_status_lock:
            item = self._command_status.get(str(command_id))
            if not item:
                return None
            return json.loads(json.dumps(item, ensure_ascii=False))

    def get_control_snapshot(self) -> Dict[str, Any]:
        """Operator truth: configured transport, reachable targets and last command."""
        self._ensure_command_status_state()
        try:
            from app.sockets.events import get_online_presence_snapshot
            presence = get_online_presence_snapshot()
        except Exception:
            presence = {}
        try:
            from app.robot.runtime_registry import get_runtime_status
            runtime = get_runtime_status()
        except Exception:
            runtime = {'onlineCount': 0, 'runtimes': [], 'primary': None}
        mode = self.get_control_mode()
        child_agent_online = int(presence.get('childAgentOnline') or 0) > 0
        runtime_online = int(runtime.get('onlineCount') or 0) > 0
        primary_runtime = runtime.get('primary') or {}
        runtime_compatible = bool(primary_runtime.get('compatible') is True)
        runtime_capabilities = set(primary_runtime.get('capabilities') or [])
        runtime_sync_ready = 'behavior-sync-v1' in runtime_capabilities
        runtime_reason = primary_runtime.get('compatibilityReason')
        display_online = int(presence.get('robotDisplayOnline') or 0) > 0
        control_online = int(presence.get('robotControlOnline') or 0) > 0
        if mode == 'robot_runtime':
            motion_target_ready = bool(
                runtime_online and runtime_compatible and runtime_sync_ready
            )
            if not runtime_online:
                motion_target_detail = 'Robot Runtime 离线'
                verification = 'runtime_offline'
            elif not runtime_compatible:
                motion_target_detail = (
                    f'Robot Runtime 在线但协议不兼容（{runtime_reason or "unknown"}），请升级机器人端'
                )
                verification = 'runtime_incompatible'
            elif not runtime_sync_ready:
                motion_target_detail = 'Robot Runtime 缺少 behavior-sync-v1，请升级机器人端'
                verification = 'runtime_capability_missing'
            else:
                motion_target_detail = 'Robot Runtime 在线且多模态同步协议兼容'
                verification = 'runtime_http_ack'
        elif mode == 'child_agent':
            motion_target_ready = child_agent_online
            motion_target_detail = 'Child Agent 在线' if child_agent_online else 'Child Agent 离线'
            verification = 'socket_dispatch_only'
        else:
            motion_target_ready = True
            motion_target_detail = 'Server OSC 为 UDP 通道，无法确认真机收包'
            verification = 'udp_unverified'
        with self._command_status_lock:
            last = next(reversed(self._command_status.values()), None) if self._command_status else None
            last_copy = json.loads(json.dumps(last, ensure_ascii=False)) if last else None
        return {
            'controlMode': mode,
            'busy': self.get_behavior_busy_state(),
            'targets': {
                'motionReady': motion_target_ready,
                'motionDetail': motion_target_detail,
                'motionVerification': verification,
                'robotRuntimeOnline': runtime_online,
                'robotRuntimeCompatible': runtime_compatible,
                'robotRuntimeCompatibilityReason': runtime_reason,
                'robotRuntimeBuildVersion': primary_runtime.get('buildVersion'),
                'childAgentOnline': child_agent_online,
                'robotDisplayOnline': display_online,
                'robotControlOnline': control_online,
            },
            'lastCommand': last_copy,
        }

    def mark_expression_terminal(
        self,
        command_id: Optional[str],
        *,
        status: str,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        modality: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Apply a correlated terminal emitted by the robot expression page."""
        if not command_id:
            return None
        current = self.get_command_status(str(command_id))
        if not current:
            logger.warning(
                '收到未知表情 ended 回执，无法关联行为: command=%s status=%s',
                command_id, status,
            )
            return None
        strict = bool(current.get('requestId') and current.get('sessionId'))
        if strict and (
            str(request_id or '') != str(current.get('requestId'))
            or str(session_id or '') != str(current.get('sessionId'))
            or str(modality or '') != 'expression'
        ):
            logger.warning(
                '表情 ended 回执与命令不匹配，忽略（回执到达但无法确认）: '
                'command=%s got_request=%s got_session=%s got_modality=%s want_request=%s want_session=%s',
                command_id, request_id, session_id, modality,
                current.get('requestId'), current.get('sessionId'),
            )
            return None
        normalized = str(status or '').strip().lower()
        if normalized not in ('ended', 'error', 'dropped', 'stopped', 'timeout'):
            return None
        existing = (current.get('components') or {}).get('expression') or {}
        if existing.get('status') in (
            'completed', 'failed', 'dropped', 'stopped', 'timeout', 'cancelled'
        ):
            current['idempotentReplay'] = True
            return current
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            waiter = self._behavior_audio_waiters.get(str(command_id))
            if strict and (
                not waiter
                or not waiter.get('expressionExpected')
                or 'expression' not in waiter.get('requiredModalities', frozenset())
            ):
                return None
            if waiter and waiter['expressionDone'].is_set():
                current['idempotentReplay'] = True
                return current
            if waiter:
                waiter['expressionStatus'] = normalized
                waiter['expressionDone'].set()
        component_status = 'completed' if normalized == 'ended' else 'failed'
        self._update_command_status(
            str(command_id),
            component='expression',
            component_status=component_status,
            component_detail=(reason or normalized or 'unknown'),
        )
        refreshed = self.get_command_status(str(command_id)) or {}
        if refreshed.get('phase') in COMMAND_TERMINAL_PHASES:
            components = refreshed.get('components') or {}
            required = [
                item for item in components.values()
                if isinstance(item, dict) and item.get('required')
            ]
            all_ok = bool(required) and all(
                item.get('status') in ('completed', 'skipped') for item in required
            )
            if all_ok:
                self._update_command_status(
                    str(command_id),
                    phase='completed',
                    message='所有已配置模态均已完成并收到回执',
                    error='',
                )
        return self.get_command_status(str(command_id))

    def cancel_active_behavior(self) -> Dict[str, Any]:
        """Operator stop: cancel the active transaction and return honest dispatch results."""
        with self._idle_state_lock:
            active_id = self._busy_event_id
        cancelled = self.abort_behavior(active_id) if active_id else False
        motion_stop_sent = bool(self.stop_playback())
        expression_reset_sent = bool(self.trigger_emotion(
            self.get_default_emotion(),
            restart=True,
            reason='server_control_stop',
        ))
        if active_id:
            terminal_phase = 'cancelled' if motion_stop_sent else 'failed'
            self._update_command_status(
                active_id,
                phase=terminal_phase,
                message=(
                    '行为已由 Server 控制端停止'
                    if motion_stop_sent
                    else '已取消后续调度，但机器人停止命令下发失败'
                ),
                error='' if motion_stop_sent else 'robot_stop_dispatch_failed',
                component='motion',
                component_status='cancelled',
                component_detail='已发送停止命令' if motion_stop_sent else '停止命令下发失败',
            )
        return {
            'success': bool(motion_stop_sent),
            'activeBehaviorId': active_id,
            'behaviorCancelled': bool(cancelled),
            'motionStopSent': motion_stop_sent,
            'expressionResetSent': expression_reset_sent,
            'partial': bool(expression_reset_sent or cancelled) and not motion_stop_sent,
            'controlMode': self.get_control_mode(),
        }

    def _new_behavior_waiter(
        self,
        behavior_id: str,
        *,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        protocol_version: str = '1',
        pre_reserved: bool = False,
    ) -> Dict[str, Any]:
        now = time.monotonic()
        return {
            'behaviorId': behavior_id,
            'requestId': request_id,
            'sessionId': str(session_id) if session_id else None,
            'protocolVersion': str(protocol_version or '1'),
            'strictEnvelope': bool(request_id and session_id),
            'preReserved': bool(pre_reserved),
            'sequenceEnqueued': False,
            'visualStarted': False,
            'aborted': False,
            'cancelDispatched': False,
            'startAtServerMs': 0,
            'runtimeMotionPrepared': False,
            'runtimePrepareAttempted': False,
            'runtimeMotionEnvelope': None,
            'runtimeBaseUrl': None,
            'modalityReady': threading.Event(),
            'readyModalities': set(),
            'speechReadyKeys': set(),
            'animationExpectationDecided': False,
            'dispatchReady': threading.Event(),
            'audioDone': threading.Event(),
            'animationDone': threading.Event(),
            'animationExpected': False,
            'animationStatus': 'skipped',
            'animationDegraded': False,
            'expectedAudioCount': None,
            'completedAudioCount': 0,
            'completionKeys': set(),
            'visualDeadline': 0.0,
            'audioDeadline': 0.0,
            'animationDeadline': 0.0,
            'motionDone': threading.Event(),
            'motionExpected': False,
            'motionStatus': 'skipped',
            'expressionDone': threading.Event(),
            'expressionExpected': False,
            'expressionStatus': 'skipped',
            'requiredModalities': frozenset(),
            'modalitiesFrozen': False,
            'reservationDeadline': (
                now + BEHAVIOR_RESERVATION_TIMEOUT_MS / 1000.0
            ),
        }

    def _clear_stale_reservation_locked(self) -> None:
        """Keep an in-flight request reserved until its owner commits or aborts.

        The old wall-clock expiry could release the slot while
        ``PlayResourceHandler`` was still opening media/database state.  A retry
        could then reserve the same global robot slot and mutate that state in
        parallel.  Socket handlers already abort explicitly on every failure
        path, so an actively owned reservation must never be reclaimed merely
        because processing took longer than the optimistic UI deadline.
        """
        if not self._behavior_busy or not self._busy_event_id:
            return
        self._ensure_behavior_coordination_state()
        waiter = self._behavior_audio_waiters.get(self._busy_event_id)
        if not waiter or waiter.get('sequenceEnqueued'):
            return
        if time.monotonic() < float(waiter.get('reservationDeadline') or 0):
            return
        if not waiter.get('expiryWarned'):
            waiter['expiryWarned'] = True
            logger.warning(
                '行为预占处理超过预期，继续保留原子槽位直至显式提交/回滚 id=%s',
                self._busy_event_id,
            )
        # Keep a small positive retry hint while the owning handler is alive.
        waiter['reservationDeadline'] = time.monotonic() + 1.0
        self._active_sequence_deadline = waiter['reservationDeadline']

    def reserve_behavior(
        self,
        *,
        behavior_id: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically reserve the one behavior slot before any course side effect."""
        reserved_id = str(
            behavior_id or f'behavior-{uuid.uuid4().hex[:12]}'
        )
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            self._clear_stale_reservation_locked()
            if self._behavior_busy:
                state = self.get_behavior_busy_state()
                return {
                    'accepted': False,
                    'busy': True,
                    'behaviorId': state.get('eventId'),
                    'activeBehaviorId': state.get('eventId'),
                    'interactionId': state.get('eventId'),
                    'requestId': request_id,
                    'remainingMs': state.get('remainingMs', 0),
                    'reason': 'behavior_busy',
                }

            if not self._process_behavior_lock.acquire(blocking=False):
                return {
                    'accepted': False,
                    'busy': True,
                    'behaviorId': None,
                    'activeBehaviorId': None,
                    'interactionId': None,
                    'requestId': request_id,
                    'remainingMs': BEHAVIOR_RESERVATION_TIMEOUT_MS,
                    'reason': 'cross_process_behavior_busy',
                }

            waiter = self._new_behavior_waiter(
                reserved_id,
                request_id=request_id,
                session_id=session_id,
                protocol_version='1',
                pre_reserved=True,
            )
            self._behavior_audio_waiters[reserved_id] = waiter
            self._behavior_busy = True
            self._busy_event_id = reserved_id
            self._active_sequence_deadline = waiter['reservationDeadline']
            self._idle_generation += 1
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
            return {
                'accepted': True,
                'busy': False,
                'behaviorId': reserved_id,
                'activeBehaviorId': reserved_id,
                'interactionId': reserved_id,
                'requestId': request_id,
                'remainingMs': BEHAVIOR_RESERVATION_TIMEOUT_MS,
            }

    def reserve_audio_only_behavior(
        self,
        *,
        behavior_id: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reserve and enqueue a behavior whose only output is correlated TTS.

        The queue worker uses the same dispatch/terminal barrier as a visual
        behavior, but skips expression and motion output.  The caller must
        either call ``set_behavior_audio_expected`` after emitting TTS or
        ``abort_behavior`` when dispatch fails.
        """
        reservation = self.reserve_behavior(
            behavior_id=behavior_id,
            request_id=request_id,
            session_id=session_id,
        )
        if not reservation.get('accepted'):
            return reservation

        reserved_id = str(reservation.get('behaviorId'))
        plan = {
            'id': reserved_id,
            'requestId': request_id,
            'sessionId': str(session_id) if session_id else None,
            'durationMs': 0,
            'expressionDurationMs': 0,
            'motionDurationMs': 0,
            'motionEndMs': 0,
            'motionOffsetMs': 0,
            'audioOffsetMs': 0,
            'motion': None,
            'emotion': None,
            'audioOnly': True,
        }
        if self._enqueue_sequence(plan):
            return reservation

        self.abort_behavior(reserved_id)
        state = self.get_behavior_busy_state()
        return {
            'accepted': False,
            'busy': bool(state.get('busy')),
            'behaviorId': state.get('eventId'),
            'activeBehaviorId': state.get('eventId'),
            'interactionId': state.get('eventId'),
            'requestId': request_id,
            'remainingMs': int(state.get('remainingMs') or 0),
            'reason': 'behavior_busy',
        }

    def abort_behavior(self, behavior_id: Optional[str]) -> bool:
        """Abort one exact transaction and retract every staged output."""
        if not behavior_id:
            return False
        behavior_id = str(behavior_id)
        completed_payload = None
        cancel_payload = None
        cancel_runtime_motion = False
        runtime_cancel_envelope = None
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter:
                return False
            waiter['aborted'] = True
            waiter['expectedAudioCount'] = 0
            waiter['dispatchReady'].set()
            waiter['audioDone'].set()
            waiter['animationStatus'] = 'stopped'
            waiter['animationDegraded'] = bool(
                waiter.get('animationExpected')
            )
            waiter['animationDone'].set()
            waiter['motionStatus'] = 'stopped' if waiter.get('motionExpected') else 'skipped'
            waiter['motionDone'].set()
            waiter['expressionStatus'] = (
                'stopped' if waiter.get('expressionExpected') else 'skipped'
            )
            waiter['expressionDone'].set()
            if not waiter.get('cancelDispatched') and waiter.get('strictEnvelope'):
                waiter['cancelDispatched'] = True
                cancel_payload = {
                    'protocolVersion': str(waiter.get('protocolVersion') or '1'),
                    'sessionId': str(waiter.get('sessionId') or ''),
                    'requestId': str(waiter.get('requestId') or ''),
                    'behaviorId': behavior_id,
                    'startAtServerMs': int(waiter.get('startAtServerMs') or 0),
                    'modality': 'multimodal',
                    'status': 'cancelled',
                    'terminalStatus': 'cancelled',
                    'reason': 'behavior_aborted',
                }
                cancel_runtime_motion = bool(waiter.get('runtimePrepareAttempted'))
                runtime_cancel_envelope = waiter.get('runtimeMotionEnvelope')
            if waiter.get('sequenceEnqueued'):
                # The worker owns final lock release.  Its waits are unblocked
                # above, while clients receive an exact correlated cancellation.
                pass
            else:
                self._behavior_audio_waiters.pop(behavior_id, None)
                if self._busy_event_id == behavior_id:
                    self._behavior_busy = False
                    self._busy_event_id = None
                    self._active_sequence_deadline = 0.0
                    self._process_behavior_lock.release()
                completed_payload = {
                    'behaviorId': behavior_id,
                    'interactionId': behavior_id,
                    'requestId': waiter.get('requestId'),
                    'sessionId': waiter.get('sessionId'),
                    'busy': False,
                    'remainingMs': 0,
                    'status': 'cancelled',
                    'terminalStatus': 'cancelled',
                    'degraded': True,
                    'message': '行为已在输出前取消',
                    'error': 'behavior_aborted',
                }
        if cancel_payload:
            self._cancel_behavior_outputs(
                cancel_payload,
                cancel_runtime_motion=cancel_runtime_motion,
                runtime_envelope=runtime_cancel_envelope,
                runtime_base_url=(
                    str(waiter.get('runtimeBaseUrl') or '') or None
                ),
            )
        self._emit_behavior_completed(completed_payload)
        return True

    def _cancel_behavior_outputs(
        self,
        envelope: Dict[str, Any],
        *,
        cancel_runtime_motion: bool = False,
        runtime_envelope: Optional[Dict[str, Any]] = None,
        runtime_base_url: Optional[str] = None,
    ) -> None:
        """Best-effort fan-out of one exact cancellation to every modality."""
        if _socketio:
            try:
                # Robot display is not session-room bound.  Every client still
                # validates the three IDs before touching local playback.
                _socketio.emit('behavior_cancel', dict(envelope))
            except Exception as exc:
                logger.warning('发送 behavior_cancel 失败: %s', exc)
        if cancel_runtime_motion and self.get_control_mode() == 'robot_runtime':
            motion_envelope = dict(runtime_envelope or {
                **envelope,
                'modality': 'motion',
            })
            body = self._runtime_json_post_pinned(
                '/behavior/cancel',
                motion_envelope,
                runtime_base_url,
            )
            if body is None:
                logger.warning(
                    'Runtime 未确认行为取消 behaviorId=%s requestId=%s',
                    envelope.get('behaviorId'), envelope.get('requestId'),
                )

    def set_behavior_audio_expected(
        self,
        behavior_id: Optional[str],
        expected_count: int,
        *,
        session_id: Optional[str] = None,
        timeout_ms: Optional[int] = None,
    ) -> bool:
        """Publish how many real audio completions gate behavior release."""
        if not behavior_id:
            return False
        behavior_id = str(behavior_id)
        expected = max(0, int(expected_count or 0))
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter:
                return False
            if session_id:
                waiter['sessionId'] = str(session_id)
            waiter['expectedAudioCount'] = expected
            if expected <= int(waiter.get('completedAudioCount') or 0):
                waiter['audioDone'].set()
                audio_deadline = time.monotonic()
            else:
                timeout = max(
                    1,
                    int(timeout_ms or BEHAVIOR_AUDIO_TIMEOUT_MS),
                )
                audio_deadline = time.monotonic() + timeout / 1000.0
                waiter['audioDeadline'] = audio_deadline
            waiter['dispatchReady'].set()
            self._refresh_behavior_ready_locked(waiter)
            self._active_sequence_deadline = max(
                float(waiter.get('visualDeadline') or 0),
                audio_deadline,
            )
        self._update_command_status(
            behavior_id,
            component='audio',
            component_required=expected > 0,
            component_status='playing' if expected > 0 else 'skipped',
            component_detail=(
                f'等待 {expected} 个关联完成回执'
                if expected > 0 else '本次行为无语音输出'
            ),
        )
        return True

    def mark_behavior_audio_complete(
        self,
        *,
        behavior_id: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        modality: Optional[str] = None,
        status: Optional[str] = None,
        completion_key: Optional[str] = None,
    ) -> Optional[str]:
        """Mark one correlated browser/file output terminal.

        A terminal without ``behavior_id`` may belong to an older, unrelated
        utterance in the same runtime session.  Falling back to the currently
        busy behavior lets that late callback release a newer action early, so
        uncorrelated terminals are intentionally ignored.
        """
        if not behavior_id:
            return None
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            resolved_id = str(behavior_id)
            waiter = self._behavior_audio_waiters.get(resolved_id or '')
            if not waiter:
                return None
            expected_session = waiter.get('sessionId')
            if waiter.get('strictEnvelope') and (
                str(request_id or '') != str(waiter.get('requestId') or '')
                or str(session_id or '') != str(expected_session or '')
                or str(modality or '') != 'speech'
            ):
                return None
            normalized_status = str(status or 'ended').strip().lower()
            if normalized_status not in (
                'ended', 'error', 'stopped', 'dropped', 'timeout'
            ):
                return None
            if (
                session_id
                and expected_session
                and str(session_id) != str(expected_session)
            ):
                return None
            key = str(completion_key or '').strip()
            if key and key in waiter['completionKeys']:
                return resolved_id
            if key:
                waiter['completionKeys'].add(key)
            waiter['completedAudioCount'] = (
                int(waiter.get('completedAudioCount') or 0) + 1
            )
            expected = waiter.get('expectedAudioCount')
            if expected is not None and waiter['completedAudioCount'] >= int(expected):
                waiter['audioDone'].set()
                self._active_sequence_deadline = max(
                    float(waiter.get('visualDeadline') or 0),
                    time.monotonic(),
                )
            completed_count = int(waiter.get('completedAudioCount') or 0)
            expected_count = int(expected or 0)
        self._update_command_status(
            resolved_id,
            component='audio',
            component_required=expected_count > 0,
            component_status=(
                'completed' if expected_count > 0 and completed_count >= expected_count
                else 'playing'
            ),
            component_detail=f'{completed_count}/{expected_count}',
        )
        return resolved_id

    def set_behavior_animation_expected(
        self,
        behavior_id: Optional[str],
        expected: bool,
        *,
        session_id: Optional[str] = None,
        timeout_ms: Optional[int] = None,
    ) -> bool:
        """Register the child-screen MP4 before the behavior is committed."""
        if not behavior_id:
            return False
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            waiter = self._behavior_audio_waiters.get(str(behavior_id))
            if not waiter:
                return False
            if session_id:
                waiter['sessionId'] = str(session_id)
            waiter['animationExpected'] = bool(expected)
            waiter['animationExpectationDecided'] = True
            if not expected:
                waiter['animationStatus'] = 'skipped'
                waiter['animationDone'].set()
                update_status = 'skipped'
            else:
                waiter['animationStatus'] = 'pending'
                deadline = time.monotonic() + max(
                    1,
                    int(timeout_ms or BEHAVIOR_ANIMATION_TIMEOUT_MS),
                ) / 1000.0
                waiter['animationDeadline'] = deadline
                self._active_sequence_deadline = max(
                    self._active_sequence_deadline,
                    deadline,
                )
                update_status = 'playing'
            self._refresh_behavior_ready_locked(waiter)
        self._update_command_status(
            behavior_id,
            component='childAnimation',
            component_required=bool(expected),
            component_status=update_status,
        )
        return True

    def mark_behavior_animation_complete(
        self,
        *,
        behavior_id: Optional[str],
        request_id: Optional[str],
        session_id: Optional[str],
        status: str,
        modality: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Accept one fully correlated child animation terminal."""
        if not behavior_id or not request_id or not session_id:
            return None
        normalized_status = str(status or '').strip().lower()
        if normalized_status not in ('ended', 'error', 'dropped', 'stopped'):
            return None
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            waiter = self._behavior_audio_waiters.get(str(behavior_id))
            if not waiter or not waiter.get('animationExpected'):
                return None
            if waiter.get('strictEnvelope') and str(modality or '') != 'childAnimation':
                return None
            if str(waiter.get('requestId') or '') != str(request_id):
                return None
            if str(waiter.get('sessionId') or '') != str(session_id):
                return None
            if waiter['animationDone'].is_set():
                return {
                    'behaviorId': str(behavior_id),
                    'status': waiter.get('animationStatus'),
                    'degraded': bool(waiter.get('animationDegraded')),
                    'idempotentReplay': True,
                }
            waiter['animationStatus'] = normalized_status
            waiter['animationDegraded'] = normalized_status != 'ended'
            waiter['animationDone'].set()
            self._active_sequence_deadline = max(
                float(waiter.get('visualDeadline') or 0),
                float(waiter.get('audioDeadline') or 0),
                time.monotonic(),
            )
            result = {
                'behaviorId': str(behavior_id),
                'status': normalized_status,
                'degraded': normalized_status != 'ended',
                'idempotentReplay': False,
            }
        self._update_command_status(
            str(behavior_id),
            component='childAnimation',
            component_required=True,
            component_status=(
                'completed' if normalized_status == 'ended' else normalized_status
            ),
        )
        return result

    def mark_behavior_motion_event(
        self,
        *,
        behavior_id: Optional[str],
        request_id: Optional[str],
        session_id: Optional[str],
        modality: Optional[str],
        status: Optional[str],
        reason: Optional[str] = None,
        actual_at_runtime_ms: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Accept only an exact Runtime motion event for the active behavior."""
        if not behavior_id or not request_id or not session_id or modality != 'motion':
            return None
        normalized = str(status or '').strip().lower()
        if normalized not in ('started', 'ended', 'failed', 'stopped', 'timeout'):
            return None
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            waiter = self._behavior_audio_waiters.get(str(behavior_id))
            if not waiter or not waiter.get('motionExpected'):
                return None
            if (
                str(waiter.get('requestId') or '') != str(request_id)
                or str(waiter.get('sessionId') or '') != str(session_id)
            ):
                return None
            if waiter['motionDone'].is_set():
                return {
                    'behaviorId': str(behavior_id),
                    'status': waiter.get('motionStatus'),
                    'idempotentReplay': True,
                }
            waiter['motionStatus'] = normalized
            runtime_offset_ms = float(waiter.get('runtimeClockOffsetMs') or 0.0)
            if normalized != 'started':
                waiter['motionDone'].set()
        normalized_actual_ms = None
        try:
            if actual_at_runtime_ms is not None:
                normalized_actual_ms = int(round(
                    float(actual_at_runtime_ms) - runtime_offset_ms
                ))
        except (TypeError, ValueError):
            normalized_actual_ms = None
        self._update_command_status(
            str(behavior_id),
            component='motion',
            component_required=True,
            component_status=(
                'playing' if normalized == 'started'
                else 'completed' if normalized == 'ended'
                else normalized
            ),
            component_detail=(
                f'Runtime actualAt={actual_at_runtime_ms}'
                + (f' reason={reason}' if reason else '')
            ),
            component_actual_at_ms=normalized_actual_ms,
        )
        return {
            'behaviorId': str(behavior_id),
            'status': normalized,
            'idempotentReplay': False,
        }

    def mark_behavior_modality_started(
        self,
        *,
        behavior_id: Optional[str],
        request_id: Optional[str],
        session_id: Optional[str],
        modality: Optional[str],
        actual_at_ms: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record an exact actual-start callback without changing terminal state."""
        modality_name = str(modality or '')
        component = {
            'speech': 'audio',
            'expression': 'expression',
            'childAnimation': 'childAnimation',
        }.get(modality_name)
        if not component or not behavior_id or not request_id or not session_id:
            return None
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            waiter = self._behavior_audio_waiters.get(str(behavior_id))
            if not waiter or not waiter.get('modalitiesFrozen'):
                return None
            if (
                str(waiter.get('requestId') or '') != str(request_id)
                or str(waiter.get('sessionId') or '') != str(session_id)
                or modality_name not in waiter.get('requiredModalities', frozenset())
            ):
                return None
            terminal_event = {
                'speech': waiter['audioDone'],
                'expression': waiter['expressionDone'],
                'childAnimation': waiter['animationDone'],
            }[modality_name]
            if terminal_event.is_set():
                return None
            if modality_name == 'expression':
                started_at = time.monotonic()
                duration_ms = int(
                    waiter.get('expressionDurationMs')
                    or waiter.get('durationMs')
                    or 0
                )
                waiter['expressionStartedAt'] = started_at
                waiter['visualDeadline'] = started_at + max(0, duration_ms) / 1000.0 + 1.0
                self._active_sequence_deadline = max(
                    float(waiter.get('visualDeadline') or 0),
                    float(waiter.get('audioDeadline') or 0),
                )
        self._update_command_status(
            str(behavior_id),
            component=component,
            component_required=True,
            component_status='playing',
            component_detail=f'实际启动时间={actual_at_ms}',
        )
        return {
            'behaviorId': str(behavior_id),
            'modality': modality_name,
            'status': 'started',
        }

    @staticmethod
    def _refresh_behavior_ready_locked(waiter: Dict[str, Any]) -> bool:
        ready = set(waiter.get('readyModalities') or set())
        speech_ready = len(waiter.get('speechReadyKeys') or set())
        required_ready = (
            (not waiter.get('expressionExpected') or 'expression' in ready)
            and (
                int(waiter.get('expectedAudioCount') or 0) <= 0
                or speech_ready >= int(waiter.get('expectedAudioCount') or 0)
            )
            and (not waiter.get('animationExpected') or 'childAnimation' in ready)
        )
        if required_ready:
            waiter['modalityReady'].set()
        else:
            waiter['modalityReady'].clear()
        return required_ready

    def mark_behavior_modality_ready(
        self,
        *,
        behavior_id: Optional[str],
        request_id: Optional[str],
        session_id: Optional[str],
        modality: Optional[str],
        readiness_key: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Accept a pre-anchor ready ACK for one exact client modality."""
        name = str(modality or '')
        if name not in {'speech', 'expression', 'childAnimation'}:
            return None
        if not behavior_id or not request_id or not session_id:
            return None
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            waiter = self._behavior_audio_waiters.get(str(behavior_id))
            if not waiter or waiter.get('aborted'):
                return None
            if (
                str(waiter.get('requestId') or '') != str(request_id)
                or str(waiter.get('sessionId') or '') != str(session_id)
            ):
                return None
            expected = {
                'speech': (
                    waiter.get('expectedAudioCount') is None
                    or int(waiter.get('expectedAudioCount') or 0) > 0
                ),
                'expression': bool(waiter.get('expressionExpected')),
                'childAnimation': (
                    not waiter.get('animationExpectationDecided')
                    or bool(waiter.get('animationExpected'))
                ),
            }[name]
            if not expected:
                return None
            if name == 'speech':
                key = str(readiness_key or '').strip()
                if not key:
                    return None
                waiter['speechReadyKeys'].add(key)
            else:
                waiter['readyModalities'].add(name)
            all_ready = self._refresh_behavior_ready_locked(waiter)
            return {
                'behaviorId': str(behavior_id),
                'modality': name,
                'ready': True,
                'allRequiredReady': all_ready,
                'speechReadyCount': len(waiter.get('speechReadyKeys') or set()),
            }

    def _wait_for_behavior_audio(self, plan: Dict[str, Any]) -> None:
        behavior_id = str(plan.get('id') or '')
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter:
                return
            dispatch_ready = waiter['dispatchReady']

        if not dispatch_ready.wait(BEHAVIOR_AUDIO_DECISION_TIMEOUT_MS / 1000.0):
            logger.warning(
                '行为 %s 未收到语音下发决策，按无语音完成',
                behavior_id,
            )
            self.set_behavior_audio_expected(behavior_id, 0)

        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter:
                return
            expected = int(waiter.get('expectedAudioCount') or 0)
            audio_done = waiter['audioDone']
            deadline = float(waiter.get('audioDeadline') or time.monotonic())
        if expected <= 0:
            return
        timeout = max(0.0, deadline - time.monotonic())
        if not audio_done.wait(timeout):
            with self._idle_state_lock:
                current = self._behavior_audio_waiters.get(behavior_id)
                if current:
                    current['audioTimedOut'] = True
            logger.warning(
                '行为语音完成回传超时，保守释放 id=%s expected=%s completed=%s',
                behavior_id,
                expected,
                waiter.get('completedAudioCount'),
            )

    def _wait_for_behavior_animation(self, plan: Dict[str, Any]) -> None:
        behavior_id = str(plan.get('id') or '')
        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter or not waiter.get('animationExpected'):
                return
            animation_done = waiter['animationDone']
            deadline = float(
                waiter.get('animationDeadline') or time.monotonic()
            )
        timeout = max(0.0, deadline - time.monotonic())
        if animation_done.wait(timeout):
            return
        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter or waiter['animationDone'].is_set():
                return
            waiter['animationStatus'] = 'timeout'
            waiter['animationDegraded'] = True
            waiter['animationDone'].set()
        logger.warning('行为动画完成回传超时，降级释放 id=%s', behavior_id)

    def _wait_for_behavior_motion(self, plan: Dict[str, Any]) -> None:
        behavior_id = str(plan.get('id') or '')
        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter or not waiter.get('motionExpected'):
                return
            motion_done = waiter['motionDone']
        if motion_done.wait(0.35):
            return
        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter or waiter['motionDone'].is_set():
                return
            waiter['motionStatus'] = 'timeout'
            waiter['motionDone'].set()
        self._update_command_status(
            behavior_id,
            component='motion',
            component_required=True,
            component_status='timeout',
            component_detail='Runtime ended 回执超时，按降级释放',
        )
        logger.warning('Runtime 动作完成回传超时，降级释放 id=%s', behavior_id)

    def _wait_for_behavior_expression(self, plan: Dict[str, Any]) -> None:
        behavior_id = str(plan.get('id') or '')
        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter or not waiter.get('expressionExpected'):
                return
            expression_done = waiter['expressionDone']
        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(behavior_id)
            deadline = float((waiter or {}).get('visualDeadline') or time.monotonic())
        if expression_done.wait(max(0.35, deadline - time.monotonic())):
            return
        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter or waiter['expressionDone'].is_set():
                return
            waiter['expressionStatus'] = 'unverified'
            waiter['expressionDone'].set()
        self._update_command_status(
            behavior_id,
            component='expression',
            component_required=True,
            component_status='unverified',
            component_detail='表情计划结束后未及时收到 ended，允许迟到回执完成收敛',
        )
        logger.warning('表情完成回传未及时到达，按 unverified 释放 id=%s', behavior_id)

    def _stage_behavior_expression(self, plan: Dict[str, Any]) -> bool:
        if plan.get('audioOnly') or not plan.get('emotion'):
            plan['expressionDispatched'] = False
            return True
        sequence_id = str(plan.get('id') or '')
        start_at = float(plan.get('startAtMonotonic') or time.monotonic())
        start_epoch_ms = int(plan.get('startAtEpochMs') or round(time.time() * 1000))
        sent = self.trigger_emotion(
            plan['emotion'],
            sequenceId=sequence_id,
            behaviorId=sequence_id,
            protocolVersion=str(plan.get('protocolVersion') or '1'),
            requestId=plan.get('requestId'),
            sessionId=plan.get('sessionId'),
            modality='expression',
            durationMs=plan['expressionDurationMs'],
            startAtServerMs=start_epoch_ms,
            startAtEpochMs=start_epoch_ms,
            startDelayMs=max(0, int(round((start_at - time.monotonic()) * 1000.0))),
            restart=True,
            **(
                {'dialogueReply': True, 'source': 'dialogue'}
                if plan.get('dialogueReply') else {}
            ),
        )
        plan['expressionDispatched'] = bool(sent)
        self._update_command_status(
            sequence_id,
            component='expression',
            component_status='prepared' if sent else 'failed',
            component_detail=(
                '已发送表情预加载与共同锚点'
                if sent else 'Socket.IO 未绑定或表情排程发送失败'
            ),
        )
        return bool(sent) or not plan.get('sessionId')

    def _wait_for_behavior_commit(self, plan: Dict[str, Any]) -> bool:
        """Wait until audio dispatch is decided before exposing visual output."""
        behavior_id = str(plan.get('id') or '')
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter:
                return False
            dispatch_ready = waiter['dispatchReady']

        if not dispatch_ready.wait(
            BEHAVIOR_AUDIO_DECISION_TIMEOUT_MS / 1000.0
        ):
            logger.warning(
                '行为 %s 未收到语音下发决策，按原子失败中止',
                behavior_id,
            )
            if not any(plan.get(key) for key in ('motion', 'emotion', 'sequence')):
                self.abort_behavior(behavior_id)
                return False
            # Audio dispatch is one modality, not a transaction-wide gate.
            # Keep the behavior alive so motion/expression can still provide
            # feedback and the next click starts from a clean waiter state.
            with self._idle_state_lock:
                current = self._behavior_audio_waiters.get(behavior_id)
                if current:
                    current['audioDispatchTimedOut'] = True
                    current['audioStatus'] = 'failed'
                    current['audioDetail'] = 'audio dispatch decision timeout'
                    current['dispatchReady'].set()

        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter or waiter.get('aborted'):
                return False

        if not self._stage_behavior_expression(plan):
            logger.warning('行为 %s 的表情下发失败，继续执行其他模态', behavior_id)
            with self._idle_state_lock:
                current = self._behavior_audio_waiters.get(behavior_id)
                if current:
                    current['expressionStatus'] = 'failed'
                    current['expressionDone'].set()

        if (
            plan.get('motion')
            and self.get_control_mode() == 'robot_runtime'
        ):
            if self._child_agent_online():
                # Preferred production path: server socket -> child page ->
                # localhost Runtime. It avoids LAN firewall/NAT entirely.
                plan['motionViaChildRelay'] = True
                self._update_command_status(
                    behavior_id,
                    component='motion',
                    component_required=True,
                    component_status='relay_ready',
                    component_detail='儿童端本机 Runtime 转发通道已就绪',
                )
            elif not self._prepare_runtime_motion(plan):
                # A motion transport failure must never cancel speech,
                # expression, or child animation that are already staged.
                plan['runtimePrepareFailed'] = True
                self._update_command_status(
                    behavior_id,
                    component='motion',
                    component_required=True,
                    component_status='fallback_pending',
                    component_detail='Runtime 同步准备失败，将在锚点直接下发动作',
                )

        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter or waiter.get('aborted'):
                return False
            required = set()
            if waiter.get('expressionExpected'):
                required.add('expression')
            if waiter.get('motionExpected'):
                required.add('motion')
            if int(waiter.get('expectedAudioCount') or 0) > 0:
                required.add('speech')
            if waiter.get('animationExpected'):
                required.add('childAnimation')
            waiter['requiredModalities'] = frozenset(required)
            waiter['modalitiesFrozen'] = True
            all_ready = self._refresh_behavior_ready_locked(waiter)
            modality_ready = waiter['modalityReady']

        if not all_ready:
            ready_deadline_ms = (
                int(plan.get('startAtEpochMs') or 0)
                - BEHAVIOR_COMMIT_MIN_LEAD_MS
            )
            timeout = max(0.0, (ready_deadline_ms - int(time.time() * 1000)) / 1000.0)
            if timeout <= 0 or not modality_ready.wait(timeout):
                # Client ready ACKs are telemetry, not a second class-start
                # gate. The server has already accepted the audio decision,
                # expression dispatch, and (when available) Runtime prepare.
                # Cancelling here races with real audio/animation output and
                # leaves the robot reporting behavior_not_committed even though
                # the instruction was already being performed.
                logger.warning(
                    '行为 %s 的客户端模态未在安全窗内 ready，继续执行并记录诊断 required=%s',
                    behavior_id, sorted(required),
                )
                with self._idle_state_lock:
                    current = self._behavior_audio_waiters.get(behavior_id)
                    if current:
                        ready_names = set(current.get('readyModalities') or set())
                        if current.get('runtimeMotionPrepared'):
                            ready_names.add('motion')
                        if len(current.get('speechReadyKeys') or set()) >= int(
                            current.get('expectedAudioCount') or 0
                        ):
                            ready_names.add('speech')
                        current['readinessDegraded'] = True
                        current['readinessMissing'] = sorted(required - ready_names)

        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(behavior_id)
            if not waiter or waiter.get('aborted'):
                return False
            # This transition is atomic with abort_behavior(): once true, an
            # abort preserves the already-visible plan; before it, abort skips
            # the plan entirely.
            waiter['visualStarted'] = True
            return True

    def _behavior_cancelled(self, behavior_id: str) -> bool:
        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(str(behavior_id))
            return bool(waiter and waiter.get('aborted'))

    @staticmethod
    def _emit_behavior_completed(payload: Optional[Dict[str, Any]]) -> None:
        if not payload or not _socketio:
            return
        try:
            session_id = payload.get('sessionId')
            if session_id:
                _socketio.emit(
                    'behavior_completed',
                    payload,
                    room=f'session_{session_id}_teacher',
                )
        except Exception as exc:
            logger.warning('发送 behavior_completed 失败: %s', exc)

    def _build_sequence_plan(
        self,
        *,
        motion: Optional[str],
        emotion: str,
        sequence: Optional[Dict[str, Any]],
        event_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """把绑定配置和动作元数据合并成以表情为原点的单一时间轴。"""
        sequence = sequence if isinstance(sequence, dict) else {}
        source = event_data or {}
        audio = sequence.get('audio') if isinstance(sequence.get('audio'), dict) else {}
        metadata = get_motion_metadata(motion) if motion else {}
        imported_expression = metadata.get('expression') if isinstance(metadata.get('expression'), dict) else {}
        imported_media = str(imported_expression.get('mediaId') or '').strip()

        expression = (
            str(sequence.get('expressionMediaId') or '').strip()
            or str(emotion or '').strip()
            or str(imported_expression.get('mediaId') or '').strip()
            or self.get_default_emotion()
        )
        duration_ms = self._as_ms(sequence.get('expressionDurationMs'))
        duration_already_scaled = False
        same_as_imported = bool(imported_media) and (
            expression.replace('\\', '/').split('/')[-1]
            == imported_media.replace('\\', '/').split('/')[-1]
        )
        if not duration_ms and same_as_imported:
            duration_ms = self._as_ms(imported_expression.get('durationMs'))
        if not duration_ms:
            from app.robot.emotion_assets import get_expression_duration_ms
            duration_ms = get_expression_duration_ms(expression)
            duration_already_scaled = bool(duration_ms)
        if not duration_ms and same_as_imported:
            duration_ms = self._as_ms(metadata.get('durationMs'))
        # 视频无元数据、旧 GIF 解析失败时才保守回退 3 秒。
        if not duration_ms:
            duration_ms = 3000
        elif not duration_already_scaled and str(expression).lower().endswith('.mp4'):
            from app.robot.emotion_assets import get_emotion_style
            expression_speed = get_emotion_style(expression.replace('\\', '/').split('/')[-1])[
                'speedMultiplier'
            ]
            duration_ms = max(1, int(round(duration_ms / expression_speed)))

        motion_offset_ms = self._as_ms(sequence.get('motionOffsetMs'))
        if not motion_offset_ms:
            motion_offset_ms = self._as_ms(metadata.get('motionStartTime'))
        # 兼容替换表情：动作占用以真实命令结束点为准，不用 JSON 中可能包含
        # 静止尾段的 motionDurationMs 限制表情素材长度。
        motion_duration_ms = 0
        if motion:
            frames = get_scaled_motion_frames(motion)
            if frames:
                motion_duration_ms = max(
                    self._as_ms(frame.get('time')) + self._as_ms(frame.get('moveMs'))
                    for frame in frames
                    if isinstance(frame, dict)
                )
        if motion and not motion_duration_ms:
            speed = float(metadata.get('speedMultiplier') or 1.0)
            motion_duration_ms = int(round(
                self._as_ms(metadata.get('motionDurationMs')) / speed
            ))

        audio_offset_ms = self._as_ms(audio.get('offsetMs'))
        aux = source.get('aux') if isinstance(source.get('aux'), dict) else {}
        if any(bool(aux.get(key)) for key in (
            'question', 'praise', 'hint', 'socialGreetingIntro',
            'socialGreetingPlay', 'socialFarewellBye', 'socialFarewellReply',
        )) and audio_offset_ms >= duration_ms:
            raise ValueError('语音开始时间必须落在表情结束之前')

        session_id = source.get('sessionId') or source.get('session_id')
        motion_end_ms = motion_offset_ms + motion_duration_ms if motion else 0
        event_duration_ms = max(duration_ms, motion_end_ms)
        behavior_id = (
            source.get('behaviorId')
            or source.get('behavior_id')
            or source.get('interactionId')
            or f'behavior-{uuid.uuid4().hex[:12]}'
        )
        request_id = (
            source.get('requestId')
            or source.get('request_id')
            or str(behavior_id)
        )
        fast_feedback = bool(aux.get('praise'))
        return {
            'id': str(behavior_id),
            'protocolVersion': '1',
            'requestId': str(request_id),
            'motion': motion,
            'emotion': expression,
            'durationMs': event_duration_ms,
            'expressionDurationMs': duration_ms,
            'motionDurationMs': motion_duration_ms,
            'motionEndMs': motion_end_ms,
            'motionOffsetMs': motion_offset_ms,
            'audioOffsetMs': audio_offset_ms,
            'sessionId': str(session_id) if session_id else None,
            'dialogueReply': bool(source.get('dialogueReply')),
            'startLeadMs': (
                BEHAVIOR_FEEDBACK_START_LEAD_MS if fast_feedback else None
            ),
        }

    def _run_sequence(self, plan: Dict[str, Any]) -> None:
        sequence_id = plan['id']
        start_at = float(plan.get('startAtMonotonic') or time.monotonic())
        start_epoch_ms = int(
            plan.get('startAtEpochMs') or round(time.time() * 1000)
        )
        expression_sent = bool(plan.get('expressionDispatched'))
        if plan.get('runtimeMotionPrepared') and not self._commit_runtime_motion(plan):
            logger.warning('行为 %s 的 Runtime commit 失败，降级为直接动作', sequence_id)
            plan['runtimeMotionPrepared'] = False
            plan['runtimeCommitFailed'] = True
            with self._idle_state_lock:
                waiter = self._behavior_audio_waiters.get(sequence_id)
                if waiter:
                    waiter['runtimeMotionPrepared'] = False
                    waiter['motionExpected'] = False
                    waiter['motionStatus'] = 'fallback_pending'
                    waiter['motionDone'].set()
        remaining_to_start = start_at - time.monotonic()
        if remaining_to_start > 0:
            time.sleep(remaining_to_start)
        if self._behavior_cancelled(sequence_id):
            return
        # Keep the idle pose active while all modalities are staging, then hand
        # over at the shared anchor instead of creating a visible dead interval.
        self._stop_idle_motion_if_needed()
        started = start_at
        logger.info(
            '开始行为序列 id=%s anchor=%s expression=%s/%sms event=%sms motion=%s@%sms end=%sms audio_offset=%sms',
            sequence_id, start_epoch_ms,
            plan['emotion'], plan['expressionDurationMs'], plan['durationMs'],
            plan['motion'], plan['motionOffsetMs'], plan['motionEndMs'], plan['audioOffsetMs'],
        )

        events = []
        if plan.get('motion'):
            events.append((plan['motionOffsetMs'], 'motion'))
        for offset_ms, kind in sorted(events, key=lambda item: item[0]):
            remaining = offset_ms / 1000.0 - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)
            if self._behavior_cancelled(sequence_id):
                return
            if kind == 'motion':
                motion_started = (
                    True
                    if plan.get('runtimeMotionPrepared')
                    else self._emit_motion_to_child_agent(plan['motion'], None)
                    if plan.get('motionViaChildRelay')
                    else self.play_motion(plan['motion'])
                )
                self._update_command_status(
                    sequence_id,
                    component='motion',
                    component_status='dispatched' if motion_started else 'failed',
                    component_detail=(
                        f'已通过 {self.get_control_mode()} 下发'
                        if motion_started else '动作不存在、目标离线或下发失败'
                    ),
                )
                if not motion_started:
                    logger.error('行为序列 %s 的动作未能启动: %s', sequence_id, plan['motion'])

        remaining = plan['durationMs'] / 1000.0 - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)
        if self._behavior_cancelled(sequence_id):
            return
        if expression_sent:
            current = self.get_command_status(sequence_id) or {}
            expression_state = (current.get('components') or {}).get('expression') or {}
            if expression_state.get('status') not in (
                'completed', 'failed', 'stopped', 'timeout', 'cancelled'
            ):
                self._update_command_status(
                    sequence_id,
                    component='expression',
                    component_status='unverified',
                    component_detail='媒体计划时长已结束，但未收到表情显示端完成回执',
                )
        if plan.get('motion'):
            current = self.get_command_status(sequence_id) or {}
            motion_state = (current.get('components') or {}).get('motion') or {}
            if motion_state.get('status') not in ('failed', 'completed'):
                verification = self.get_control_snapshot()['targets']['motionVerification']
                self._update_command_status(
                    sequence_id,
                    component='motion',
                    component_status=(
                        'unverified'
                        if plan.get('runtimeMotionPrepared') or verification == 'udp_unverified'
                        else 'completed'
                    ),
                    component_detail=(
                        '计划时长已结束；未及时收到 Runtime ended 回执'
                        if plan.get('runtimeMotionPrepared')
                        else '计划时长已结束；UDP 无真机完成回执'
                        if verification == 'udp_unverified'
                        else '目标已接受命令且计划时长结束'
                    ),
                )
        logger.info('行为序列完成 id=%s', sequence_id)

    def _stop_idle_motion_if_needed(self) -> None:
        """正式行为开始前停止由服务自身启动的待机动作。"""
        should_stop = False
        idle_request_id = None
        with self._idle_state_lock:
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
            if self._idle_motion_active:
                self._idle_motion_active = False
                should_stop = True
                idle_request_id = getattr(self, '_idle_motion_request_id', None)
                self._idle_motion_request_id = None
        if should_stop:
            if self.get_control_mode() == 'robot_runtime':
                # A formal /osc/play replaces the current idle playback
                # atomically. Sending a separate stop through another network
                # path can arrive late and interrupt the formal motion.
                return
            else:
                self.stop_playback()

    def _schedule_idle_pose_if_quiet(self) -> None:
        idle_pose = self._mapping_resolver.get_idle_pose()
        if not idle_pose or not self._sequence_queue.empty():
            return

        with self._idle_state_lock:
            generation = self._idle_generation
            if self._idle_timer:
                self._idle_timer.cancel()

            def return_to_idle() -> None:
                idle_request_id = f'idle-{uuid.uuid4().hex[:12]}'
                with self._idle_state_lock:
                    self._idle_timer = None
                    if generation != self._idle_generation or not self._sequence_queue.empty():
                        return
                    # 先登记“正在启动”，但不要在锁内执行可能耗时的 Runtime HTTP。
                    self._idle_motion_active = True
                    self._idle_motion_request_id = idle_request_id
                started = bool(
                    self._emit_motion_to_child_agent(
                        idle_pose,
                        None,
                        request_id=idle_request_id,
                    )
                    if self.get_control_mode() == 'robot_runtime' and self._child_agent_online()
                    else self._play_motion_via_runtime(
                        idle_pose,
                        None,
                        request_id=idle_request_id,
                    )
                    if self.get_control_mode() == 'robot_runtime'
                    else self.play_motion(idle_pose)
                )
                with self._idle_state_lock:
                    became_stale = (
                        generation != self._idle_generation
                        or not self._sequence_queue.empty()
                    )
                    self._idle_motion_active = started and not became_stale
                    if not self._idle_motion_active:
                        self._idle_motion_request_id = None
                if started and became_stale:
                    if self.get_control_mode() == 'robot_runtime':
                        self._runtime_osc_post('/osc/stop', {
                            'requestId': idle_request_id,
                            'onlyIfCurrent': True,
                        })
                    else:
                        self.stop_playback()

            self._idle_timer = threading.Timer(
                max(0.0, IDLE_POSE_DELAY),
                return_to_idle,
            )
            self._idle_timer.daemon = True
            self._idle_timer.name = 'RobotReturnToIdle'
            self._idle_timer.start()

    def _enqueue_sequence(self, plan: Dict[str, Any]) -> bool:
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            self._clear_stale_reservation_locked()
            behavior_id = str(
                plan.get('id') or f'behavior-{uuid.uuid4().hex[:12]}'
            )
            plan['id'] = behavior_id
            waiter = self._behavior_audio_waiters.get(behavior_id)
            owns_reservation = bool(
                self._behavior_busy
                and self._busy_event_id == behavior_id
                and waiter
                and not waiter.get('sequenceEnqueued')
            )
            if self._behavior_busy and not owns_reservation:
                logger.info(
                    '行为播放中，忽略新事件 id=%s active=%s remaining=%sms',
                    behavior_id,
                    self._busy_event_id,
                    self.get_behavior_busy_state()['remainingMs'],
                )
                return False
            if waiter is None:
                if not self._process_behavior_lock.acquire(blocking=False):
                    logger.info('cross-process behavior slot is busy id=%s', behavior_id)
                    return False
                waiter = self._new_behavior_waiter(
                    behavior_id,
                    request_id=plan.get('requestId'),
                    session_id=plan.get('sessionId'),
                    protocol_version=str(plan.get('protocolVersion') or '1'),
                )
                # Preview/direct robot events do not have a paired audio
                # dispatcher. Mark the decision immediately to avoid a 3s tail.
                waiter['expectedAudioCount'] = 0
                waiter['dispatchReady'].set()
                waiter['audioDone'].set()
                self._behavior_audio_waiters[behavior_id] = waiter
            now_monotonic = time.monotonic()
            now_epoch_ms = time.time() * 1000.0
            requested_lead_ms = self._as_ms(plan.get('startLeadMs'))
            lead_ms = max(
                BEHAVIOR_COMMIT_MIN_LEAD_MS,
                requested_lead_ms or BEHAVIOR_START_LEAD_MS,
            )
            start_at = float(
                plan.get('startAtMonotonic')
                or (now_monotonic + lead_ms / 1000.0)
            )
            plan['startAtMonotonic'] = start_at
            plan['startAtEpochMs'] = int(round(
                now_epoch_ms + max(0.0, start_at - now_monotonic) * 1000.0
            ))
            plan['scheduledDelayMs'] = max(
                0,
                int(round((start_at - now_monotonic) * 1000.0)),
            )
            try:
                self._sequence_queue.put_nowait(plan)
            except queue.Full:
                logger.info('行为槽位已占用，忽略 id=%s', behavior_id)
                if owns_reservation:
                    self._behavior_audio_waiters.pop(behavior_id, None)
                    self._behavior_busy = False
                    self._busy_event_id = None
                    self._active_sequence_deadline = 0.0
                    self._process_behavior_lock.release()
                return False
            waiter['sequenceEnqueued'] = True
            waiter['sessionId'] = (
                str(plan.get('sessionId')) if plan.get('sessionId')
                else waiter.get('sessionId')
            )
            waiter['requestId'] = plan.get('requestId') or waiter.get('requestId')
            waiter['protocolVersion'] = str(plan.get('protocolVersion') or '1')
            waiter['startAtServerMs'] = int(plan.get('startAtEpochMs') or 0)
            waiter['durationMs'] = self._as_ms(plan.get('durationMs'))
            waiter['expressionDurationMs'] = self._as_ms(
                plan.get('expressionDurationMs') or plan.get('durationMs')
            )
            waiter['strictEnvelope'] = bool(
                waiter.get('requestId') and waiter.get('sessionId')
            )
            waiter['expressionExpected'] = bool(plan.get('emotion'))
            waiter['expressionStatus'] = (
                'pending' if waiter['expressionExpected'] else 'skipped'
            )
            if not waiter['expressionExpected']:
                waiter['expressionDone'].set()
            visual_deadline = (
                start_at + self._as_ms(plan.get('durationMs')) / 1000.0
            )
            waiter['visualDeadline'] = visual_deadline
            self._behavior_busy = True
            self._busy_event_id = behavior_id
            self._active_sequence_deadline = max(
                visual_deadline,
                float(waiter.get('audioDeadline') or 0),
            )
            self._idle_generation += 1
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
            self._record_command(plan)
            return True

    def get_behavior_busy_state(self) -> Dict[str, Any]:
        """返回行为互斥状态，供 play_resource 在产生课程副作用前快速拒绝。"""
        with self._idle_state_lock:
            self._ensure_behavior_coordination_state()
            self._clear_stale_reservation_locked()
            remaining_ms = max(
                0,
                int((self._active_sequence_deadline - time.monotonic()) * 1000),
            )
            return {
                'busy': bool(self._behavior_busy),
                'eventId': self._busy_event_id,
                'remainingMs': remaining_ms,
            }

    def resolve_audio_offset_ms(self, data: Dict[str, Any]) -> int:
        """从与动作相同的映射快照读取语音偏移；不参与课程语音选取。"""
        v2_plan = self.resolve_interaction_plan(data)
        if v2_plan is not None and v2_plan.source.startswith("v2."):
            sequence = v2_plan.metadata.get("sequence") if isinstance(v2_plan.metadata, dict) else {}
            audio = sequence.get("audio") if isinstance(sequence, dict) else {}
            return self._as_ms((audio or {}).get("offsetMs"))
        aux_type = self._mapping_resolver.parse_aux_type(data.get('aux'))
        mapping = self._mapping_resolver.find_mapping(
            data.get('studentId'),
            data.get('courseId'),
            data.get('itemId'),
            aux_type,
        )
        sequence = mapping.get('sequence') if isinstance(mapping, dict) else {}
        audio = sequence.get('audio') if isinstance(sequence, dict) else {}
        return self._as_ms((audio or {}).get('offsetMs'))

    def _resolve_interaction_plan(self, data: Dict[str, Any], resolver=None):
        """只在有已发布 V2 profile 时返回 V2 结果；无 profile 完整走旧解析。"""
        try:
            from app.contracts.models import InteractionContext

            capabilities = dict(data.get('capabilities') or {})
            if data.get('sessionId') or data.get('session_id'):
                capabilities.setdefault('sessionId', data.get('sessionId') or data.get('session_id'))
            if data.get('trainingSessionId') or data.get('training_session_id'):
                capabilities.setdefault('trainingSessionId', data.get('trainingSessionId') or data.get('training_session_id'))
            context = InteractionContext(
                course_id=str(data.get('courseId') or '') or None,
                course_type=data.get('courseType') or data.get('course_type'),
                item_id=str(data.get('itemId') or '') or None,
                question_id=str(data.get('questionId') or '') or None,
                event_key=data.get('eventKey') or data.get('event_key'),
                scene_key=data.get('sceneKey') or data.get('scene_key'),
                line_id=data.get('lineId') or data.get('line_id'),
                student_id=str(data.get('studentId') or '') or None,
                profile_version=self._session_profile_version(data),
                behavior_id=data.get('behaviorId') or data.get('behavior_id'),
                request_id=data.get('requestId') or data.get('request_id'),
                capabilities=capabilities,
            )
            resolver = resolver or self._build_interaction_resolver()
            plan, shadow_report = resolver.resolve_with_shadow(
                context,
                aux=data.get('aux') or {},
            )
            if shadow_report and isinstance(plan.metadata, dict):
                plan = replace(
                    plan,
                    metadata={**plan.metadata, 'shadowReport': shadow_report},
                )
            return plan
        except Exception as exc:
            logger.warning('InteractionProfileV2 解析失败，回退 legacy: %s', exc)
            return None

    def _build_interaction_resolver(self, *, store=None, catalog=None):
        """Build the one resolver seam shared by runtime and preview paths."""
        from app.computation.interaction import (
            InteractionResolver,
            LegacyInteractionAdapter,
            get_event_catalog,
        )
        from app.robot.config import ROBOT_DATA_DIR
        from app.storage.repositories.interaction_profile_store import (
            JsonInteractionProfileStore,
        )

        return InteractionResolver(
            store=store or JsonInteractionProfileStore(
                os.path.join(ROBOT_DATA_DIR, 'interaction_profiles.json')
            ),
            legacy=LegacyInteractionAdapter(self._mapping_resolver),
            catalog=catalog or get_event_catalog(),
        )

    @staticmethod
    def _session_profile_version(data: Dict[str, Any]) -> Optional[str]:
        """Read a server-frozen profile version before client compatibility input."""
        session_id = data.get('sessionId') or data.get('session_id')
        if session_id:
            try:
                from app.session import get_session_manager

                session = get_session_manager().get_session(str(session_id))
                metadata = getattr(session, 'metadata', {}) if session else {}
                if isinstance(metadata, dict) and 'activeProfileVersion' in metadata:
                    value = metadata.get('activeProfileVersion')
                    return str(value).strip() if value else None
            except Exception as exc:
                logger.warning('读取 session activeProfileVersion 失败: %s', exc)
        # Old sessions without the field still accept the historical client
        # field. Once the field exists, the frontend cannot override it.
        return data.get('profileVersion') or data.get('profile_version')

    def get_active_profile_version(
        self,
        *,
        course_id: Any,
        course_type: Optional[str],
        session_id: Optional[str] = None,
    ) -> Optional[str]:
        from app.contracts.models import InteractionContext

        context = InteractionContext(
            course_id=str(course_id) if course_id is not None else None,
            course_type=course_type,
            capabilities={'sessionId': str(session_id)} if session_id else {},
        )
        return self._build_interaction_resolver().active_profile_version(context)

    def resolve_interaction_plan(self, data: Dict[str, Any], *, store=None, catalog=None):
        """Public adapter used by the control preview and runtime trigger paths."""
        payload = dict(data or {})
        nested = payload.get('context')
        if isinstance(nested, dict):
            merged = dict(payload)
            merged.update(nested)
            merged['aux'] = payload.get('aux') or nested.get('aux') or {}
            payload = merged
        resolver = self._build_interaction_resolver(store=store, catalog=catalog) if store is not None or catalog is not None else None
        return self._resolve_interaction_plan(payload, resolver=resolver)

    def preview_behavior_sequence(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """控制端试播：使用传入的未保存绑定，仍走与正式触发相同的调度器。"""
        motions = data.get('motions') if isinstance(data.get('motions'), list) else []
        selected_motion = self._mapping_resolver.select_motion(motions)
        aux_type = str(data.get('auxType') or '')
        aux_keys = {
            'question': 'question', 'praise': 'praise', 'hint': 'hint',
            'social_greeting_intro': 'socialGreetingIntro',
            'social_greeting_play': 'socialGreetingPlay',
            'social_farewell_bye': 'socialFarewellBye',
            'social_farewell_reply': 'socialFarewellReply',
        }
        preview_data = dict(data)
        if aux_type in aux_keys:
            preview_data['aux'] = {aux_keys[aux_type]: True}
        if not preview_data.get('courseType') and preview_data.get('courseId'):
            try:
                from database.models import Course
                course = Course.query.get(int(preview_data['courseId']))
                if course:
                    preview_data['courseType'] = course.to_dict().get('type') or 'default'
            except Exception as exc:
                logger.warning('试播解析课程类型失败: %s', exc)
        preview_data.setdefault('courseType', 'default')
        control = self.get_control_snapshot()
        targets = control.get('targets') or {}
        preview_sequence = data.get('sequence') if isinstance(data.get('sequence'), dict) else {}
        expression = str(
            data.get('emotion')
            or preview_sequence.get('expressionMediaId')
            or self.get_default_emotion()
        ).strip()
        missing_targets = []
        warnings = []
        if selected_motion and not targets.get('motionReady'):
            missing_targets.append({
                'component': 'motion',
                'code': 'motion_target_offline',
                'detail': targets.get('motionDetail') or '动作执行目标离线',
            })
        if expression and not targets.get('robotDisplayOnline'):
            missing_targets.append({
                'component': 'expression',
                'code': 'robot_display_offline',
                'detail': '机器人表情页 /robot/emotion 未在线，无法确认表情会被接收',
            })
        if targets.get('motionVerification') == 'udp_unverified' and selected_motion:
            warnings.append('Server OSC 使用 UDP，无真机接收/完成回执')
        if missing_targets:
            return {
                'success': False,
                'error': 'control_target_not_ready',
                'message': '试播未执行：存在离线或不可确认的目标',
                'missingTargets': missing_targets,
                'control': control,
            }
        try:
            plan = self._build_sequence_plan(
                motion=selected_motion,
                emotion=str(data.get('emotion') or self.get_default_emotion()),
                sequence=data.get('sequence'),
                event_data=preview_data,
            )
        except ValueError as exc:
            return {'success': False, 'message': str(exc)}
        plan['source'] = 'server_control_preview'
        plan['warnings'] = warnings
        if not self._enqueue_sequence(plan):
            return {
                'success': False,
                'message': '当前行为尚未播放完成，本次触发已忽略',
                'busy': True,
                **self.get_behavior_busy_state(),
            }
        return {
            'success': True,
            'sequenceId': plan['id'],
            'motion': selected_motion,
            'emotion': plan['emotion'],
            'durationMs': plan['durationMs'],
            'scheduledDelayMs': plan.get('scheduledDelayMs', 0),
            'phase': 'queued',
            'statusUrl': f'/api/robot/sequence/status/{plan["id"]}',
            'actualPlan': {
                'motion': selected_motion,
                'emotion': plan['emotion'],
                'durationMs': plan['durationMs'],
                'expressionDurationMs': plan['expressionDurationMs'],
                'motionOffsetMs': plan['motionOffsetMs'],
                'audioOffsetMs': plan['audioOffsetMs'],
                'controlMode': self.get_control_mode(),
            },
            'warnings': warnings,
        }
    
    def trigger_course_event(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        触发课程事件（供 play_resource 调用）
        
        Args:
            data: {
                action: str,
                studentId: int,
                courseId: int,
                itemId: int | None,
                aux: {question: bool, praise: bool, hint: bool}
            }
            
        Returns:
            {success: bool, message: str, motion: str | None, auxType: str, emotion: str}
        """
        course_id = data.get('courseId')
        if not course_id:
            return {'success': False, 'message': 'courseId required', 'motion': None, 'auxType': None, 'emotion': None}
        
        student_id = data.get('studentId')
        item_id = data.get('itemId')
        aux = data.get('aux')
        
        # 解析动作类型
        aux_type = self._mapping_resolver.parse_aux_type(aux)
        course_type = str(data.get('courseType') or data.get('course_type') or '').strip().lower()
        social_role = None
        try:
            from database.models import Course, CourseItem

            course = Course.query.get(int(course_id))
            if course is not None:
                course_type = str(course.to_dict().get('type') or course_type).strip().lower()
            if item_id is not None:
                item = CourseItem.query.get(int(item_id))
                if item is not None and int(item.course_id) == int(course_id):
                    item_data = item.to_dict()
                    social_role = item_data.get('socialRole')
                    if not social_role:
                        config = item_data.get('config') if isinstance(item_data.get('config'), dict) else {}
                        social_role = config.get('socialRole')
                    if not social_role and item.name in ('打招呼', '再见'):
                        social_role = 'greeting' if item.name == '打招呼' else 'farewell'
        except Exception as exc:
            logger.warning('解析行为课程归属失败，使用事件载荷课型: %s', exc)

        from app.robot.behavior_events import is_aux_allowed
        if not is_aux_allowed(course_type, aux_type, social_role=social_role):
            logger.warning(
                '拒绝课程不支持的机器人事件: course=%s type=%s item=%s role=%s aux=%s',
                course_id, course_type, item_id, social_role, aux_type,
            )
            return {
                'success': False,
                'message': '该机器人行为不属于当前课程/课点',
                'error': 'behavior_event_not_allowed',
                'motion': None,
                'auxType': aux_type,
                'emotion': None,
                'courseType': course_type,
            }
        data['courseType'] = course_type
        logger.info(f"📥 课程事件: course={course_id}, type={course_type}, item={item_id}, auxType={aux_type}")
        
        # 查找匹配的动作、表情与偏移配置
        mapping = self._mapping_resolver.find_mapping(student_id, course_id, item_id, aux_type)
        motions = mapping.get('motions', [])
        emotion = mapping.get('emotion') or self.get_default_emotion()
        # Interactive iframe feedback can arrive without a course-specific
        # mapping. Always fall back to the configured global behavior profile
        # so praise/question never silently becomes audio-only.
        if not motions:
            fallback = self._mapping_resolver.find_mapping(None, -1, None, aux_type)
            motions = fallback.get('motions', []) or motions
            emotion = emotion or fallback.get('emotion')
        sequence_config = mapping.get('sequence') if isinstance(mapping.get('sequence'), dict) else {}
        # 课程机器人表现只有 course_map 的全局→课程→课点三级配置是执行真相。
        # InteractionProfileV2 仍可用于独立预演/迁移，但不再暗中覆盖配置中心。
        v2_plan = None
        v2_speech_configured = False
        speech_payload = {}
        if v2_speech_configured:
            speech_payload = {
                'speechConfigured': True,
                'speechCommands': [asdict(command) for command in v2_plan.speech],
            }
        if v2_plan is not None and isinstance(v2_plan.metadata, dict) and v2_plan.metadata.get('shadowReport'):
            speech_payload['shadowReport'] = v2_plan.metadata.get('shadowReport')
            logger.info('使用已发布 InteractionProfileV2: course=%s event=%s source=%s trace=%s', course_id, v2_plan.context.event_key, v2_plan.source, v2_plan.resolution_trace)
        # 普通课点首次打开会落到 silent。默认配置只是“无动作 + idle 表情”，
        # 这不是一个真正行为，不能占用 3 秒序列队列，否则紧随其后的打招呼
        # 会出现“语音先播、动作很久后才播”。显式配置了 silent 动作/表情媒体时仍执行。
        if aux_type == 'silent':
            behavior_id = (
                data.get('behaviorId')
                or data.get('behavior_id')
                or data.get('interactionId')
                or f'behavior-{uuid.uuid4().hex[:12]}'
            )
            return {
                'success': True,
                'message': 'No-op silent behavior skipped',
                'motion': None,
                'auxType': aux_type,
                'emotion': emotion,
                'skipped': True,
                'behaviorId': str(behavior_id),
                'sequenceId': str(behavior_id),
                'remainingMs': 0,
                **speech_payload,
            }
        # 无动作时仍允许纯表情 / 语音行为。
        selected_motion = self._mapping_resolver.select_motion(motions)
        try:
            plan = self._build_sequence_plan(
                motion=selected_motion,
                emotion=emotion,
                sequence=sequence_config,
                event_data=data,
            )
        except ValueError as exc:
            return {'success': False, 'message': str(exc), 'motion': selected_motion, 'auxType': aux_type, 'emotion': emotion}

        if self._enqueue_sequence(plan):
            return {
                'success': True,
                'message': f'Queued behavior sequence "{plan["emotion"]}"',
                'motion': selected_motion,
                'auxType': aux_type,
                'emotion': plan['emotion'],
                'sequenceId': plan['id'],
                'behaviorId': plan['id'],
                'durationMs': plan['durationMs'],
                'scheduledDelayMs': plan.get('scheduledDelayMs', 0),
                'startAtEpochMs': plan.get('startAtEpochMs'),
                'remainingMs': self.get_behavior_busy_state().get('remainingMs', 0),
                **speech_payload,
            }
        return {
            'success': False,
            'message': '当前行为尚未播放完成，本次触发已忽略',
            'motion': selected_motion,
            'auxType': aux_type,
            'emotion': plan['emotion'],
            **self.get_behavior_busy_state(),
            **speech_payload,
        }
    
    # ========== 映射配置 ==========
    
    def get_full_mapping(self) -> Dict[str, Any]:
        """获取完整映射配置"""
        return self._mapping_resolver.get_full_mapping()
    
    def get_idle_pose(self) -> Optional[str]:
        """获取静态姿势"""
        return self._mapping_resolver.get_idle_pose()
    
    def set_idle_pose(self, motion_name: str) -> None:
        """设置静态姿势"""
        self._mapping_resolver.set_idle_pose(motion_name)
    
    def update_default_motions(self, aux_type: str, motions: List[str], emotion: Optional[str] = None, sequence: Optional[Dict[str, Any]] = None, animation: Optional[str] = None) -> None:
        """更新通用动作"""
        self._mapping_resolver.update_default_motions(aux_type, motions, emotion, sequence, animation)
    
    def delete_default_motions(self, aux_type: str) -> None:
        """删除通用动作"""
        self._mapping_resolver.delete_default_motions(aux_type)
    
    def update_course_motions(self, course_id: int, aux_type: str, motions: List[str], emotion: Optional[str] = None, sequence: Optional[Dict[str, Any]] = None, animation: Optional[str] = None) -> None:
        """更新课程级动作"""
        self._mapping_resolver.update_course_motions(course_id, aux_type, motions, emotion, sequence, animation)
    
    def delete_course_motions(self, course_id: int, aux_type: str) -> None:
        """删除课程级动作"""
        self._mapping_resolver.delete_course_motions(course_id, aux_type)

    def update_course_item_motions(
        self, course_id: int, item_id: int, aux_type: str, motions: List[str],
        emotion: Optional[str] = None, sequence: Optional[Dict[str, Any]] = None,
        animation: Optional[str] = None,
    ) -> None:
        self._mapping_resolver.update_course_item_motions(
            course_id, item_id, aux_type, motions, emotion, sequence, animation,
        )

    def delete_course_item_motions(self, course_id: int, item_id: int, aux_type: str) -> None:
        self._mapping_resolver.delete_course_item_motions(course_id, item_id, aux_type)
    
    def update_student_course_motions(
        self, student_id: int, course_id: int, aux_type: str, motions: List[str], emotion: Optional[str] = None, sequence: Optional[Dict[str, Any]] = None, animation: Optional[str] = None
    ) -> None:
        """更新学生-课程级动作"""
        self._mapping_resolver.update_student_course_motions(student_id, course_id, aux_type, motions, emotion, sequence, animation)
    
    def delete_student_course_motions(self, student_id: int, course_id: int, aux_type: str) -> None:
        """删除学生-课程级动作"""
        self._mapping_resolver.delete_student_course_motions(student_id, course_id, aux_type)
    
    def update_item_motions(
        self, student_id: int, course_id: int, item_id: int, aux_type: str, motions: List[str], emotion: Optional[str] = None, sequence: Optional[Dict[str, Any]] = None, animation: Optional[str] = None
    ) -> None:
        """更新项目级动作"""
        self._mapping_resolver.update_item_motions(
            student_id, course_id, item_id, aux_type,
            motions=motions, emotion=emotion, sequence=sequence, animation=animation,
        )

    def resolve_encouragement_animation(self, data: Dict[str, Any]) -> Optional[str]:
        """Resolve the praise binding animation, with library fallback only when unset."""
        from app.robot.animation_assets import resolve_animation

        aux_type = self._mapping_resolver.parse_aux_type(data.get('aux'))
        if aux_type != 'praise':
            return None
        mapping = self._mapping_resolver.find_mapping(
            data.get('studentId'),
            data.get('courseId'),
            data.get('itemId'),
            aux_type,
        )
        return resolve_animation(mapping.get('animation'))

    def start_dialogue_reply_behavior(
        self,
        *,
        emotion: str,
        behavior_id: str,
        request_id: str,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Attach a configured expression to an already reserved dialogue turn."""
        try:
            plan = self._build_sequence_plan(
                motion=None,
                emotion=emotion,
                sequence={},
                event_data={
                    'behaviorId': behavior_id,
                    'requestId': request_id,
                    'sessionId': session_id,
                    'dialogueReply': True,
                },
            )
        except (ValueError, FileNotFoundError) as exc:
            logger.warning('构建大模型回复表情行为失败: %s', exc)
            return None
        if not self._enqueue_sequence(plan):
            return None
        return {
            'behaviorId': plan['id'],
            'emotion': plan['emotion'],
            'durationMs': plan['durationMs'],
            'scheduledDelayMs': plan.get('scheduledDelayMs', 0),
            'startAtEpochMs': plan.get('startAtEpochMs'),
        }

    def get_animations_payload(self) -> Dict[str, Any]:
        from app.robot.animation_assets import get_animations_payload
        return get_animations_payload()

    def upload_animation(self, filename: str, file_bytes: bytes) -> Dict[str, Any]:
        from app.robot.animation_assets import save_uploaded_animation
        return save_uploaded_animation(filename, file_bytes, return_details=True)

    def rename_animation(self, old_name: str, new_name: str) -> Dict[str, Any]:
        from app.robot.animation_assets import rename_animation_file
        return rename_animation_file(old_name, new_name)

    def delete_animation(self, name: str, force: bool = False) -> None:
        from app.robot.animation_assets import delete_animation_file
        delete_animation_file(name, force=force)
    
    def delete_item_motions(
        self, student_id: int, course_id: int, item_id: int, aux_type: str
    ) -> None:
        """删除项目级动作"""
        self._mapping_resolver.delete_item_motions(student_id, course_id, item_id, aux_type)
    
    # ========== 基础数据 ==========
    
    def get_students(self) -> List[Dict[str, Any]]:
        """获取学生列表"""
        try:
            with open(STUDENTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取学生列表失败: {e}")
            return []
    
    def get_courses(self) -> List[Dict[str, Any]]:
        """获取课程列表"""
        try:
            with open(COURSES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取课程列表失败: {e}")
            return []
    
    # ========== 表情相关 ==========
    
    def get_available_emotions(self) -> List[str]:
        """获取所有可用表情列表"""
        from app.robot.emotion_assets import list_emotion_files
        return list_emotion_files()

    def get_emotions_payload(self) -> Dict[str, Any]:
        from app.robot.emotion_assets import get_emotions_payload
        return get_emotions_payload()

    def get_dialogue_reply_expressions(self) -> Dict[str, Any]:
        from app.robot.emotion_assets import get_dialogue_reply_expressions
        return get_dialogue_reply_expressions()

    def set_dialogue_reply_expressions(self, value: Dict[str, Any]) -> Dict[str, Any]:
        from app.robot.emotion_assets import set_dialogue_reply_expressions
        return set_dialogue_reply_expressions(value)

    def select_dialogue_reply_emotion(self, text: str) -> Optional[Dict[str, Any]]:
        from app.robot.emotion_assets import select_dialogue_reply_emotion
        return select_dialogue_reply_emotion(text)

    def get_emotion_style(self, name: str) -> Dict[str, Any]:
        from app.robot.emotion_assets import get_emotion_style
        return get_emotion_style(name)

    def set_emotion_style(self, name: str, style: Dict[str, Any]) -> Dict[str, Any]:
        from app.robot.emotion_assets import set_emotion_style
        return set_emotion_style(name, style)

    def get_global_emotion_filter(self) -> Dict[str, Any]:
        from app.robot.emotion_assets import get_global_filter
        return get_global_filter()

    def set_global_emotion_filter(self, value: Dict[str, Any]) -> Dict[str, Any]:
        from app.robot.emotion_assets import set_global_filter
        return set_global_filter(value)

    def get_default_emotion(self) -> str:
        from app.robot.emotion_assets import get_default_emotion
        return get_default_emotion()

    def set_default_emotion(self, name: str) -> str:
        from app.robot.emotion_assets import set_default_emotion
        return set_default_emotion(name)

    def get_idle_emotions(self) -> List[str]:
        from app.robot.emotion_assets import get_idle_emotions
        return get_idle_emotions()

    def set_idle_emotions(self, names: List[str]) -> List[str]:
        from app.robot.emotion_assets import set_idle_emotions
        result = set_idle_emotions(names)
        if _socketio is not None:
            _socketio.emit('robot_idle_pool_changed', {
                'emotions': result,
                'default': result[0],
            })
        return result

    def upload_emotion(self, filename: str, file_bytes: bytes) -> Dict[str, Any]:
        from app.robot.emotion_assets import save_uploaded_emotion
        return save_uploaded_emotion(filename, file_bytes, return_details=True)

    def delete_emotion(self, name: str, force: bool = False) -> None:
        from app.robot.emotion_assets import delete_emotion_file
        delete_emotion_file(name, force=force)
    
    def trigger_emotion(self, emotion: str, **payload: Any) -> bool:
        """
        通过WebSocket触发表情切换
        
        Args:
            emotion: 表情文件名（如 "003_Happy.gif"）
            
        Returns:
            是否成功发送
        """
        global _socketio
        
        if _socketio is None:
            logger.warning("SocketIO未绑定，无法发送表情事件")
            return False
        
        try:
            event = {'emotionName': emotion}
            event['style'] = self.get_emotion_style(emotion)
            event['globalFilter'] = self.get_global_emotion_filter()
            event.update(payload)
            _socketio.emit('robot_emotion_change', event)
            logger.info(f"🎭 表情切换: {emotion}")
            return True
        except Exception as e:
            logger.error(f"发送表情事件失败: {e}")
            return False

    # ========== robot_runtime 模式辅助 ==========

    def _runtime_headers(self) -> Dict[str, str]:
        headers = {'Content-Type': 'application/json'}
        if ROBOT_RUNTIME_KEY:
            headers['X-Robot-Runtime-Key'] = ROBOT_RUNTIME_KEY
            headers['X-Child-Media-Agent-Key'] = ROBOT_RUNTIME_KEY
        return headers

    def _runtime_base_url(self) -> Optional[str]:
        primary = get_primary_runtime()
        if not primary:
            return None
        return (primary.get('advertisedUrl') or '').rstrip('/') or None

    def _runtime_osc_post(self, path: str, payload: Dict[str, Any]) -> bool:
        body = self._runtime_json_post(path, payload)
        return bool(body and body.get('ok', True))

    def _runtime_json_post(
        self,
        path: str,
        payload: Dict[str, Any],
        *,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        if _requests is None:
            logger.error("requests 未安装，无法直连 Robot Runtime")
            return None
        base = str(base_url or self._runtime_base_url() or '').rstrip('/')
        if not base:
            logger.warning("无在线 Robot Runtime 注册，无法发送 %s", path)
            return None
        url = f"{base}{path}"
        try:
            resp = _requests.post(
                url,
                json=payload,
                headers=self._runtime_headers(),
                timeout=(
                    max(0.1, float(timeout_seconds))
                    if timeout_seconds is not None
                    else ROBOT_RUNTIME_HTTP_TIMEOUT
                ),
            )
            if resp.status_code != 200:
                logger.warning(
                    "Runtime OSC 失败: %s status=%s body=%s",
                    url, resp.status_code, resp.text[:200],
                )
                return None
            body = resp.json() if resp.content else {}
            return body if isinstance(body, dict) else None
        except Exception as e:
            logger.error("Runtime OSC 请求异常 %s: %s", url, e)
            return None

    def _runtime_json_post_pinned(
        self,
        path: str,
        payload: Dict[str, Any],
        base_url: Optional[str],
        *,
        timeout_seconds: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Post to one selected Runtime while tolerating legacy test adapters."""
        try:
            return self._runtime_json_post(
                path,
                payload,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            )
        except TypeError as exc:
            # A few integrations replace this private method with the historical
            # two-argument callable. Keep those adapters usable without allowing
            # real network errors to silently switch Runtime targets.
            if 'base_url' not in str(exc) and 'timeout_seconds' not in str(exc):
                raise
            return self._runtime_json_post(path, payload)

    @staticmethod
    def _motion_envelope(plan: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'protocolVersion': str(plan.get('protocolVersion') or '1'),
            'sessionId': str(plan.get('sessionId') or ''),
            'requestId': str(plan.get('requestId') or ''),
            'behaviorId': str(plan.get('id') or ''),
            'startAtServerMs': int(plan.get('motionStartAtServerMs') or 0),
            'modality': 'motion',
        }

    def _prepare_runtime_motion(self, plan: Dict[str, Any]) -> bool:
        primary = get_primary_runtime() or {}
        if 'behavior-sync-v1' not in set(primary.get('capabilities') or []):
            logger.error('Runtime 缺少 behavior-sync-v1，拒绝使用旧估时动作路径')
            return False
        frames = get_scaled_motion_frames(str(plan.get('motion') or ''))
        if not frames:
            return False
        runtime_base_url = str(primary.get('advertisedUrl') or '').rstrip('/')
        if not runtime_base_url:
            logger.error('Runtime 主实例缺少 advertisedUrl')
            return False
        plan['runtimeBaseUrl'] = runtime_base_url
        plan['motionStartAtServerMs'] = int(plan.get('startAtEpochMs') or 0) + self._as_ms(
            plan.get('motionOffsetMs')
        )
        envelope = self._motion_envelope(plan)
        if not all(envelope.get(key) for key in ('sessionId', 'requestId', 'behaviorId', 'startAtServerMs')):
            logger.error('Runtime 动作信封缺少三 ID 或锚点: %s', envelope)
            return False
        sent_at = time.time() * 1000.0
        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(str(plan.get('id') or ''))
            if waiter:
                waiter['runtimePrepareAttempted'] = True
                waiter['runtimeMotionEnvelope'] = dict(envelope)
                waiter['runtimeBaseUrl'] = runtime_base_url
        body = self._runtime_json_post_pinned('/behavior/prepare', {
            **envelope,
            'motionName': plan.get('motion'),
            'frames': frames,
            'neutralPose': get_neutral_pose(),
        }, runtime_base_url, timeout_seconds=min(0.6, ROBOT_RUNTIME_HTTP_TIMEOUT))
        received_at = time.time() * 1000.0
        if not body or not body.get('ready'):
            return False
        remaining_lead_ms = int(plan.get('startAtEpochMs') or 0) - int(received_at)
        if remaining_lead_ms < BEHAVIOR_COMMIT_MIN_LEAD_MS:
            logger.error(
                'Runtime prepare 返回过晚，拒绝冒险启动 behaviorId=%s remaining=%sms required=%sms',
                plan.get('id'), remaining_lead_ms, BEHAVIOR_COMMIT_MIN_LEAD_MS,
            )
            return False
        try:
            runtime_epoch = float(body.get('runtimeEpochMs'))
        except (TypeError, ValueError):
            return False
        plan['runtimeClockOffsetMs'] = runtime_epoch - ((sent_at + received_at) / 2.0)
        plan['runtimeMotionPrepared'] = True
        with self._idle_state_lock:
            waiter = self._behavior_audio_waiters.get(str(plan.get('id') or ''))
            if waiter:
                waiter['runtimeMotionPrepared'] = True
                waiter['motionExpected'] = True
                waiter['motionStatus'] = 'prepared'
                waiter['runtimeClockOffsetMs'] = plan['runtimeClockOffsetMs']
        self._update_command_status(
            str(plan.get('id') or ''),
            component='motion',
            component_required=True,
            component_status='prepared',
            component_detail=f"Runtime 已缓存动作；clockOffset={plan['runtimeClockOffsetMs']:.1f}ms",
        )
        return True

    def _commit_runtime_motion(self, plan: Dict[str, Any]) -> bool:
        envelope = self._motion_envelope(plan)
        start_at_runtime_ms = int(round(
            float(envelope['startAtServerMs'])
            + float(plan.get('runtimeClockOffsetMs') or 0.0)
        ))
        body = self._runtime_json_post_pinned('/behavior/commit', {
            **envelope,
            'startAtRuntimeMs': start_at_runtime_ms,
        }, plan.get('runtimeBaseUrl'), timeout_seconds=min(0.6, ROBOT_RUNTIME_HTTP_TIMEOUT))
        committed = bool(body and body.get('committed'))
        self._update_command_status(
            str(plan.get('id') or ''),
            component='motion',
            component_required=True,
            component_status='committed' if committed else 'failed',
            component_detail=(
                f'Runtime 本地等待锚点 {start_at_runtime_ms}'
                if committed else 'Runtime commit 失败'
            ),
        )
        return committed

    def _play_motion_via_runtime(
        self,
        motion_name: str,
        on_complete: Optional[callable],
        *,
        request_id: Optional[str] = None,
    ) -> bool:
        frames = get_scaled_motion_frames(motion_name)
        if not frames:
            logger.warning("动作 '%s' 不存在或为空（robot_runtime）", motion_name)
            return False

        body = self._runtime_json_post('/osc/play', {
            'requestId': request_id or f"legacy-preview-{motion_name}-{int(time.time() * 1000)}",
            'motionName': motion_name,
            'frames': frames,
            'neutralPose': get_neutral_pose(),
        }, timeout_seconds=min(0.6, ROBOT_RUNTIME_HTTP_TIMEOUT))
        ok = bool(body and body.get('ok', True))
        if not ok:
            return False

        if on_complete:
            duration_ms = (
                int(frames[-1].get('time', 0)) + int(frames[-1].get('moveMs', 0))
                if frames else 0
            )

            def _deferred_complete():
                time.sleep(max(0, duration_ms) / 1000.0)
                try:
                    on_complete()
                except Exception as e:
                    logger.error("robot_runtime 模式回调执行失败: %s", e)

            threading.Thread(
                target=_deferred_complete,
                daemon=True,
                name=f"RobotRuntimeComplete-{motion_name}",
            ).start()
        return True

    # ========== child_agent 模式辅助 ==========

    @staticmethod
    def _child_agent_online() -> bool:
        try:
            from app.sockets.events import get_online_presence_snapshot
            presence = get_online_presence_snapshot()
            return int(presence.get('childAgentOnline') or 0) > 0
        except Exception:
            return False

    def _emit_robot_command(self, command: Dict[str, Any]) -> bool:
        """向机器人端页面发送动作命令（child_agent 模式）。"""
        global _socketio
        if _socketio is None:
            logger.warning("SocketIO未绑定，无法发送机器人动作命令")
            return False
        if not self._child_agent_online():
            logger.warning("Child Agent 离线，拒绝伪报机器人命令下发成功")
            return False

        envelope = {
            'commandId': f"robot-{int(time.time() * 1000)}",
            'ts': int(time.time() * 1000),
        }
        envelope.update(command)

        try:
            if self._child_room:
                _socketio.emit('robot_motion_command', envelope, room=self._child_room)
            else:
                _socketio.emit('robot_motion_command', envelope)
            return True
        except Exception as e:
            logger.error("发送机器人动作命令失败: %s", e)
            return False

    def _emit_motion_to_child_agent(
        self,
        motion_name: str,
        on_complete: Optional[callable],
        *,
        request_id: Optional[str] = None,
    ) -> bool:
        """读取动作帧并发送给机器人端 Agent 执行。"""
        frames = get_scaled_motion_frames(motion_name)
        if not frames:
            logger.warning("动作 '%s' 不存在或为空（child_agent）", motion_name)
            return False

        ok = self._emit_robot_command({
            'commandId': request_id or f"motion-{uuid.uuid4().hex[:12]}",
            'type': 'play_motion',
            'source': 'robot_service',
            'payload': {
                'motionName': motion_name,
                'frames': frames,
            },
        })
        if not ok:
            return False

        if on_complete:
            duration_ms = (
                int(frames[-1].get('time', 0)) + int(frames[-1].get('moveMs', 0))
                if frames else 0
            )

            def _deferred_complete():
                time.sleep(max(0, duration_ms) / 1000.0)
                try:
                    on_complete()
                except Exception as e:
                    logger.error("child_agent 模式回调执行失败: %s", e)

            threading.Thread(
                target=_deferred_complete,
                daemon=True,
                name=f"RobotMotionComplete-{motion_name}",
            ).start()
        return True


# 全局服务实例获取函数
_robot_service: Optional[RobotService] = None


def get_robot_service() -> RobotService:
    """获取机械臂服务单例"""
    global _robot_service
    if _robot_service is None:
        _robot_service = RobotService()
    return _robot_service
