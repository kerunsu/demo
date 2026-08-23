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
from typing import Any, Dict, List, Optional, Set

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from app.config import Config
from app.robot.config import COURSE_MAP_FILE
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
    return jsonify({
        'success': True,
        'courses': [_course_admin_dict(c, mapped) for c in courses],
    })


@config_content_bp.route('/courses', methods=['POST'])
def create_course():
    data = request.get_json() or {}
    title = (data.get('title') or '').strip()
    if not title:
        return jsonify({'success': False, 'error': 'title required'}), 400
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
    ct = CourseType.query.get(type_id)
    if not ct:
        return jsonify({'success': False, 'error': '课型不存在'}), 404

    course = Course(
        course_type_id=int(type_id),
        title=title,
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
    if not course:
        return jsonify({'success': False, 'error': '课程不存在'}), 404
    mapped = _course_ids_with_mapping(_load_course_map())
    data = _course_admin_dict(course, mapped)
    data['items'] = [_item_admin_dict(it) for it in course.items]
    return jsonify({'success': True, 'course': data})


@config_content_bp.route('/courses/<int:course_id>', methods=['PATCH'])
def patch_course(course_id: int):
    course = Course.query.get(course_id)
    if not course:
        return jsonify({'success': False, 'error': '课程不存在'}), 404
    data = request.get_json() or {}
    if 'title' in data and data['title'] is not None:
        course.title = str(data['title']).strip() or course.title
    if 'icon' in data:
        course.icon = data['icon']
    if 'questionAudio' in data or 'question' in data:
        course.question_audio = data.get('questionAudio', data.get('question'))
    if 'praiseAudio' in data or 'praise' in data:
        course.praise_audio = data.get('praiseAudio', data.get('praise'))
    if 'entryFile' in data or 'file' in data:
        course.entry_file = data.get('entryFile', data.get('file'))
    # 课型只读：忽略 courseTypeId 变更（v1）
    db.session.commit()
    mapped = _course_ids_with_mapping(_load_course_map())
    return jsonify({'success': True, 'course': _course_admin_dict(course, mapped)})


@config_content_bp.route('/courses/<int:course_id>', methods=['DELETE'])
def delete_course(course_id: int):
    course = Course.query.get(course_id)
    if not course:
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
    if not course:
        return jsonify({'success': False, 'error': '课程不存在'}), 404
    return jsonify({
        'success': True,
        'items': [_item_admin_dict(it) for it in course.items],
    })


@config_content_bp.route('/courses/<int:course_id>/items', methods=['POST'])
def create_item(course_id: int):
    course = Course.query.get(course_id)
    if not course:
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
    if not item:
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
    if not item:
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


# ========== 课型 / 社交语音（audio_manifest） ==========

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
        slot = set_enabled(intent, course_type, data.get('selected'))
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
        slot = add_custom(intent, course_type, data.get('text'))
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
        return jsonify({'success': True, 'defaults': get_course_type_defaults(course_type)})
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
        for key in keys:
            if key in data and data[key]:
                updated.append(set_course_type_audio(course_type, key, str(data[key])))
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
    from app.audio.manifest_io import get_entry_display_path
    try:
        eid, path = get_entry_display_path(entry_id)
        return jsonify({'success': True, 'entryId': eid, 'filePath': path})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@config_content_bp.route('/audio/entries/<entry_id>', methods=['PUT'])
def put_audio_entry(entry_id: str):
    """社交四键等：body { filePath: "resources/audios/..." }"""
    from app.audio.manifest_io import SOCIAL_ENTRY_KEYS, set_entry_single_file, set_social_button_audio
    data = request.get_json(silent=True) or {}
    file_path = data.get('filePath') or data.get('path') or ''
    try:
        if entry_id in SOCIAL_ENTRY_KEYS:
            result = set_social_button_audio(entry_id, str(file_path))
        else:
            result = set_entry_single_file(entry_id, str(file_path))
        return jsonify({'success': True, **result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error('put_audio_entry: %s', e, exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 工作台汇总 ==========

@config_content_bp.route('/content/summary', methods=['GET'])
def content_summary():
    from app.robot.emotion_assets import list_emotion_files
    from app.robot import get_robot_service
    from app.audio.manifest_io import list_types_missing_question

    courses = Course.query.all()
    items = CourseItem.query.all()
    mapped = _course_ids_with_mapping(_load_course_map())
    missing_types = list_types_missing_question()
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
    motion_count = 0
    try:
        motion_count = len(get_robot_service().get_motion_list() or [])
    except Exception as e:
        logger.warning('summary motions: %s', e)

    return jsonify({
        'success': True,
        'summary': {
            'courseCount': len(courses),
            'itemCount': len(items),
            'emotionCount': len(list_emotion_files()),
            'motionCount': motion_count,
            'missingQuestionAudio': len(missing_types),
            'missingQuestionAudioTypes': missing_types,
            'missingQuestionAudioCourseIds': missing_question_ids,
            'missingItemMedia': len(missing_media_items),
            'missingItemMediaItems': missing_media_items[:50],
            'unmappedCourses': len(unmapped_courses),
            'unmappedCourseIds': unmapped_courses,
        },
    })
