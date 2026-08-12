"""课型话术库：题开始提问 / 表扬 / 鼓励 / 提示 / 社交打招呼与再见。"""

from __future__ import annotations

import random
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import yaml

from app.config import BASE_DIR
from app.utils.logger import setup_logger

logger = setup_logger("dialogue.phrases")

_DEFAULT_PATH = BASE_DIR / "config" / "dialogue_phrases.yaml"
_lock = Lock()
_bank: Optional[Dict[str, Any]] = None
_recent: Dict[str, List[str]] = {}

# 排序 category+rule → question 话术键（对齐 DemoRobot ORDERING_RULES / sequencing）
ORDERING_RULE_PHRASE_KEYS: Dict[Tuple[str, str], str] = {
    ("size", "bigger"): "size_bigger",
    ("size", "smaller"): "size_smaller",
    ("length", "longer"): "length_longer",
    ("length", "shorter"): "length_shorter",
    ("height", "taller"): "height_taller",
    ("height", "shorter"): "height_shorter",
    ("count", "more"): "count_more",
    ("count", "less"): "count_less",
}

ORDERING_QUESTION_PHRASE_KEYS = frozenset(ORDERING_RULE_PHRASE_KEYS.values())

# 拟声提问：单字动物名加「小」更自然（猫→小猫）
_ONOMATOPOEIA_DIMINUTIVES: Dict[str, str] = {
    "猫": "小猫",
    "狗": "小狗",
    "鸟": "小鸟",
    "鸡": "小鸡",
    "鸭": "小鸭",
    "鹅": "小鹅",
    "羊": "小羊",
    "牛": "小牛",
    "猪": "小猪",
    "兔": "小兔",
    "马": "小马",
    "熊": "小熊",
    "虎": "小老虎",
    "狮": "小狮子",
    "猴": "小猴",
    "鼠": "小老鼠",
    "青蛙": "小青蛙",
    "老虎": "小老虎",
    "狮子": "小狮子",
    "老鼠": "小老鼠",
}
_ONOMATOPOEIA_NAME_SUFFIXES = ("的叫声", "叫声", "叫")
_ONOMATOPOEIA_QUESTION_FALLBACK = "听听，这是什么声音呀？"
_ONOMATOPOEIA_QUESTION_TEMPLATE = "{name}会怎么叫呀？"


def naturalize_onomatopoeia_name(raw: Optional[str]) -> str:
    """课点名 → 提问用称呼：去掉尾缀「叫」，可选加「小」。"""
    name = str(raw or "").strip()
    if not name:
        return ""
    for suffix in _ONOMATOPOEIA_NAME_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)].strip()
            break
    if not name:
        return ""
    return _ONOMATOPOEIA_DIMINUTIVES.get(name, name)


def fill_phrase_template(phrase: str, *, name: Optional[str] = None) -> Optional[str]:
    """填充 {name}；缺名且模板需要 name 时返回 None（调用方换句/兜底）。"""
    text = str(phrase or "").strip()
    if not text:
        return None
    if "{name}" not in text:
        return text
    display = naturalize_onomatopoeia_name(name)
    if not display:
        return None
    return text.replace("{name}", display)


def format_onomatopoeia_question(name: Optional[str] = None) -> str:
    """拟声提问：有名时从 yaml 模板池随机（避重），无名则无模板句 / 固定兜底。"""
    display = naturalize_onomatopoeia_name(name)
    lines = _lines_for("question", "onomatopoeia")
    if display:
        filled_pool: List[str] = []
        for line in lines:
            filled = fill_phrase_template(line, name=display)
            if filled:
                filled_pool.append(filled)
        if filled_pool:
            key = "question:onomatopoeia"
            recent = _recent.get(key) or []
            pool = [line for line in filled_pool if line not in recent] or filled_pool
            choice = random.choice(pool)
            _recent[key] = (recent + [choice])[-6:]
            return choice
        return _ONOMATOPOEIA_QUESTION_TEMPLATE.replace("{name}", display)
    for line in lines:
        if "{name}" not in line:
            return line
    return _ONOMATOPOEIA_QUESTION_FALLBACK


def resolve_item_display_name(
    *sources: Any,
    prefer_keys: Optional[Tuple[str, ...]] = None,
) -> str:
    """从 play_resource / page_context 等字典里取展示名（优先 name，再 speechTarget）。"""
    keys = prefer_keys or (
        "itemName",
        "item_name",
        "name",
        "label",
        "itemLabel",
        "speechTarget",
        "speech_target",
        "target",
        "targetText",
    )
    for src in sources:
        if isinstance(src, str) and src.strip():
            return src.strip()
        if not isinstance(src, dict):
            continue
        for key in keys:
            val = src.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
    return ""


