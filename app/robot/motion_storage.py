"""
动作存储层

统一管理 motions.json 的读写、格式兼容与基础校验。
"""
import json
import math
import os
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from app.robot.config import MOTIONS_FILE
from app.robot.neutral_pose import complete_pose, get_neutral_pose
from app.utils.logger import setup_logger

logger = setup_logger('motion_storage')

CURRENT_SCHEMA_VERSION = 2
VALID_AXES = {'pitch', 'yaw', 'armL', 'armR'}
MOTION_SPEED_MIN = 0.25
MOTION_SPEED_MAX = 4.0
DEFAULT_MOTION_SPEED = 1.0
_document_lock = threading.RLock()


def _utc_now_iso() -> str:
    """返回 UTC ISO 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _build_empty_document() -> Dict[str, Any]:
    """构建空动作文档（新格式）。"""
    return {
        'version': CURRENT_SCHEMA_VERSION,
        'updatedAt': _utc_now_iso(),
        'motions': {},
        # 导入 dollser-motion 时保留的时间轴语义。frames 仍保持旧播放引擎格式，
        # 因而不会影响已保存的动作。
        'motionMeta': {},
    }


def _is_old_style_document(doc: Any) -> bool:
    """
    识别旧格式：
    {
      "motion_name": [ ...frames... ]
    }
    """
    if not isinstance(doc, dict):
        return False
    return 'motions' not in doc


def _normalize_document(raw: Any) -> Dict[str, Any]:
    """将任意输入归一化为新格式文档。"""
    if not isinstance(raw, dict):
        logger.warning("motions.json 不是对象，已重置为空文档")
        return _build_empty_document()

    # 兼容单动作文件（v2 dollser-motion）直接作为 motions.json 的场景
    if _is_dollser_motion_document(raw):
        motion_name, frames = convert_dollser_motion_to_frames(raw)
        logger.info("检测到 dollser-motion 单动作文件，已自动转换为动作库格式")
        return {
            'version': CURRENT_SCHEMA_VERSION,
            'updatedAt': _utc_now_iso(),
            'motions': {motion_name: frames},
            'motionMeta': {motion_name: extract_dollser_motion_metadata(raw, frames)},
        }

    if _is_old_style_document(raw):
        # 旧格式自动升级为新格式
        logger.info("检测到旧版 motions.json 格式，已自动兼容加载")
        return {
            'version': CURRENT_SCHEMA_VERSION,
            'updatedAt': _utc_now_iso(),
            'motions': raw,
            'motionMeta': {},
        }

    motions = raw.get('motions')
    if not isinstance(motions, dict):
        logger.warning("motions 字段不是对象，已重置为空对象")
        motions = {}

    version = raw.get('version', CURRENT_SCHEMA_VERSION)
    if not isinstance(version, int):
        version = CURRENT_SCHEMA_VERSION

    updated_at = raw.get('updatedAt')
    if not isinstance(updated_at, str) or not updated_at:
        updated_at = _utc_now_iso()

    motion_meta = raw.get('motionMeta')
    if not isinstance(motion_meta, dict):
        motion_meta = {}

    return {
        'version': version,
        'updatedAt': updated_at,
        'motions': motions,
        'motionMeta': motion_meta,
    }


def _sanitize_frame(frame: Any) -> Dict[str, Any]:
    """对单帧数据做最小安全校验和补全。"""
    if not isinstance(frame, dict):
        return {
            'time': 0,
            'pose': get_neutral_pose(),
            'moveMs': 100,
        }

    time_ms = frame.get('time', 0)
    if not isinstance(time_ms, (int, float)):
        time_ms = 0
    time_ms = int(max(0, time_ms))

    pose = frame.get('pose', {})
    if not isinstance(pose, dict):
        pose = {}

    move_ms = frame.get('moveMs', 100)
    if not isinstance(move_ms, (int, float)):
        move_ms = 100

    return {
        'time': time_ms,
        'pose': complete_pose(pose),
        'moveMs': int(max(0, move_ms))
    }


def _is_dollser_motion_document(doc: Any) -> bool:
    """判断是否为 v2 dollser-motion 单动作文件。"""
    return (
        isinstance(doc, dict)
        and doc.get('format') == 'dollser-motion'
        and isinstance(doc.get('commands'), list)
    )


def convert_dollser_motion_to_frames(
    doc: Dict[str, Any],
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    将 v2 dollser-motion 文档转换为旧播放引擎可用的 frame 列表。

    转换策略：
    1. 以 initialPose 作为初始状态
    2. 按 time 聚合 commands，同一时刻更新多个轴
    3. 输出格式为 [{time, pose, moveMs}, ...]
    """
    name = doc.get('name') or 'imported_dollser_motion'
    initial_pose = doc.get('initialPose') if isinstance(doc.get('initialPose'), dict) else {}
    current_pose = complete_pose(initial_pose)

    commands = doc.get('commands', [])
    if not isinstance(commands, list):
        return name, [{'time': 0, 'pose': current_pose.copy(), 'moveMs': 100}]

    sorted_commands = sorted(
        [cmd for cmd in commands if isinstance(cmd, dict)],
        key=lambda cmd: int(max(0, cmd.get('time', 0))),
    )

    frames_by_time: Dict[int, Dict[str, Any]] = {
        0: {'time': 0, 'pose': current_pose.copy(), 'moveMs': 100}
    }

    for cmd in sorted_commands:
        axis = cmd.get('axis')
        if axis not in VALID_AXES:
            continue

        time_ms = int(max(0, cmd.get('time', 0)))
        angle = cmd.get('angle', current_pose[axis])
        move_ms = int(max(0, cmd.get('moveMs', 100)))

        if time_ms not in frames_by_time:
            frames_by_time[time_ms] = {
                'time': time_ms,
                'pose': current_pose.copy(),
                'moveMs': move_ms,
            }

        frames_by_time[time_ms]['pose'][axis] = angle
        frames_by_time[time_ms]['moveMs'] = max(
            int(frames_by_time[time_ms].get('moveMs', 100)),
            move_ms,
        )
        current_pose[axis] = angle

    frames = [frames_by_time[t] for t in sorted(frames_by_time.keys())]
    return name, sanitize_frames(frames)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def extract_dollser_motion_metadata(
    doc: Dict[str, Any], frames: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """保留 v2 动作文件中的相对时间信息，供行为序列编排使用。"""
    expression = doc.get('expression') if isinstance(doc.get('expression'), dict) else {}
    media_id = expression.get('mediaId') if isinstance(expression.get('mediaId'), str) else ''
    duration = _safe_int(doc.get('durationMs'), 0)
    motion_duration = _safe_int(doc.get('motionDurationMs'), 0)
    if not motion_duration and frames:
        last = frames[-1]
        motion_duration = _safe_int(last.get('time'), 0) + _safe_int(last.get('moveMs'), 0)
    return {
        'sourceFormat': doc.get('format') or 'dollser-motion',
        'sourceVersion': doc.get('version'),
        'durationMs': max(0, duration),
        'motionDurationMs': max(0, motion_duration),
        'motionStartTime': max(0, _safe_int(doc.get('motionStartTime'), 0)),
        'expression': {
            'mediaId': media_id,
            'offsetMs': max(0, _safe_int(expression.get('offsetMs'), 0)),
            'durationMs': max(0, _safe_int(expression.get('durationMs'), 0)),
            'loop': bool(expression.get('loop', False)),
        },
    }


def sanitize_frames(frames: Any) -> List[Dict[str, Any]]:
    """对动作帧列表进行清洗。"""
    if not isinstance(frames, list):
        return []
    return [_sanitize_frame(frame) for frame in frames]


def load_document() -> Dict[str, Any]:
    """读取并返回归一化后的动作文档。"""
    with _document_lock:
        try:
            # Windows editors/PowerShell may add a UTF-8 BOM. Accept it while
            # keeping all subsequent atomic writes as plain UTF-8.
            with open(MOTIONS_FILE, 'r', encoding='utf-8-sig') as f:
                raw = json.load(f)
            return _normalize_document(raw)
        except Exception as e:
            logger.error(f"读取动作文件失败: {e}")
            return _build_empty_document()


def save_document(doc: Dict[str, Any]) -> None:
    """保存完整动作文档（新格式）。"""
    normalized = _normalize_document(doc)
    normalized['version'] = CURRENT_SCHEMA_VERSION
    normalized['updatedAt'] = _utc_now_iso()

    target = os.path.abspath(MOTIONS_FILE)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with _document_lock:
        fd, temporary = tempfile.mkstemp(
            prefix=f'.{os.path.basename(target)}.', suffix='.tmp',
            dir=os.path.dirname(target),
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(normalized, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, target)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def load_motions() -> Dict[str, List[Dict[str, Any]]]:
    """读取动作映射表。"""
    return load_document().get('motions', {})


def save_motions(motions: Dict[str, List[Dict[str, Any]]]) -> None:
    """保存动作映射表。"""
    safe_motions: Dict[str, List[Dict[str, Any]]] = {}
    for name, frames in motions.items():
        if not isinstance(name, str) or not name:
            continue
        safe_motions[name] = sanitize_frames(frames)

    with _document_lock:
        existing_meta = load_document().get('motionMeta', {})
        kept_meta = {name: meta for name, meta in existing_meta.items() if name in safe_motions}
        save_document({
            'version': CURRENT_SCHEMA_VERSION,
            'motions': safe_motions,
            'motionMeta': kept_meta,
        })


def get_motion_metadata(motion_name: str) -> Dict[str, Any]:
    """返回动作导入时保留的编排元数据；旧动作返回空对象。"""
    meta = load_document().get('motionMeta', {}).get(motion_name)
    result = dict(meta) if isinstance(meta, dict) else {}
    result['speedMultiplier'] = _normalize_speed(
        result.get('speedMultiplier'), DEFAULT_MOTION_SPEED
    )
    return result


def _normalize_speed(value: Any, default: float = DEFAULT_MOTION_SPEED) -> float:
    """Return a finite in-range speed or the compatibility default."""
    if isinstance(value, bool):
        return default
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(speed) or not MOTION_SPEED_MIN <= speed <= MOTION_SPEED_MAX:
        return default
    return speed


def validate_motion_speed(value: Any) -> float:
    """Validate API input. A multiplier of 2.0 means twice as fast."""
    speed = _normalize_speed(value, float('nan'))
    if not math.isfinite(speed):
        raise ValueError(
            f'speedMultiplier must be between {MOTION_SPEED_MIN} and {MOTION_SPEED_MAX}'
        )
    return speed


def set_motion_speed(motion_name: str, value: Any) -> Dict[str, Any]:
    speed = validate_motion_speed(value)
    with _document_lock:
        doc = load_document()
        if motion_name not in doc.get('motions', {}):
            raise FileNotFoundError(f'Motion not found: {motion_name}')
        metas = doc.setdefault('motionMeta', {})
        current = metas.get(motion_name)
        meta = dict(current) if isinstance(current, dict) else {}
        meta['speedMultiplier'] = speed
        metas[motion_name] = meta
        save_document(doc)
    return get_motion_metadata(motion_name)


def get_scaled_motion_frames(motion_name: str) -> List[Dict[str, Any]]:
    """Load frames with all timing fields scaled for actual playback."""
    frames = load_motions().get(motion_name) or []
    speed = get_motion_metadata(motion_name)['speedMultiplier']
    scaled: List[Dict[str, Any]] = []
    for frame in frames:
        item = dict(frame)
        item['pose'] = dict(frame.get('pose') or {})
        item['time'] = int(round(_safe_int(frame.get('time'), 0) / speed))
        item['moveMs'] = int(round(_safe_int(frame.get('moveMs'), 100) / speed))
        scaled.append(item)
    return scaled


def import_dollser_motion_file(path: str, motion_name: str = None) -> str:
    """
    导入 v2 dollser-motion 文件到动作库。

    Returns:
        实际写入的动作名称
    """
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    if not _is_dollser_motion_document(raw):
        raise ValueError("文件不是 v2 dollser-motion 格式")

    detected_name, frames = convert_dollser_motion_to_frames(raw)
    target_name = motion_name or detected_name

    with _document_lock:
        doc = load_document()
        motions = doc.get('motions', {})
        motions[target_name] = frames
        metas = doc.get('motionMeta', {})
        metas[target_name] = extract_dollser_motion_metadata(raw, frames)
        save_document({
            'version': CURRENT_SCHEMA_VERSION,
            'motions': motions,
            'motionMeta': metas,
        })
    return target_name
