"""机器人课程行为事件的唯一归属规则。

配置中心、REST 写入和运行时触发都必须使用这里的规则，避免社交事件
泄漏到排序、命名等普通课程。
"""

from __future__ import annotations

from typing import Iterable, Optional


ENGAGEMENT_AUX_TYPES = ("attention", "reward")
STANDARD_AUX_TYPES = ("praise", "question", "hint", "silent") + ENGAGEMENT_AUX_TYPES
LIFECYCLE_AUX_TYPES = ("silent",)
SOCIAL_GREETING_AUX_TYPES = (
    "social_greeting_intro",
    "social_greeting_play",
)
SOCIAL_FAREWELL_AUX_TYPES = (
    "social_farewell_bye",
    "social_farewell_reply",
)
SOCIAL_AUX_TYPES = SOCIAL_GREETING_AUX_TYPES + SOCIAL_FAREWELL_AUX_TYPES
ALL_AUX_TYPES = STANDARD_AUX_TYPES + SOCIAL_AUX_TYPES

_COURSE_TYPE_ALIASES = {
    "命名": "naming",
    "拟声": "onomatopoeia",
    "模仿": "mimic",
    "配对": "pairing",
    "排序": "ordering",
    "社交": "social",
    "matching": "pairing",
    "sequencing": "ordering",
}


def canonical_course_type(value: object) -> str:
    raw = str(value or "").strip().lower()
    return _COURSE_TYPE_ALIASES.get(raw, raw)


def allowed_aux_types(
    course_type: object,
    *,
    social_role: Optional[str] = None,
) -> tuple[str, ...]:
    """返回特定课程/课点真正可触发的行为槽。

    ``silent`` 不是社交话术，而是教师端首次进入/切换课点时发送的
    生命周期事件。所有课程都必须接受它，否则社交课会在真正的
    greeting/farewell 指令发出前就拒绝内容加载。表扬/提问/提示仍不得
    泄漏进社交课点。
    """
    if canonical_course_type(course_type) != "social":
        return STANDARD_AUX_TYPES
    role = str(social_role or "").strip().lower()
    if role == "greeting":
        return LIFECYCLE_AUX_TYPES + ENGAGEMENT_AUX_TYPES + SOCIAL_GREETING_AUX_TYPES
    if role == "farewell":
        return LIFECYCLE_AUX_TYPES + ENGAGEMENT_AUX_TYPES + SOCIAL_FAREWELL_AUX_TYPES
    return LIFECYCLE_AUX_TYPES + ENGAGEMENT_AUX_TYPES + SOCIAL_AUX_TYPES


def is_aux_allowed(
    course_type: object,
    aux_type: object,
    *,
    social_role: Optional[str] = None,
) -> bool:
    return str(aux_type or "") in allowed_aux_types(
        course_type,
        social_role=social_role,
    )


def validate_aux_type(aux_type: object) -> str:
    value = str(aux_type or "").strip()
    if value not in ALL_AUX_TYPES:
        raise ValueError("invalid_behavior_event")
    return value


__all__ = [
    "ALL_AUX_TYPES",
    "ENGAGEMENT_AUX_TYPES",
    "LIFECYCLE_AUX_TYPES",
    "SOCIAL_AUX_TYPES",
    "SOCIAL_FAREWELL_AUX_TYPES",
    "SOCIAL_GREETING_AUX_TYPES",
    "STANDARD_AUX_TYPES",
    "allowed_aux_types",
    "canonical_course_type",
    "is_aux_allowed",
    "validate_aux_type",
]