def get_phrase_bank(force_reload: bool = False) -> Dict[str, Any]:
    global _bank
    with _lock:
        if _bank is not None and not force_reload:
            return _bank
        path = Path(_DEFAULT_PATH)
        if not path.exists():
            logger.warning("话术文件不存在: %s，使用内置兜底", path)
            _bank = {
                "question": {"default": ["看一看屏幕。"]},
                "praise": {"default": ["真棒！"]},
                "encourage": {"default": ["没关系，再试一次。"]},
                "hint": {"default": ["再看一看。"]},
                "social_greeting_intro": {"default": ["你好，我是麦麦。"]},
                "social_greeting_play": {"default": ["我们一起玩吧。"]},
                "social_farewell_bye": {"default": ["再见啦。"]},
                "social_farewell_reply": {"default": ["再见，下次见。"]},
            }
            return _bank
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        _bank = data if isinstance(data, dict) else {}
        logger.info("已加载对话话术: %s", path)
        return _bank


def ordering_phrase_key(category: Optional[str], rule: Optional[str]) -> Optional[str]:
    """category+rule → size_bigger 等话术键。"""
    cat = (category or "").strip().lower()
    rul = (rule or "").strip().lower()
    if not cat or not rul:
        return None
    return ORDERING_RULE_PHRASE_KEYS.get((cat, rul))


def normalize_ordering_question_key(audio_or_rule_key: Optional[str]) -> Optional[str]:
    """
    归一化排序提问键：
    question_size_bigger / size_bigger / ordering_size_bigger → size_bigger
    """
    raw = (audio_or_rule_key or "").strip().lower().replace("-", "_")
    if not raw:
        return None
    for prefix in ("question_", "ordering_", "sequencing_"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    if raw in ORDERING_QUESTION_PHRASE_KEYS:
        return raw
    # 兼容 DemoRobot 规则文案片段
    text_aliases = {
        "bigger": "size_bigger",
        "smaller": "size_smaller",
        "longer": "length_longer",
        "shorter_length": "length_shorter",
        "taller": "height_taller",
        "shorter_height": "height_shorter",
        "more": "count_more",
        "less": "count_less",
        "选更大的": "size_bigger",
        "选更小的": "size_smaller",
        "选更长的": "length_longer",
        "选更短的": "length_shorter",
        "选更高的": "height_taller",
        "选更矮的": "height_shorter",
        "选更多的": "count_more",
        "选更少的": "count_less",
    }
    return text_aliases.get(raw)


def base_lines_for(intent: str, course_type: Optional[str]) -> List[str]:
    """Return reviewed base lines without applying the Server selection overlay."""
    bank = get_phrase_bank()
    section = bank.get(intent) or {}
    if not isinstance(section, dict):
        return []
    course_key = (course_type or "").strip().lower()
    lines = section.get(course_key) if course_key else None
    if not lines:
        lines = section.get("default") or []
    if isinstance(lines, str):
        return [lines]
    return [str(x).strip() for x in lines if str(x).strip()]


def _lines_for(intent: str, course_type: Optional[str]) -> List[str]:
    course_key = (course_type or "").strip().lower()
    base = base_lines_for(intent, course_type)
    if not course_key:
        return base
    try:
        from app.dialogue.phrase_library import effective_lines

        return effective_lines(base, intent, course_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取实时话术选择失败，使用基础语料: %s", exc)
        return base


def pick_phrase(
    intent: str,
    course_type: Optional[str] = None,
    *,
    recent_key: Optional[str] = None,
    variant: Optional[str] = None,
    name: Optional[str] = None,
) -> str:
    """随机选取一句，尽量避开最近用过的。variant 优先（如排序 size_bigger）。
    name 用于填充拟声等模板句中的 {name}。
    """
    course_key = (course_type or "").strip().lower()
    # 拟声提问：按当前物品动态生成，不走随机池（避免抽到缺名模板）
    if intent == "question" and course_key == "onomatopoeia" and not (variant or "").strip():
        return format_onomatopoeia_question(name)

    preferred = (variant or "").strip().lower() or None
    lines: List[str] = []
    if preferred:
        lines = _lines_for(intent, preferred)
    if not lines:
        lines = _lines_for(intent, course_type)
    if not lines and course_key in ("ordering", "sequencing"):
        # 排序未知规则：用 ordering 兜底，勿落到 default 闲聊句
        lines = _lines_for(intent, "ordering")
    if not lines:
        lines = _lines_for(intent, None)
    if not lines:
        fallback = {
            "question": "看一看屏幕。",
            "praise": "真棒！",
            "encourage": "没关系，再试一次。",
            "hint": "再看一看。",
            "social_greeting_intro": "你好，我是麦麦。",
            "social_greeting_play": "我们一起玩吧。",
            "social_farewell_bye": "再见啦。",
            "social_farewell_reply": "再见，下次见。",
        }
        return fallback.get(intent, "我们继续吧。")

    key = recent_key or f"{intent}:{preferred or course_type or 'default'}"
    recent = _recent.get(key) or []
    # 有 name 时优先能填充的模板；无名时跳过需 {name} 的句子
    usable: List[str] = []
    for line in lines:
        filled = fill_phrase_template(line, name=name)
        if filled:
            usable.append(filled)
    if not usable:
        if intent == "question" and course_key == "onomatopoeia":
            return format_onomatopoeia_question(name)
        usable = [
            line
            for line in lines
            if "{name}" not in line
        ] or list(lines)

    pool = [line for line in usable if line not in recent] or usable
    choice = random.choice(pool)
    _recent[key] = (recent + [choice])[-6:]
    return choice
