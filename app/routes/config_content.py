"""
配置中心 · 交互内容 API
课程 / 课点 CRUD + 媒资浏览上传 + 工作台汇总
前缀: /api/config
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from app.config import BASE_DIR, Config
from app.course_scope import (
    canonical_course_type,
    enabled_course_types,
    filter_course_payloads,
    is_course_type_enabled,
)
from app.robot.config import COURSE_MAP_FILE
from app.storage.repositories.course_preset_store import JsonCoursePresetStore
from app.utils.logger import setup_logger
from database.models import Course, CourseItem, CourseType, db

logger = setup_logger('config_content')

config_content_bp = Blueprint('config_content', __name__, url_prefix='/api/config')

RESOURCES_ROOT = Path(Config.STATIC_DIR) / 'resources'
ALLOWED_MEDIA_EXT = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp',
    '.mp3', '.wav', '.ogg', '.m4a', '.aac',
    '.mp4', '.webm', '.mov',
    '.html', '.htm',
}
TYPE_EN_TO_CN = {
    'mimic': '模仿',
    'naming': '命名',
    'onomatopoeia': '拟声',
    'pairing': '配对',
    'ordering': '排序',
    'social': '社交',
}
TYPE_CN_TO_EN = {v: k for k, v in TYPE_EN_TO_CN.items()}
_COURSE_PRESET_STORE = JsonCoursePresetStore(BASE_DIR / 'config' / 'course_presets.json')

_DEMO_GLOBAL_PHRASE_INTENTS = frozenset({'attention', 'reward'})
_DEMO_COURSE_PHRASE_INTENTS = frozenset({'question', 'hint', 'praise'})
_DEMO_ORDERING_QUESTION_VARIANTS = frozenset({
    'size_bigger', 'size_smaller',
    'length_longer', 'length_shorter',
    'height_taller', 'height_shorter',
    'count_more', 'count_less',
})


def _demo_phrase_scope(intent: str, course_type: str) -> str:
    """Validate and canonicalize a phrase write against the fixed Demo scope."""
    normalized_intent = str(intent or '').strip().lower()
    raw_type = str(course_type or '').strip().lower()
    normalized_type = canonical_course_type(raw_type)
    if normalized_type == 'global' and normalized_intent in _DEMO_GLOBAL_PHRASE_INTENTS:
        return normalized_type
    if (
        is_course_type_enabled(normalized_type)
        and normalized_intent in _DEMO_COURSE_PHRASE_INTENTS
    ):
        return normalized_type
    if (
        raw_type in _DEMO_ORDERING_QUESTION_VARIANTS
        and normalized_intent == 'question'
    ):
        return raw_type
    raise ValueError('Demo 版仅允许全局、模仿、配对和排序话术')


def ensure_speech_target_column() -> None:
    """SQLite：若缺 speech_target 列则 ALTER 补上。"""
    try:
        rows = db.session.execute(text('PRAGMA table_info(course_item)')).fetchall()
        cols = {r[1] for r in rows}
        if 'speech_target' not in cols:
            db.session.execute(text(
                'ALTER TABLE course_item ADD COLUMN speech_target VARCHAR(200)'
            ))
            db.session.commit()
            logger.info('已为 course_item 添加 speech_target 列')
    except Exception as e:
        db.session.rollback()
        logger.warning('ensure_speech_target_column: %s', e)


def _safe_rel_under_resources(rel: str) -> Path:
    """将相对 resources 的路径解析为绝对 Path，禁止跳出。"""
    rel = (rel or '').replace('\\', '/').lstrip('/')
    if rel.startswith('resources/'):
        rel = rel[len('resources/'):]
    if rel.startswith('static/resources/'):
        rel = rel[len('static/resources/'):]
    if '..' in rel.split('/'):
        raise ValueError('非法路径')
    target = (RESOURCES_ROOT / rel).resolve()
    root = RESOURCES_ROOT.resolve()
    if not str(target).startswith(str(root)):
        raise ValueError('路径超出 resources 根目录')
    return target


def _to_static_rel(path_under_resources: str, is_dir: bool = False) -> str:
    """返回存库用相对路径：resources/... 或尾 /。"""
    p = path_under_resources.replace('\\', '/').lstrip('/')
    if p.startswith('resources/'):
        out = p
    else:
        out = f'resources/{p}' if p else 'resources/'
    if is_dir and not out.endswith('/'):
        out += '/'
    return out


def _normalize_stored_path(p: Optional[str]) -> Optional[str]:
    if not p:
        return None
    return p.replace('\\', '/')


def _load_course_map() -> Dict[str, Any]:
    try:
        with open(COURSE_MAP_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _course_ids_with_mapping(course_map: Dict[str, Any]) -> Set[int]:
    ids: Set[int] = set()
    courses = course_map.get('courses') or {}
    for cid in courses.keys():
        try:
            ids.add(int(cid))
        except (TypeError, ValueError):
            pass
    students = course_map.get('students') or {}
    for st in students.values():
        if not isinstance(st, dict):
            continue
        for cid in (st.get('courses') or {}).keys():
            try:
                ids.add(int(cid))
            except (TypeError, ValueError):
                pass
        for key in (st.get('items') or {}).keys():
            # key 可能是 "courseId_itemId" 或嵌套
            parts = str(key).split('_')
            if parts and parts[0].isdigit():
                ids.add(int(parts[0]))
    return ids


def _course_map_refs_for_course(course_id: int) -> List[str]:
    cm = _load_course_map()
    refs = []
    courses = cm.get('courses') or {}
    if str(course_id) in courses or course_id in courses:
        refs.append(f'courses.{course_id}')
    students = cm.get('students') or {}
    for sid, st in students.items():
        if not isinstance(st, dict):
            continue
        st_courses = st.get('courses') or {}
        if str(course_id) in st_courses or course_id in st_courses:
            refs.append(f'students.{sid}.courses.{course_id}')
        items = st.get('items') or {}
        for key in items.keys():
            if str(key).startswith(f'{course_id}_') or str(key).startswith(f'{course_id}/'):
                refs.append(f'students.{sid}.items.{key}')
    return refs


def _find_media_refs(rel_path: str) -> List[str]:
    """扫 Course / CourseItem 路径字段。rel_path 可为 resources/... 或带尾 /。"""
    path = _normalize_stored_path(rel_path) or ''
    # 也匹配不带 resources/ 前缀、以及目录前缀
    variants = {path, path.rstrip('/'), path.rstrip('/') + '/'}
    if path.startswith('resources/'):
        variants.add(path[len('resources/'):])
        variants.add(path[len('resources/'):].rstrip('/') + '/')
    refs: List[str] = []
    for c in Course.query.all():
        for field, val in (
            ('question_audio', c.question_audio),
            ('praise_audio', c.praise_audio),
            ('entry_file', c.entry_file),
            ('icon', c.icon),
        ):
            v = _normalize_stored_path(val)
            if not v:
                continue
            if v in variants or any(v.startswith(x.rstrip('/') + '/') for x in variants if x.endswith('/')):
                refs.append(f'course:{c.id}.{field}')
            elif path.endswith('/') and v.startswith(path):
                refs.append(f'course:{c.id}.{field}')
    for it in CourseItem.query.all():
        for field, val in (
            ('media_file', it.media_file),
            ('hint_audio', it.hint_audio),
            ('icon', it.icon),
        ):
            v = _normalize_stored_path(val)
            if not v:
                continue
            if v in variants:
                refs.append(f'item:{it.id}.{field}')
            elif path.endswith('/') and v.startswith(path.rstrip('/') + '/'):
                refs.append(f'item:{it.id}.{field}')
    return refs


def _course_admin_dict(course: Course, mapped_ids: Optional[Set[int]] = None) -> Dict[str, Any]:
    from app.audio.manifest_io import STANDARD_QP_TYPES, type_has_question_praise

    base = course.to_dict()
    items = course.items or []
    missing_media = sum(1 for it in items if not (it.media_file or '').strip())
    type_en = base.get('type') or TYPE_CN_TO_EN.get(
        course.course_type.name if course.course_type else '', ''
    )
    base['courseTypeId'] = course.course_type_id
    base['courseTypeName'] = course.course_type.name if course.course_type else None
    base['itemCount'] = len(items)
    # 提问/表扬就绪以课型 manifest 为准（社交不适用）
    if type_en == 'social':
        base['hasQuestionAudio'] = None  # UI 显示「不适用」
        base['hasPraiseAudio'] = None
        base['audioConfigMode'] = 'social'
    elif type_en in STANDARD_QP_TYPES:
        has_q, has_p = type_has_question_praise(type_en)
        base['hasQuestionAudio'] = has_q
        base['hasPraiseAudio'] = has_p
        base['audioConfigMode'] = 'type_shared'
    else:
        base['hasQuestionAudio'] = bool(course.question_audio)
        base['hasPraiseAudio'] = bool(course.praise_audio)
        base['audioConfigMode'] = 'legacy'
    base['missingItemMedia'] = missing_media
    if mapped_ids is not None:
        base['hasBehaviorMapping'] = course.id in mapped_ids
    return base


def _item_admin_dict(item: CourseItem) -> Dict[str, Any]:
    from app.audio.manifest_io import SOCIAL_ROLE_ENTRIES, get_entry_display_path

    d = item.to_dict()
    d['courseId'] = item.course_id
    d['mediaFile'] = item.media_file
    d['hintAudio'] = item.hint_audio
    d['speechTarget'] = getattr(item, 'speech_target', None)
    cfg = d.get('config') if isinstance(d.get('config'), dict) else {}
    role = cfg.get('socialRole')
    if not role and item.name in ('打招呼', '再见'):
        role = 'greeting' if item.name == '打招呼' else 'farewell'
    if role in SOCIAL_ROLE_ENTRIES:
        buttons = []
        for entry_id, label in SOCIAL_ROLE_ENTRIES[role]:
            _, path = get_entry_display_path(entry_id)
            buttons.append({'entryId': entry_id, 'label': label, 'filePath': path})
        d['socialRole'] = role
        d['socialButtons'] = buttons
    return d


def _course_preset_catalog() -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    catalog: List[Dict[str, Any]] = []
    by_type: Dict[str, Dict[str, Any]] = {}
    for course in Course.query.order_by(Course.id).all():
        type_key = TYPE_CN_TO_EN.get(
            course.course_type.name if course.course_type else '',
            course.course_type.name if course.course_type else '',
        )
        if not is_course_type_enabled(type_key):
            continue
        item = {
            'id': course.id,
            'title': course.course_type.name if course.course_type else course.title,
            'type': type_key,
            'typeName': course.course_type.name if course.course_type else None,
            'itemCount': len(course.items or []),
            'items': [
                {
                    'id': course_item.id,
                    'name': course_item.name,
                    'icon': course_item.icon,
                    'file': course_item.media_file,
                }
                for course_item in sorted(course.items or [], key=lambda value: value.id)
            ],
        }
        if type_key in by_type:
            raise RuntimeError(f'duplicate_course_type:{type_key}')
        catalog.append(item)
        by_type[type_key] = item
    return catalog, by_type


def _course_preset_response() -> Dict[str, Any]:
    document = _COURSE_PRESET_STORE.get_document()
    catalog, by_type = _course_preset_catalog()
    presets = []
    for raw in document['presets']:
        preset = dict(raw)
        selections = preset['courseSelections']
        course_types = [selection['courseType'] for selection in selections]
        missing = [course_type for course_type in course_types if course_type not in by_type]
        missing_item_ids: Dict[str, List[int]] = {}
        resolved_courses = []
        for selection in selections:
            course_type = selection['courseType']
            course = by_type.get(course_type)
            if course is None:
                continue
            available_ids = {item['id'] for item in course['items']}
            unresolved = [item_id for item_id in selection['itemIds'] if item_id not in available_ids]
            if unresolved:
                missing_item_ids[course_type] = unresolved
            resolved = dict(course)
            resolved['selectedItemIds'] = list(selection['itemIds'])
            resolved_courses.append(resolved)
        preset['courseTypes'] = course_types
        preset['courses'] = resolved_courses
        # Compatibility fields remain derived for older teacher bundles. The
        # persisted schema-v3 facts are mode + courseSelections.
        preset['courseIds'] = [course['id'] for course in preset['courses']]
        preset['missingCourseTypes'] = missing
        preset['missingItemIds'] = missing_item_ids
        preset['emptyCourseTypes'] = []
        preset['missingCourseIds'] = []
        preset['emptyCourseIds'] = []
        preset['available'] = not missing and not missing_item_ids
        preset['isDefault'] = raw['id'] == document['defaultPresetIds'][raw['mode']]
        presets.append(preset)
    return {
        'success': True,
        'schemaVersion': document['schemaVersion'],
        'defaultPresetIds': document['defaultPresetIds'],
        'defaultPresetId': document['defaultPresetIds']['assessment'],
        'enabledCourseTypes': list(enabled_course_types()),
        'presets': presets,
        'courseCatalog': catalog,
    }


def _validated_course_preset_payload(
    data: Mapping[str, Any],
) -> tuple[str, str, str, List[Dict[str, Any]], bool]:
    raw_selections = data.get('courseSelections')
    raw_types = data.get('courseTypes')
    if raw_selections is None and raw_types is None and isinstance(data.get('courseIds'), list):
        # One-release request compatibility: resolve IDs immediately and only
        # use their canonical types before materializing exact item IDs.
        legacy_ids: List[int] = []
        for raw_id in data['courseIds']:
            if isinstance(raw_id, bool) or not str(raw_id).strip().isdigit() or int(raw_id) <= 0:
                raise ValueError('courseIds 只能包含正整数')
            course_id = int(raw_id)
            if course_id not in legacy_ids:
                legacy_ids.append(course_id)
        legacy_courses = Course.query.filter(Course.id.in_(legacy_ids)).all()
        by_id = {course.id: course for course in legacy_courses}
        raw_types = [
            TYPE_CN_TO_EN.get(by_id[course_id].course_type.name, '')
            for course_id in legacy_ids
            if course_id in by_id and by_id[course_id].course_type
        ]
        if len(raw_types) != len(legacy_ids):
            raise ValueError('课程不存在或未归类')
    if raw_selections is None:
        if not isinstance(raw_types, list):
            raise ValueError('courseSelections must be an array')
        course_types = JsonCoursePresetStore._normalize_course_types(raw_types)
    else:
        if not isinstance(raw_selections, list):
            raise ValueError('courseSelections must be an array')
        normalized = JsonCoursePresetStore._normalize_course_selections(raw_selections)
        course_types = [selection['courseType'] for selection in normalized]
    unknown = [course_type for course_type in course_types if course_type not in TYPE_EN_TO_CN]
    if unknown:
        raise ValueError(f'课型不存在: {", ".join(unknown)}')
    disabled = [
        course_type for course_type in course_types
        if not is_course_type_enabled(course_type)
    ]
    if disabled:
        raise ValueError(
            f'Demo 机仅允许模仿、配对和排序课程: {", ".join(disabled)}'
        )
    courses = Course.query.join(CourseType).filter(CourseType.name.in_([
        TYPE_EN_TO_CN[course_type] for course_type in course_types
    ])).all()
    by_type = {
        TYPE_CN_TO_EN.get(course.course_type.name, ''): course
        for course in courses
        if course.course_type
    }
    missing = [course_type for course_type in course_types if course_type not in by_type]
    if missing:
        raise ValueError(f'课型没有课程: {", ".join(missing)}')
    empty = [course_type for course_type in course_types if not by_type[course_type].items]
    if empty:
        raise ValueError(f'课型没有课点: {", ".join(empty)}')
    if raw_selections is None:
        normalized = [
            {
                'courseType': course_type,
                'itemIds': sorted(item.id for item in by_type[course_type].items),
            }
            for course_type in course_types
        ]
    invalid_items: List[str] = []
    for selection in normalized:
        course_type = selection['courseType']
        valid_ids = {item.id for item in by_type[course_type].items}
        for item_id in selection['itemIds']:
            if item_id not in valid_ids:
                invalid_items.append(f'{course_type}:{item_id}')
    if invalid_items:
        raise ValueError(f'课点不存在或不属于所选大类: {", ".join(invalid_items)}')
    return (
        JsonCoursePresetStore._normalize_mode(data.get('mode') or 'assessment'),
        str(data.get('name') or ''),
        str(data.get('description') or ''),
        normalized,
        data.get('isDefault') is True,
    )


def _course_preset_error_message(error: ValueError) -> str:
    messages = {
        'course_types_must_be_identifiers': 'courseTypes 只能包含规范课型标识',
        'course_types_required': '请至少选择一个课程大类',
        'course_selections_required': '请至少选择一个课程大类',
        'course_selection_items_required': '每个课程大类至少选择一个具体课点',
        'course_selections_must_be_an_array': 'courseSelections 必须是数组',
        'item_ids_must_be_an_array': 'itemIds 必须是数组',
        'item_ids_must_be_positive_integers': 'itemIds 只能包含正整数',
        'duplicate_course_selection_type': '同一个课程大类不能重复添加',
        'invalid_course_preset_mode': '预设用途只能是 assessment 或 intervention',
        'preset_name_required': '请填写预设名称',
        'preset_name_too_long': '预设名称不能超过 80 个字符',
        'preset_description_too_long': '预设说明不能超过 240 个字符',
        'preset_name_already_exists': '预设名称已存在',
    }
    return messages.get(str(error), str(error))


# ========== 教师端课程预设 ==========

@config_content_bp.route('/course-presets', methods=['GET'])
def list_course_presets():
    return jsonify(_course_preset_response())


@config_content_bp.route('/course-presets', methods=['POST'])
def create_course_preset():
    data = request.get_json(silent=True) or {}
    try:
        mode, name, description, course_selections, is_default = _validated_course_preset_payload(data)
        preset = _COURSE_PRESET_STORE.create(
            mode=mode,
            name=name,
            description=description,
            course_selections=course_selections,
            is_default=is_default,
        )
    except ValueError as exc:
        return jsonify({'success': False, 'error': _course_preset_error_message(exc)}), 400
    response = _course_preset_response()
    response['preset'] = next(item for item in response['presets'] if item['id'] == preset['id'])
    return jsonify(response), 201


@config_content_bp.route('/course-presets/<preset_id>', methods=['PUT'])
def update_course_preset(preset_id: str):
    data = request.get_json(silent=True) or {}
    try:
        mode, name, description, course_selections, is_default = _validated_course_preset_payload(data)
        preset = _COURSE_PRESET_STORE.update(
            preset_id,
            mode=mode,
            name=name,
            description=description,
            course_selections=course_selections,
            is_default=is_default,
        )
    except KeyError:
        return jsonify({'success': False, 'error': '课程预设不存在'}), 404
    except ValueError as exc:
        return jsonify({'success': False, 'error': _course_preset_error_message(exc)}), 400
    response = _course_preset_response()
    response['preset'] = next(item for item in response['presets'] if item['id'] == preset['id'])
    return jsonify(response)


@config_content_bp.route('/course-presets/<preset_id>', methods=['DELETE'])
def delete_course_preset(preset_id: str):
    try:
        _COURSE_PRESET_STORE.delete(preset_id)
    except KeyError:
        return jsonify({'success': False, 'error': '课程预设不存在'}), 404
    return jsonify(_course_preset_response())


# ========== 课型（只读） ==========

@config_content_bp.route('/course-types', methods=['GET'])
def list_course_types():
    types = CourseType.query.order_by(CourseType.id).all()
    return jsonify({
        'success': True,
        'types': [
            {
                'id': t.id,
                'name': t.name,
                'type': TYPE_CN_TO_EN.get(t.name, t.name),
            }
            for t in types
            if is_course_type_enabled(TYPE_CN_TO_EN.get(t.name, t.name))
        ],
    })


# ========== 课程 ==========

@config_content_bp.route('/courses', methods=['GET'])
def list_courses():
    type_filter = request.args.get('type')  # 英文或中文
    q = Course.query
    if type_filter:
        cn = TYPE_EN_TO_CN.get(type_filter, type_filter)
        ct = CourseType.query.filter_by(name=cn).first()
        if ct:
            q = q.filter_by(course_type_id=ct.id)
        else:
            return jsonify({'success': True, 'courses': []})
    mapped = _course_ids_with_mapping(_load_course_map())
    courses = q.order_by(Course.id).all()
    course_payloads = filter_course_payloads(
        [_course_admin_dict(course, mapped) for course in courses]
    )
    return jsonify({
        'success': True,
        'courses': course_payloads,
    })


@config_content_bp.route('/courses', methods=['POST'])
def create_course():
    data = request.get_json() or {}
    type_id = data.get('courseTypeId') or data.get('course_type_id')
    type_en = data.get('type')
    if not type_id and type_en:
        cn = TYPE_EN_TO_CN.get(type_en, type_en)
        ct = CourseType.query.filter_by(name=cn).first()
        if not ct:
            return jsonify({'success': False, 'error': f'未知课型: {type_en}'}), 400
        type_id = ct.id
    if not type_id:
        return jsonify({'success': False, 'error': 'courseTypeId or type required'}), 400
    ct = db.session.get(CourseType, int(type_id))
    if not ct:
        return jsonify({'success': False, 'error': '课型不存在'}), 404
    resolved_type = TYPE_CN_TO_EN.get(ct.name, ct.name)
    if not is_course_type_enabled(resolved_type):
        return jsonify({
            'success': False,
            'error': 'Demo 机仅允许创建模仿、配对和排序课程',
        }), 400
    existing = Course.query.filter_by(course_type_id=int(type_id)).first()
    if existing is not None:
        return jsonify({
            'success': False,
            'error': f'“{ct.name}”大类已存在，请在该大类中添加课点',
            'courseId': existing.id,
        }), 409
    course = Course(
        course_type_id=int(type_id),
        title=ct.name,
        icon=data.get('icon'),
        question_audio=data.get('questionAudio') or data.get('question'),
        praise_audio=data.get('praiseAudio') or data.get('praise'),
        entry_file=data.get('entryFile') or data.get('file'),
    )
    db.session.add(course)
    db.session.commit()
    return jsonify({'success': True, 'course': _course_admin_dict(course, set())}), 201


@config_content_bp.route('/courses/<int:course_id>', methods=['GET'])
def get_course(course_id: int):
    course = Course.query.get(course_id)
    if not course or not is_course_type_enabled(course.to_dict().get('type')):
        return jsonify({'success': False, 'error': '课程不存在'}), 404
    mapped = _course_ids_with_mapping(_load_course_map())
    data = _course_admin_dict(course, mapped)
    data['items'] = [_item_admin_dict(it) for it in course.items]
    return jsonify({'success': True, 'course': data})


@config_content_bp.route('/courses/<int:course_id>', methods=['PATCH'])
def patch_course(course_id: int):
    course = Course.query.get(course_id)
    if not course or not is_course_type_enabled(course.to_dict().get('type')):
        return jsonify({'success': False, 'error': '课程不存在'}), 404
    data = request.get_json() or {}
    # 一个课型只有一个课程大类，显示名称由 CourseType 唯一决定。
    course.title = course.course_type.name if course.course_type else course.title
    if 'icon' in data:
        course.icon = data['icon']
    if 'questionAudio' in data or 'question' in data:
        course.question_audio = data.get('questionAudio', data.get('question'))
    if 'praiseAudio' in data or 'praise' in data:
        course.praise_audio = data.get('praiseAudio', data.get('praise'))
    if 'entryFile' in data or 'file' in data:
        course.entry_file = data.get('entryFile', data.get('file'))
    # 课型与大类名称只读；课点内容在大类内部维护。
    db.session.commit()
    mapped = _course_ids_with_mapping(_load_course_map())
    return jsonify({'success': True, 'course': _course_admin_dict(course, mapped)})


@config_content_bp.route('/courses/<int:course_id>', methods=['DELETE'])
def delete_course(course_id: int):
    course = Course.query.get(course_id)
    if not course or not is_course_type_enabled(course.to_dict().get('type')):
        return jsonify({'success': False, 'error': '课程不存在'}), 404
    force = request.args.get('force', '').lower() in ('1', 'true', 'yes')
    refs = _course_map_refs_for_course(course_id)
    if refs and not force:
        return jsonify({
            'success': False,
            'error': f'课程仍被 course_map 引用（{len(refs)} 处）',
            'referencedBy': refs,
            'hint': '加 ?force=1 强制删除',
        }), 409
    db.session.delete(course)
    db.session.commit()
    return jsonify({'success': True, 'deleted': course_id})


@config_content_bp.route('/courses/<int:course_id>/items', methods=['GET'])
def list_items(course_id: int):
    course = Course.query.get(course_id)
    if not course or not is_course_type_enabled(course.to_dict().get('type')):
        return jsonify({'success': False, 'error': '课程不存在'}), 404
    return jsonify({
        'success': True,
        'items': [_item_admin_dict(it) for it in course.items],
    })


@config_content_bp.route('/courses/<int:course_id>/items', methods=['POST'])
def create_item(course_id: int):
    course = Course.query.get(course_id)
    if not course or not is_course_type_enabled(course.to_dict().get('type')):
        return jsonify({'success': False, 'error': '课程不存在'}), 404
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'name required'}), 400
    item_type = data.get('type') or 'image'
    if item_type not in ('image', 'interactive'):
        return jsonify({'success': False, 'error': 'type must be image|interactive'}), 400
    config_val = data.get('config')
    if isinstance(config_val, dict):
        config_val = json.dumps(config_val, ensure_ascii=False)
    item = CourseItem(
        course_id=course_id,
        name=name,
        icon=data.get('icon'),
        type=item_type,
        media_file=data.get('mediaFile') or data.get('file'),
        hint_audio=data.get('hintAudio') or data.get('hint'),
        difficulty=data.get('difficulty'),
        config=config_val,
        speech_target=(data.get('speechTarget') or data.get('speech_target') or None),
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({'success': True, 'item': _item_admin_dict(item)}), 201


@config_content_bp.route('/items/<int:item_id>', methods=['PATCH'])
def patch_item(item_id: int):
    item = CourseItem.query.get(item_id)
    if not item or not is_course_type_enabled(item.course.to_dict().get('type')):
        return jsonify({'success': False, 'error': '课点不存在'}), 404
    data = request.get_json() or {}
    if 'name' in data and data['name'] is not None:
        item.name = str(data['name']).strip() or item.name
    if 'type' in data and data['type'] in ('image', 'interactive'):
        item.type = data['type']
    if 'icon' in data:
        item.icon = data['icon']
    if 'mediaFile' in data or 'file' in data:
        item.media_file = data.get('mediaFile', data.get('file'))
    if 'hintAudio' in data or 'hint' in data:
        item.hint_audio = data.get('hintAudio', data.get('hint'))
    if 'difficulty' in data:
        item.difficulty = data['difficulty']
    if 'speechTarget' in data or 'speech_target' in data:
        val = data.get('speechTarget', data.get('speech_target'))
        item.speech_target = (val or None) if val is not None else None
        if val == '':
            item.speech_target = None
    if 'config' in data:
        cfg = data['config']
        if isinstance(cfg, dict):
            item.config = json.dumps(cfg, ensure_ascii=False)
        elif cfg is None or cfg == '':
            item.config = None
        else:
            item.config = str(cfg)
    db.session.commit()
    return jsonify({'success': True, 'item': _item_admin_dict(item)})


@config_content_bp.route('/items/<int:item_id>', methods=['DELETE'])
def delete_item(item_id: int):
    item = CourseItem.query.get(item_id)
    if not item or not is_course_type_enabled(item.course.to_dict().get('type')):
        return jsonify({'success': False, 'error': '课点不存在'}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({'success': True, 'deleted': item_id})


# ========== 媒资 ==========

@config_content_bp.route('/media', methods=['GET'])
def list_media():
    root = request.args.get('root', '').strip().replace('\\', '/')
    try:
        if not root:
            # 顶层分类
            entries = []
            if RESOURCES_ROOT.is_dir():
                for name in sorted(os.listdir(RESOURCES_ROOT)):
                    p = RESOURCES_ROOT / name
                    if name.startswith('.'):
                        continue
                    if p.is_dir():
                        entries.append({
                            'name': name,
                            'path': _to_static_rel(name, is_dir=True),
                            'kind': 'dir',
                            'sampleCount': sum(1 for _ in p.rglob('*') if _.is_file()),
                        })
            return jsonify({'success': True, 'root': '', 'entries': entries})

        target = _safe_rel_under_resources(root.rstrip('/'))
        if not target.exists():
            return jsonify({'success': False, 'error': '目录不存在'}), 404
        if not target.is_dir():
            return jsonify({'success': False, 'error': 'root 必须是目录'}), 400

        entries = []
        for name in sorted(os.listdir(target)):
            if name.startswith('.'):
                continue
            p = target / name
            rel = str(p.relative_to(RESOURCES_ROOT)).replace('\\', '/')
            if p.is_dir():
                files = [f for f in p.iterdir() if f.is_file()]
                entries.append({
                    'name': name,
                    'path': _to_static_rel(rel, is_dir=True),
                    'kind': 'dir',
                    'sampleCount': len(files),
                    'url': f'/static/resources/{rel}/',
                })
            else:
                ext = p.suffix.lower()
                entries.append({
                    'name': name,
                    'path': _to_static_rel(rel, is_dir=False),
                    'kind': 'file',
                    'ext': ext,
                    'size': p.stat().st_size,
                    'url': f'/static/resources/{rel}',
                })
        return jsonify({
            'success': True,
            'root': _to_static_rel(root.rstrip('/'), is_dir=True),
            'entries': entries,
        })
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error('list_media: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@config_content_bp.route('/media/upload', methods=['POST'])
def upload_media():
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'file required'}), 400
        f = request.files['file']
        if not f or not f.filename:
            return jsonify({'success': False, 'error': 'empty filename'}), 400
        dest_rel = (request.form.get('dir') or request.form.get('path') or 'images').strip()
        dest_rel = dest_rel.replace('\\', '/').lstrip('/')
        if dest_rel.startswith('resources/'):
            dest_rel = dest_rel[len('resources/'):]
        name = os.path.basename(f.filename)
        if not re.match(r'^[A-Za-z0-9_\-\.\u4e00-\u9fff]+$', name):
            # 放宽：去掉危险字符
            name = re.sub(r'[^\w\-\.\u4e00-\u9fff]', '_', name)
        ext = Path(name).suffix.lower()
        if ext not in ALLOWED_MEDIA_EXT:
            return jsonify({'success': False, 'error': f'不允许的扩展名: {ext}'}), 400
        dest_dir = _safe_rel_under_resources(dest_rel.rstrip('/'))
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / name
        if dest.exists():
            return jsonify({'success': False, 'error': f'文件已存在: {name}'}), 409
        f.save(str(dest))
        rel = str(dest.relative_to(RESOURCES_ROOT)).replace('\\', '/')
        path = _to_static_rel(rel, is_dir=False)
        return jsonify({
            'success': True,
            'path': path,
            'url': f'/static/{path}' if not path.startswith('static/') else f'/{path}',
            'name': name,
        }), 201
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error('upload_media: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@config_content_bp.route('/media', methods=['DELETE'])
def delete_media():
    data = request.get_json(silent=True) or {}
    path = data.get('path') or request.args.get('path')
    force = bool(data.get('force')) or request.args.get('force', '').lower() in ('1', 'true', 'yes')
    if not path:
        return jsonify({'success': False, 'error': 'path required'}), 400
    try:
        is_dir = path.endswith('/')
        target = _safe_rel_under_resources(path.rstrip('/'))
        if not target.exists():
            return jsonify({'success': False, 'error': '不存在'}), 404
        stored = _to_static_rel(
            str(target.relative_to(RESOURCES_ROOT)).replace('\\', '/'),
            is_dir=is_dir or target.is_dir(),
        )
        refs = _find_media_refs(stored)
        # 也扫不带 resources/ 的旧路径
        if stored.startswith('resources/'):
            refs += _find_media_refs(stored[len('resources/'):])
        refs = list(dict.fromkeys(refs))
        if refs and not force:
            return jsonify({
                'success': False,
                'error': f'仍被引用（{len(refs)} 处）',
                'referencedBy': refs,
                'hint': '传 force=true 强制删除',
            }), 409
        if target.is_dir():
            # 仅允许空目录或 force
            children = list(target.iterdir())
            if children and not force:
                return jsonify({
                    'success': False,
                    'error': '目录非空',
                    'hint': '传 force=true 递归删除',
                }), 409
            if force:
                import shutil
                shutil.rmtree(target)
            else:
                target.rmdir()
        else:
            target.unlink()
        return jsonify({'success': True, 'deleted': stored})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error('delete_media: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== Demo 课型实时话术 ==========

@config_content_bp.route('/phrases', methods=['GET'])
def get_dialogue_phrases():
    """实时 TTS 话术库及各课型当前启用集。"""
    from app.audio.manifest_io import ORDERING_QUESTION_SLOTS
    from app.dialogue.phrase_library import get_slot
    from app.dialogue.phrases import base_lines_for

    course_types = []
    global_slots = []
    for intent, slot_label in (
        ('attention', '吸引 · 重新集中注意'),
        ('reward', '夸奖 · 注意力回归'),
    ):
        slot = get_slot(base_lines_for(intent, 'global'), intent, 'global')
        slot['label'] = slot_label
        global_slots.append(slot)
    course_types.append({
        'type': 'global',
        'label': '全局注意力互动',
        'courses': [],
        'courseCount': 0,
        'slots': global_slots,
        'globalInteraction': True,
    })
    for type_key, label in TYPE_EN_TO_CN.items():
        if not is_course_type_enabled(type_key):
            continue
        db_type = CourseType.query.filter_by(name=label).first()
        linked_courses = []
        if db_type:
            linked_courses = [
                {'id': course.id, 'title': course.title}
                for course in Course.query.filter_by(course_type_id=db_type.id)
                .order_by(Course.id)
                .all()
            ]
        slots = []
        for intent in ('question', 'hint', 'praise'):
            slots.append(get_slot(base_lines_for(intent, type_key), intent, type_key))
        if type_key == 'social':
            for intent, slot_label in (
                ('social_greeting_intro', '打招呼 · 自我介绍'),
                ('social_greeting_play', '打招呼 · 邀请玩耍'),
                ('social_farewell_bye', '再见 · 主动告别'),
                ('social_farewell_reply', '再见 · 回应儿童'),
            ):
                slot = get_slot(base_lines_for(intent, type_key), intent, type_key)
                slot['label'] = slot_label
                slots.append(slot)
        if type_key == 'ordering':
            for _audio_key, slot_label, category, rule in ORDERING_QUESTION_SLOTS:
                variant = f'{category}_{rule}'
                slot = get_slot(base_lines_for('question', variant), 'question', variant)
                slot['label'] = f'提问 · {slot_label}'
                slots.append(slot)
        course_types.append({
            'type': type_key,
            'label': label,
            'courses': linked_courses,
            'courseCount': len(linked_courses),
            'slots': slots,
        })
    return jsonify({
        'success': True,
        'mode': 'browser',
        'courseTypes': course_types,
    })


@config_content_bp.route('/phrases/<intent>/<course_type>', methods=['PUT'])
def put_dialogue_phrase_selection(intent: str, course_type: str):
    from app.dialogue.phrase_library import set_enabled

    data = request.get_json(silent=True) or {}
    try:
        demo_course_type = _demo_phrase_scope(intent, course_type)
        slot = set_enabled(intent, demo_course_type, data.get('selected'))
        return jsonify({'success': True, 'slot': slot})
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        logger.error('put_dialogue_phrase_selection: %s', exc, exc_info=True)
        return jsonify({'success': False, 'error': str(exc)}), 500


@config_content_bp.route('/phrases/<intent>/<course_type>/custom', methods=['POST'])
def post_dialogue_custom_phrase(intent: str, course_type: str):
    from app.dialogue.phrase_library import add_custom

    data = request.get_json(silent=True) or {}
    try:
        demo_course_type = _demo_phrase_scope(intent, course_type)
        slot = add_custom(intent, demo_course_type, data.get('text'))
        return jsonify({'success': True, 'slot': slot}), 201
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        logger.error('post_dialogue_custom_phrase: %s', exc, exc_info=True)
        return jsonify({'success': False, 'error': str(exc)}), 500

@config_content_bp.route('/audio/course-defaults/<course_type>', methods=['GET'])
def get_audio_course_defaults(course_type: str):
    from app.audio.manifest_io import get_course_type_defaults
    try:
        demo_course_type = canonical_course_type(course_type)
        if not is_course_type_enabled(demo_course_type):
            raise ValueError('Demo 版仅允许模仿、配对和排序课程语音')
        return jsonify({'success': True, 'defaults': get_course_type_defaults(demo_course_type)})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error('get_audio_course_defaults: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@config_content_bp.route('/audio/course-defaults/<course_type>', methods=['PUT'])
def put_audio_course_defaults(course_type: str):
    """body: { question?, praise?, hint?, question_size_bigger?, ... }"""
    from app.audio.manifest_io import ORDERING_QUESTION_KEYS, set_course_type_audio
    data = request.get_json(silent=True) or {}
    updated = []
    keys = ('question', 'praise', 'hint', *ORDERING_QUESTION_KEYS)
    try:
        demo_course_type = canonical_course_type(course_type)
        if not is_course_type_enabled(demo_course_type):
            raise ValueError('Demo 版仅允许模仿、配对和排序课程语音')
        for key in keys:
            if key in data and data[key]:
                updated.append(set_course_type_audio(demo_course_type, key, str(data[key])))
        if not updated:
            return jsonify({'success': False, 'error': 'no audio fields to update'}), 400
        return jsonify({'success': True, 'updated': updated})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error('put_audio_course_defaults: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@config_content_bp.route('/audio/entries/<entry_id>', methods=['GET'])
def get_audio_entry(entry_id: str):
    return jsonify({
        'success': False,
        'error': 'Demo 版使用浏览器实时话术，不开放旧音频条目配置',
        'code': 'demo_capability_disabled',
    }), 410


@config_content_bp.route('/audio/entries/<entry_id>', methods=['PUT'])
def put_audio_entry(entry_id: str):
    return jsonify({
        'success': False,
        'error': 'Demo 版使用浏览器实时话术，不开放旧音频条目配置',
        'code': 'demo_capability_disabled',
    }), 410


# ========== 工作台汇总 ==========

@config_content_bp.route('/content/summary', methods=['GET'])
def content_summary():
    from app.audio.manifest_io import list_types_missing_question

    courses = [
        course for course in Course.query.all()
        if is_course_type_enabled(course.to_dict().get('type'))
    ]
    active_course_ids = {course.id for course in courses}
    items = [
        item for item in CourseItem.query.all()
        if item.course_id in active_course_ids
    ]
    mapped = _course_ids_with_mapping(_load_course_map())
    missing_types = [
        course_type for course_type in list_types_missing_question()
        if is_course_type_enabled(course_type)
    ]
    # 兼容旧字段：列出属于缺提问课型的课程 id
    missing_question_ids = []
    for c in courses:
        t = TYPE_CN_TO_EN.get(c.course_type.name if c.course_type else '', '')
        if t in missing_types:
            missing_question_ids.append(c.id)
    missing_media_items = [
        {'itemId': it.id, 'courseId': it.course_id, 'name': it.name}
        for it in items if not (it.media_file or '').strip()
    ]
    unmapped_courses = [c.id for c in courses if c.id not in mapped]
    return jsonify({
        'success': True,
        'summary': {
            'courseCount': len(courses),
            'itemCount': len(items),
            'enabledCourseTypes': list(enabled_course_types()),
            'emotionCount': 0,
            'motionCount': 0,
            'robotMotionEnabled': False,
            'robotExpressionEnabled': False,
            'missingQuestionAudio': len(missing_types),
            'missingQuestionAudioTypes': missing_types,
            'missingQuestionAudioCourseIds': missing_question_ids,
            'missingItemMedia': len(missing_media_items),
            'missingItemMediaItems': missing_media_items[:50],
            'unmappedCourses': len(unmapped_courses),
            'unmappedCourseIds': unmapped_courses,
        },
    })
