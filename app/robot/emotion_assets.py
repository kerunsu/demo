"""
表情资源管理（文件系统 + emotions_meta.json）
不引入 DB 表；引用检查扫 course_map.json。
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import Config
from app.robot.config import COURSE_MAP_FILE, ROBOT_DATA_DIR
from app.robot.mp4_validation import inspect_mp4
from app.robot.video_optimizer import save_optimized_mp4
from app.utils.logger import setup_logger

logger = setup_logger('emotion_assets')

EMOTIONS_META_FILE = os.path.join(ROBOT_DATA_DIR, 'emotions_meta.json')
# 新素材统一使用 MP4；历史 GIF 只保留读取兼容，避免旧课程映射失效。
DEFAULT_EMOTION_FALLBACK = 'v3_speak_excitedly_short.mp4'
LEGACY_DEFAULT_EMOTION_FALLBACK = 'v3_speak_excitedly_short.mp4'
SAFE_EMOTION_NAME = re.compile(r'^[A-Za-z0-9_\-\.]+\.(?:mp4|gif)$', re.IGNORECASE)
SAFE_UPLOAD_EMOTION_NAME = re.compile(r'^[A-Za-z0-9_\-\.]+\.mp4$', re.IGNORECASE)
_duration_decode_lock = threading.Lock()
_meta_lock = threading.RLock()

DEFAULT_EMOTION_STYLE = {
    'speedMultiplier': 1.0,
    'scale': 1.0,
    'hueDeg': 0.0,
    'brightness': 1.0,
    'saturation': 1.0,
    'opacity': 1.0,
}
DEFAULT_GLOBAL_FILTER = {
    'enabled': False,
    'hueDeg': 0.0,
    'brightness': 1.0,
    'saturation': 1.0,
    'contrast': 1.0,
    'opacity': 1.0,
}
DEFAULT_DIALOGUE_REPLY_EXPRESSIONS = {
    'enabled': False,
    'rules': [],
}
DIALOGUE_REPLY_TIERS = ('short', 'medium', 'long')
STYLE_RANGES = {
    'speedMultiplier': (0.25, 4.0),
    'scale': (0.5, 2.0),
    'hueDeg': (-180.0, 180.0),
    'brightness': (0.0, 2.0),
    'saturation': (0.0, 2.0),
    'opacity': (0.0, 1.0),
}
GLOBAL_FILTER_RANGES = {
    'hueDeg': (-180.0, 180.0),
    'brightness': (0.0, 2.0),
    'saturation': (0.0, 2.0),
    'contrast': (0.0, 2.0),
    'opacity': (0.0, 1.0),
}


def emotions_dir() -> str:
    return os.path.join(Config.STATIC_DIR, 'resources', 'Emotions')


def ensure_emotions_meta() -> None:
    os.makedirs(ROBOT_DATA_DIR, exist_ok=True)
    if not os.path.exists(EMOTIONS_META_FILE):
        _atomic_write_meta({
            'version': 2,
            'default': DEFAULT_EMOTION_FALLBACK,
            'styles': {},
            'globalFilter': dict(DEFAULT_GLOBAL_FILTER),
        })
    os.makedirs(emotions_dir(), exist_ok=True)


def _load_meta() -> Dict[str, Any]:
    ensure_emotions_meta()
    try:
        with _meta_lock:
            with open(EMOTIONS_META_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception as e:
        logger.warning(f'读取 emotions_meta.json 失败: {e}')
    return {'default': DEFAULT_EMOTION_FALLBACK}


def _save_meta(meta: Dict[str, Any]) -> None:
    ensure_emotions_meta()
    normalized = dict(meta)
    normalized['version'] = 2
    normalized['styles'] = (
        dict(normalized.get('styles')) if isinstance(normalized.get('styles'), dict) else {}
    )
    normalized['globalFilter'] = _effective_global_filter(normalized.get('globalFilter'))
    normalized['dialogueReplyExpressions'] = _normalize_dialogue_reply_expressions(
        normalized.get('dialogueReplyExpressions'),
        validate_files=False,
    )
    with _meta_lock:
        _atomic_write_meta(normalized)


def _atomic_write_meta(meta: Dict[str, Any]) -> None:
    target = os.path.abspath(EMOTIONS_META_FILE)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f'.{os.path.basename(target)}.', suffix='.tmp',
        dir=os.path.dirname(target),
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _finite_number(value: Any, field: str, bounds: Tuple[float, float]) -> float:
    if isinstance(value, bool):
        raise ValueError(f'{field} must be a number')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field} must be a number') from None
    if not math.isfinite(number) or not bounds[0] <= number <= bounds[1]:
        raise ValueError(f'{field} must be between {bounds[0]} and {bounds[1]}')
    return number


def _effective_style(value: Any) -> Dict[str, float]:
    source = value if isinstance(value, dict) else {}
    result = dict(DEFAULT_EMOTION_STYLE)
    for key, bounds in STYLE_RANGES.items():
        try:
            result[key] = _finite_number(source.get(key, result[key]), key, bounds)
        except ValueError:
            result[key] = DEFAULT_EMOTION_STYLE[key]
    return result


def _effective_global_filter(value: Any) -> Dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    result = dict(DEFAULT_GLOBAL_FILTER)
    result['enabled'] = source.get('enabled') if isinstance(source.get('enabled'), bool) else False
    for key, bounds in GLOBAL_FILTER_RANGES.items():
        try:
            result[key] = _finite_number(source.get(key, result[key]), key, bounds)
        except ValueError:
            result[key] = DEFAULT_GLOBAL_FILTER[key]
    return result


def _normalize_dialogue_reply_expressions(
    value: Any,
    *,
    validate_files: bool,
) -> Dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    enabled = source.get('enabled', False)
    if not isinstance(enabled, bool):
        raise ValueError('enabled must be a boolean')
    raw_rules = source.get('rules', [])
    if not isinstance(raw_rules, list):
        raise ValueError('rules must be an array')
    if raw_rules and len(raw_rules) != len(DIALOGUE_REPLY_TIERS):
        raise ValueError('大模型回复表情必须配置短、中、长三个档位')

    available = set(list_emotion_files()) if validate_files else None
    rules: List[Dict[str, Any]] = []
    previous_max = 0
    for index, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise ValueError(f'rules[{index}] must be an object')
        try:
            max_chars = int(raw.get('maxChars'))
        except (TypeError, ValueError):
            raise ValueError(f'rules[{index}].maxChars must be an integer') from None
        if isinstance(raw.get('maxChars'), bool) or not 1 <= max_chars <= 1000:
            raise ValueError(f'rules[{index}].maxChars must be between 1 and 1000')
        if max_chars <= previous_max:
            raise ValueError('规则字数上限必须严格递增')
        emotion = os.path.basename(str(raw.get('emotion') or '').strip())
        if not emotion.lower().endswith('.mp4'):
            raise ValueError(f'rules[{index}].emotion must be an MP4 expression')
        if available is not None and emotion not in available:
            raise FileNotFoundError(f'表情不存在: {emotion}')
        expected_tier = DIALOGUE_REPLY_TIERS[index]
        supplied_tier = str(raw.get('tier') or expected_tier).strip().lower()
        if supplied_tier != expected_tier:
            raise ValueError(f'rules[{index}].tier must be {expected_tier}')
        rules.append({
            'tier': expected_tier,
            'maxChars': max_chars,
            'emotion': emotion,
        })
        previous_max = max_chars
    if enabled and len(rules) != len(DIALOGUE_REPLY_TIERS):
        raise ValueError('启用大模型回复表情时必须完整配置短、中、长三个档位')
    return {'enabled': enabled, 'rules': rules}


def get_dialogue_reply_expressions() -> Dict[str, Any]:
    raw = _load_meta().get('dialogueReplyExpressions')
    try:
        return _normalize_dialogue_reply_expressions(raw, validate_files=False)
    except (ValueError, FileNotFoundError) as exc:
        logger.warning('大模型回复表情配置无效，按关闭处理: %s', exc)
        return dict(DEFAULT_DIALOGUE_REPLY_EXPRESSIONS)


def set_dialogue_reply_expressions(value: Any) -> Dict[str, Any]:
    normalized = _normalize_dialogue_reply_expressions(value, validate_files=True)
    meta = _load_meta()
    meta['dialogueReplyExpressions'] = normalized
    _save_meta(meta)
    return normalized


def select_dialogue_reply_emotion(text: str) -> Optional[Dict[str, Any]]:
    config = get_dialogue_reply_expressions()
    rules = config.get('rules') or []
    if not config.get('enabled') or not rules:
        return None
    char_count = len(''.join(str(text or '').split()))
    if char_count <= 0:
        return None
    selected = next(
        (rule for rule in rules if char_count <= int(rule['maxChars'])),
        rules[-1],
    )
    return {
        'emotion': selected['emotion'],
        'tier': selected['tier'],
        'charCount': char_count,
        'maxChars': int(selected['maxChars']),
    }


def list_emotion_files() -> List[str]:
    path = emotions_dir()
    if not os.path.isdir(path):
        return []
    try:
        files = [f for f in os.listdir(path) if f.lower().endswith(('.mp4', '.gif'))]
        files.sort(key=lambda name: (not name.lower().endswith('.mp4'), name.lower()))
        return files
    except Exception as e:
        logger.error(f'读取表情目录失败: {e}')
        return []


def get_emotion_style(name: str) -> Dict[str, float]:
    raw = _load_meta().get('styles', {})
    return _effective_style(raw.get(name) if isinstance(raw, dict) else None)


def set_emotion_style(name: str, value: Any) -> Dict[str, float]:
    name = os.path.basename(name or '')
    if name not in list_emotion_files():
        raise FileNotFoundError(f'Emotion not found: {name}')
    if not isinstance(value, dict):
        raise ValueError('style must be an object')
    unknown = set(value) - set(STYLE_RANGES)
    if unknown:
        raise ValueError(f'unknown style fields: {", ".join(sorted(unknown))}')
    style = dict(DEFAULT_EMOTION_STYLE)
    for key, bounds in STYLE_RANGES.items():
        style[key] = _finite_number(value.get(key, style[key]), key, bounds)
    if name.lower().endswith('.gif') and style['speedMultiplier'] != 1.0:
        raise ValueError('speedMultiplier is only supported for MP4 emotions')
    with _meta_lock:
        meta = _load_meta()
        styles = meta.get('styles') if isinstance(meta.get('styles'), dict) else {}
        styles[name] = style
        meta['styles'] = styles
        _save_meta(meta)
    return style


def get_global_filter() -> Dict[str, Any]:
    return _effective_global_filter(_load_meta().get('globalFilter'))


def set_global_filter(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError('globalFilter must be an object')
    allowed = {'enabled', *GLOBAL_FILTER_RANGES.keys()}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f'unknown global filter fields: {", ".join(sorted(unknown))}')
    if 'enabled' in value and not isinstance(value['enabled'], bool):
        raise ValueError('enabled must be a boolean')
    result = dict(DEFAULT_GLOBAL_FILTER)
    result['enabled'] = value.get('enabled', False)
    for key, bounds in GLOBAL_FILTER_RANGES.items():
        result[key] = _finite_number(value.get(key, result[key]), key, bounds)
    with _meta_lock:
        meta = _load_meta()
        meta['globalFilter'] = result
        _save_meta(meta)
    return result


def get_default_emotion() -> str:
    meta = _load_meta()
    name = meta.get('default') or DEFAULT_EMOTION_FALLBACK
    available = list_emotion_files()
    if not available:
        return name
    if name in available:
        return name
    # 默认文件已删：优先 MP4 idle，再退到历史 GIF 和目录中第一个素材。
    if DEFAULT_EMOTION_FALLBACK in available:
        return DEFAULT_EMOTION_FALLBACK
    if LEGACY_DEFAULT_EMOTION_FALLBACK in available:
        return LEGACY_DEFAULT_EMOTION_FALLBACK
    return available[0]


def get_idle_emotions() -> List[str]:
    """Return the configured random idle pool, preserving legacy ``default``."""
    meta = _load_meta()
    available = set(list_emotion_files())
    configured = meta.get('idlePool')
    idle_pool: List[str] = []
    if isinstance(configured, list):
        for raw_name in configured:
            name = os.path.basename(str(raw_name or ''))
            if name in available and name not in idle_pool:
                idle_pool.append(name)
    if idle_pool:
        return idle_pool
    default = get_default_emotion()
    return [default] if default else []


def set_idle_emotions(names: Any) -> List[str]:
    if not isinstance(names, list):
        raise ValueError('emotions must be an array')
    available = set(list_emotion_files())
    normalized: List[str] = []
    for raw_name in names:
        name = os.path.basename(str(raw_name or ''))
        if not SAFE_EMOTION_NAME.match(name):
            raise ValueError(f'invalid emotion filename: {raw_name}')
        if name not in available:
            raise FileNotFoundError(f'Emotion not found: {name}')
        if name not in normalized:
            normalized.append(name)
    if not normalized:
        raise ValueError('idle pool must contain at least one emotion')
    with _meta_lock:
        meta = _load_meta()
        meta['idlePool'] = normalized
        # Keep the historical single-default contract useful for old clients.
        meta['default'] = normalized[0]
        _save_meta(meta)
    return normalized


def set_default_emotion(name: str) -> str:
    name = os.path.basename(name or '')
    if not SAFE_EMOTION_NAME.match(name):
        raise ValueError('非法表情文件名')
    available = list_emotion_files()
    if name not in available:
        raise FileNotFoundError(f'表情不存在: {name}')
    meta = _load_meta()
    meta['default'] = name
    meta['idlePool'] = [name]
    _save_meta(meta)
    return name


def _walk_emotion_refs(node: Any, path: str, out: List[Tuple[str, str]]) -> None:
    if isinstance(node, dict):
        emotion = node.get('emotion')
        if isinstance(emotion, str) and emotion:
            out.append((path, emotion))
        emotion_pool = node.get('emotions')
        if isinstance(emotion_pool, list):
            for index, item in enumerate(emotion_pool):
                if isinstance(item, str) and item:
                    pool_path = f'{path}.emotions[{index}]' if path else f'emotions[{index}]'
                    out.append((pool_path, item))
        for key, value in node.items():
            if key in {'emotion', 'emotions'}:
                continue
            child_path = f'{path}.{key}' if path else str(key)
            _walk_emotion_refs(value, child_path, out)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            _walk_emotion_refs(item, f'{path}[{i}]', out)


def find_emotion_references(name: str) -> List[str]:
    """返回课程绑定和大模型回复规则中引用该表情的路径列表。"""
    try:
        with open(COURSE_MAP_FILE, 'r', encoding='utf-8') as f:
            course_map = json.load(f)
    except Exception:
        course_map = {}
    refs: List[Tuple[str, str]] = []
    _walk_emotion_refs(course_map, '', refs)
    result = [path for path, emo in refs if emo == name]
    dialogue = get_dialogue_reply_expressions()
    for index, rule in enumerate(dialogue.get('rules') or []):
        if rule.get('emotion') == name:
            result.append(f'emotions_meta.dialogueReplyExpressions.rules[{index}]')
    return result


def count_emotion_references(name: str) -> int:
    return len(find_emotion_references(name))


def get_emotions_payload() -> Dict[str, Any]:
    files = list_emotion_files()
    default = get_default_emotion()
    idle_pool = get_idle_emotions()
    items = []
    for name in files:
        ref_paths = find_emotion_references(name)
        asset_path = Path(emotions_dir()) / name
        try:
            stat = asset_path.stat()
            asset_version = f'{stat.st_mtime_ns:x}-{stat.st_size:x}'
        except OSError:
            asset_version = 'missing'
        item = {
            'name': name,
            'refCount': len(ref_paths),
            'referencedBy': ref_paths,
            'isDefault': name == default,
            'isIdle': name in idle_pool,
            'url': f'/static/resources/Emotions/{name}?v={asset_version}',
            'version': asset_version,
            'format': Path(name).suffix.lower().lstrip('.'),
            'deprecated': name.lower().endswith('.gif'),
            'style': get_emotion_style(name),
            'speedSupported': name.lower().endswith('.mp4'),
        }
        if name.lower().endswith('.mp4'):
            try:
                item.update(inspect_mp4(asset_path.read_bytes()))
            except (OSError, ValueError) as exc:
                item.update({
                    'validationStatus': 'invalid',
                    'validationWarnings': [str(exc)],
                })
        items.append(item)
    return {
        'emotions': files,
        'default': default,
        'idlePool': idle_pool,
        'items': items,
        'globalFilter': get_global_filter(),
    }


def _resolve_expression_media(media_id: str) -> Optional[Path]:
    raw = str(media_id or '').strip().replace('\\', '/')
    if not raw.lower().endswith(('.gif', '.mp4')):
        return None
    if raw.startswith('resources/'):
        candidate = Path(Config.STATIC_DIR) / raw
    elif raw.startswith('static/'):
        candidate = Path(Config.STATIC_DIR) / raw[len('static/'):]
    else:
        candidate = Path(emotions_dir()) / os.path.basename(raw)
    static_root = Path(Config.STATIC_DIR).resolve()
    path = candidate.resolve()
    if static_root not in path.parents or not path.is_file():
        return None
    return path


@lru_cache(maxsize=64)
def _decode_gif_duration(path_text: str, mtime_ns: int, size: int) -> int:
    """按路径、修改时间和大小缓存 GIF 时长。"""
    del mtime_ns, size
    path = Path(path_text)
    with _duration_decode_lock:
        # Pillow 会按真实帧解析，避免在 LZW 压缩数据中误命中 21 F9 04 字节串。
        from PIL import Image, ImageSequence
        with Image.open(path) as image:
            fallback = int(image.info.get('duration', 100) or 100)
            return sum(
                int(frame.info.get('duration', fallback) or fallback)
                for frame in ImageSequence.Iterator(image)
            )


def _mp4_boxes(data: bytes, start: int = 0, end: Optional[int] = None):
    """Yield bounded ISO-BMFF boxes without requiring ffmpeg or OpenCV."""

    cursor = start
    limit = len(data) if end is None else min(end, len(data))
    while cursor + 8 <= limit:
        size = int.from_bytes(data[cursor:cursor + 4], 'big')
        kind = data[cursor + 4:cursor + 8]
        header = 8
        if size == 1:
            if cursor + 16 > limit:
                return
            size = int.from_bytes(data[cursor + 8:cursor + 16], 'big')
            header = 16
        elif size == 0:
            size = limit - cursor
        if size < header or cursor + size > limit:
            return
        yield kind, cursor + header, cursor + size
        cursor += size


@lru_cache(maxsize=64)
def _decode_mp4_duration(path_text: str, mtime_ns: int, size: int) -> int:
    del mtime_ns, size
    data = Path(path_text).read_bytes()
    for kind, payload_start, box_end in _mp4_boxes(data):
        if kind != b'moov':
            continue
        for child_kind, child_start, child_end in _mp4_boxes(data, payload_start, box_end):
            if child_kind != b'mvhd' or child_start + 20 > child_end:
                continue
            version = data[child_start]
            if version == 0:
                timescale_pos = child_start + 12
                duration_pos = child_start + 16
                duration_size = 4
            elif version == 1:
                timescale_pos = child_start + 20
                duration_pos = child_start + 24
                duration_size = 8
            else:
                return 0
            if duration_pos + duration_size > child_end:
                return 0
            timescale = int.from_bytes(data[timescale_pos:timescale_pos + 4], 'big')
            duration = int.from_bytes(data[duration_pos:duration_pos + duration_size], 'big')
            if timescale <= 0:
                return 0
            return max(1, int(round(duration * 1000 / timescale)))
    return 0


def get_expression_duration_ms(media_id: str) -> int:
    """读取并缓存 GIF/MP4 单次播放时长。"""
    try:
        path = _resolve_expression_media(media_id)
        if not path:
            return 0
        stat = path.stat()
        if path.suffix.lower() == '.mp4':
            duration = _decode_mp4_duration(str(path), stat.st_mtime_ns, stat.st_size)
            if not duration:
                return 0
            speed = get_emotion_style(path.name)['speedMultiplier']
            return max(1, int(round(duration / speed)))
        return _decode_gif_duration(str(path), stat.st_mtime_ns, stat.st_size)
    except Exception as exc:
        logger.warning('读取表情时长失败 %s: %s', media_id, exc)
        return 0


def warm_expression_duration_cache() -> None:
    """后台预热表情时长，优先处理 course_map 当前引用的素材。"""
    referenced: List[str] = []
    try:
        with open(COURSE_MAP_FILE, 'r', encoding='utf-8') as f:
            course_map = json.load(f)
        refs: List[Tuple[str, str]] = []
        _walk_emotion_refs(course_map, '', refs)
        referenced = [name for _, name in refs]
    except Exception as exc:
        logger.debug('预热时读取表情引用失败: %s', exc)

    ordered = list(dict.fromkeys(referenced + list_emotion_files()))
    for name in ordered:
        get_expression_duration_ms(name)
    logger.info('表情时长缓存预热完成: %s 个文件', len(ordered))


def save_uploaded_emotion(
    filename: str,
    file_bytes: bytes,
    *,
    return_details: bool = False,
) -> str | Dict[str, Any]:
    name = os.path.basename(filename or '')
    if not SAFE_UPLOAD_EMOTION_NAME.match(name):
        raise ValueError('新表情仅允许 .mp4，且文件名只能含字母数字、_、-、.')
    if b'..' in name.encode('utf-8') or '/' in name or '\\' in name:
        raise ValueError('非法路径')
    if not file_bytes:
        raise ValueError('空文件')
    dest_dir = emotions_dir()
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    if os.path.exists(dest):
        raise FileExistsError(f'表情已存在: {name}')
    result = save_optimized_mp4(dest_dir, name, file_bytes, kind='emotion')
    logger.info(
        '已上传表情: %s optimized=%s %s->%s bytes',
        name, result['optimized'], result['originalSizeBytes'], result['sizeBytes'],
    )
    return result if return_details else name


def delete_emotion_file(name: str, force: bool = False) -> None:
    name = os.path.basename(name or '')
    if not SAFE_EMOTION_NAME.match(name):
        raise ValueError('非法表情文件名')
    refs = find_emotion_references(name)
    if refs and not force:
        raise PermissionError(f'表情仍被 course_map 引用（{len(refs)} 处）')
    path = os.path.join(emotions_dir(), name)
    if not os.path.isfile(path):
        raise FileNotFoundError(f'表情不存在: {name}')
    idle_pool_before_delete = get_idle_emotions()
    os.remove(path)
    with _meta_lock:
        meta = _load_meta()
        idle_pool = [item for item in idle_pool_before_delete if item != name]
        if not idle_pool:
            idle_pool = list_emotion_files()[:1]
        if idle_pool:
            meta['idlePool'] = idle_pool
            meta['default'] = idle_pool[0]
        else:
            meta['idlePool'] = []
            meta['default'] = DEFAULT_EMOTION_FALLBACK
        styles = meta.get('styles') if isinstance(meta.get('styles'), dict) else {}
        styles.pop(name, None)
        meta['styles'] = styles
        _save_meta(meta)
    logger.info(f'已删除表情: {name} (force={force})')
