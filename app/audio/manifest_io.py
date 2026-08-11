"""
读写 audio_manifest.yaml，供配置中心课型/社交语音配置使用。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from app.config import BASE_DIR
from app.utils.logger import setup_logger

logger = setup_logger('audio.manifest_io')

MANIFEST_PATH = BASE_DIR / 'config' / 'audio_manifest.yaml'
BASE_PREFIXES = ('resources/audios/', 'audios/')

STANDARD_QP_TYPES = ('naming', 'onomatopoeia', 'mimic', 'pairing', 'ordering')
SOCIAL_ENTRY_KEYS = (
    'social_greeting_intro',
    'social_greeting_play',
    'social_farewell_bye',
    'social_farewell_reply',
)
SOCIAL_ROLE_ENTRIES = {
    'greeting': [
        ('social_greeting_intro', '初见打招呼'),
        ('social_greeting_play', '一起玩耍吧'),
    ],
    'farewell': [
        ('social_farewell_bye', '再见'),
        ('social_farewell_reply', '回应'),
    ],
}

# 排序课 8 种提问（category + rule）
ORDERING_QUESTION_SLOTS = [
    ('question_size_bigger', '大小·选大的', 'size', 'bigger'),
    ('question_size_smaller', '大小·选小的', 'size', 'smaller'),
    ('question_length_longer', '长短·选长的', 'length', 'longer'),
    ('question_length_shorter', '长短·选短的', 'length', 'shorter'),
    ('question_height_taller', '高矮·选高的', 'height', 'taller'),
    ('question_height_shorter', '高矮·选矮的', 'height', 'shorter'),
    ('question_count_more', '多少·选多的', 'count', 'more'),
    ('question_count_less', '多少·选少的', 'count', 'less'),
]
ORDERING_QUESTION_KEYS = tuple(k for k, *_ in ORDERING_QUESTION_SLOTS)
ORDERING_RULE_TO_AUDIO = {
    (cat, rule): key for key, _label, cat, rule in ORDERING_QUESTION_SLOTS
}


def ordering_audio_type(category: str, rule: str) -> str:
    """排序 category+rule → course_defaults 音频键；未知则回退 question。"""
    return ORDERING_RULE_TO_AUDIO.get((category, rule), 'question')



def _load_raw() -> Dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f'manifest not found: {MANIFEST_PATH}')
    with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError('invalid manifest root')
    data.setdefault('entries', {})
    data.setdefault('course_defaults', {})
    data.setdefault('base_path', 'resources/audios')
    return data


def _save_raw(data: Dict[str, Any]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, 'w', encoding='utf-8') as f:
        yaml.safe_dump(
            data,
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


def reload_registry() -> None:
    try:
        from app.audio.registry import get_audio_registry
        get_audio_registry().load_manifest(str(MANIFEST_PATH))
        logger.info('AudioRegistry reloaded from manifest')
    except Exception as e:
        logger.warning('reload AudioRegistry failed: %s', e)


def to_entry_relative_path(stored: str) -> str:
    """媒资选择器路径 → manifest entry 内相对 path（保留文件夹末尾 /）。"""
    p = (stored or '').strip().replace('\\', '/')
    if not p:
        return ''
    trailing = p.endswith('/')
    for prefix in BASE_PREFIXES:
        if p.startswith(prefix):
            out = p[len(prefix):]
            break
    else:
        if p.startswith('resources/'):
            out = p[len('resources/'):]
        else:
            out = p.lstrip('/')
    if trailing and out and not out.endswith('/'):
        out += '/'
    return out


def to_display_path(rel: str, base_path: str = 'resources/audios') -> str:
    """entry 相对 path → 前端展示/播放用完整路径（保留文件夹末尾 /）。"""
    rel = (rel or '').strip().replace('\\', '/')
    if not rel:
        return ''
    trailing = rel.endswith('/')
    if rel.startswith('resources/'):
        return rel if not trailing or rel.endswith('/') else rel + '/'
    base = (base_path or 'resources/audios').rstrip('/')
    out = f'{base}/{rel}'.replace('//', '/')
    if trailing and not out.endswith('/'):
        out += '/'
    return out


def _first_file_path(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ''
    files = entry.get('files') or []
    if not files:
        return ''
    first = files[0]
    if isinstance(first, str):
        return first
    if isinstance(first, dict):
        return str(first.get('path') or '')
    return ''


def get_entry_display_path(entry_id: str) -> Tuple[str, str]:
    """返回 (entry_id, display_path)。"""
    data = _load_raw()
    entry = (data.get('entries') or {}).get(entry_id) or {}
    rel = _first_file_path(entry)
    return entry_id, to_display_path(rel, data.get('base_path', 'resources/audios'))


def set_entry_single_file(entry_id: str, file_path: str, description: Optional[str] = None) -> Dict[str, Any]:
    """将 entry 设为单路径；文件夹用 random，单文件用 sequential。"""
    data = _load_raw()
    entries = data.setdefault('entries', {})
    rel = to_entry_relative_path(file_path)
    if not rel:
        raise ValueError('empty file path')
    prev = entries.get(entry_id) if isinstance(entries.get(entry_id), dict) else {}
    is_dir = rel.endswith('/')
    entries[entry_id] = {
        'category': prev.get('category') or 'course.custom',
        'intent': prev.get('intent') or entry_id,
        'description': description or prev.get('description') or entry_id,
        'files': [{'path': rel}],
        'selection': 'random' if is_dir else 'sequential',
    }
    _save_raw(data)
    reload_registry()
    return {
        'entryId': entry_id,
        'filePath': to_display_path(rel, data.get('base_path', 'resources/audios')),
    }


def get_course_type_defaults(course_type: str) -> Dict[str, Any]:
    data = _load_raw()
    defaults = (data.get('course_defaults') or {}).get(course_type) or {}
    base = data.get('base_path', 'resources/audios')
    entries = data.get('entries') or {}

    def resolve(audio_type: str) -> Dict[str, str]:
        entry_id = defaults.get(audio_type) or ''
        rel = _first_file_path(entries.get(entry_id)) if entry_id else ''
        return {
            'entryId': entry_id or '',
            'filePath': to_display_path(rel, base) if rel else '',
        }

    out: Dict[str, Any] = {
        'courseType': course_type,
        'question': resolve('question'),
        'praise': resolve('praise'),
        'hint': resolve('hint'),
    }
    if course_type == 'social':
        social = {}
        for key in SOCIAL_ENTRY_KEYS:
            entry_id = defaults.get(key) or key
            rel = _first_file_path(entries.get(entry_id)) if entry_id else ''
            social[key] = {
                'entryId': entry_id,
                'filePath': to_display_path(rel, base) if rel else '',
            }
        out['social'] = social
    if course_type == 'ordering':
        ordering_qs = []
        for key, label, cat, rule in ORDERING_QUESTION_SLOTS:
            info = resolve(key)
            # 未单独配置时回退到通用 question
            if not info.get('filePath'):
                info = resolve('question')
                info['entryId'] = defaults.get(key) or info.get('entryId') or ''
            ordering_qs.append({
                'key': key,
                'label': label,
                'category': cat,
                'rule': rule,
                **info,
            })
        out['orderingQuestions'] = ordering_qs
    return out


def set_course_type_audio(course_type: str, audio_type: str, file_path: str) -> Dict[str, Any]:
    """
    为课型设置 question/praise/hint 或排序八问键：写入专用 entry，
    并更新 course_defaults，避免共享 entry 互相覆盖。
    """
    if course_type not in STANDARD_QP_TYPES:
        raise ValueError(f'unsupported course type for qp config: {course_type}')
    allowed = {'question', 'praise', 'hint', *ORDERING_QUESTION_KEYS}
    if audio_type not in allowed:
        raise ValueError(f'unsupported audio type: {audio_type}')
    # 排序八问仅 ordering 可写
    if audio_type in ORDERING_QUESTION_KEYS and course_type != 'ordering':
        raise ValueError(f'{audio_type} only allowed for ordering')

    rel = to_entry_relative_path(file_path)
    if not rel:
        raise ValueError('empty file path')

    data = _load_raw()
    entry_id = f'{course_type}_{audio_type}'
    entries = data.setdefault('entries', {})
    prev = entries.get(entry_id) if isinstance(entries.get(entry_id), dict) else {}
    entries[entry_id] = {
        'category': prev.get('category') or f'course.{course_type}',
        'intent': prev.get('intent') or audio_type,
        'description': prev.get('description') or f'{course_type} {audio_type}',
        'files': [{'path': rel}],
        'selection': 'random' if rel.endswith('/') else 'sequential',
    }
    cd = data.setdefault('course_defaults', {})
    type_map = cd.setdefault(course_type, {})
    type_map[audio_type] = entry_id
    _save_raw(data)
    reload_registry()
    return {
        'courseType': course_type,
        'audioType': audio_type,
        'entryId': entry_id,
        'filePath': to_display_path(rel, data.get('base_path', 'resources/audios')),
    }


def set_social_button_audio(entry_key: str, file_path: str) -> Dict[str, Any]:
    if entry_key not in SOCIAL_ENTRY_KEYS:
        raise ValueError(f'invalid social entry: {entry_key}')
    rel = to_entry_relative_path(file_path)
    if not rel:
        raise ValueError('empty file path')
    data = _load_raw()
    entries = data.setdefault('entries', {})
    prev = entries.get(entry_key) if isinstance(entries.get(entry_key), dict) else {}
    entries[entry_key] = {
        'category': prev.get('category') or 'course.social',
        'intent': prev.get('intent') or entry_key,
        'description': prev.get('description') or f'social {entry_key}',
        'files': [{'path': rel}],
        'selection': 'random' if rel.endswith('/') else 'sequential',
    }
    social = data.setdefault('course_defaults', {}).setdefault('social', {})
    social[entry_key] = entry_key
    _save_raw(data)
    reload_registry()
    return {
        'entryId': entry_key,
        'filePath': to_display_path(rel, data.get('base_path', 'resources/audios')),
    }


def type_has_question_praise(course_type: str) -> Tuple[bool, bool]:
    info = get_course_type_defaults(course_type)
    has_q = bool((info.get('question') or {}).get('filePath'))
    has_p = bool((info.get('praise') or {}).get('filePath'))
    return has_q, has_p


def list_types_missing_question() -> List[str]:
    missing = []
    for t in STANDARD_QP_TYPES:
        has_q, _ = type_has_question_praise(t)
        if not has_q:
            missing.append(t)
    return missing
