"""互动页（配对/排序）当前题面上下文，供 LLM 对话合并使用。"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any, Dict, Optional, Union

_lock = Lock()
_store: Dict[str, Dict[str, Any]] = {}

# 显式传 null 时清除（排序无上面目标图）
_CLEAR_WHEN_NULL = frozenset(
    {
        "target",
        "targetText",
        "targetDescription",
        "correctLabel",
        "correctPosition",
        "correctOptionLabel",
        "correctOptionPosition",
        "objectName",
        "rule",
        "ruleText",
        "category",
        "speechTarget",
        "name",
        "label",
        "itemLabel",
        "options",
        "optionsLeftToRight",
        "prompt",
        "wrongAttempts",
    }
)

# 课型切换时丢掉上一课残留字段
_COURSE_SCOPED_KEYS = frozenset(
    {
        "target",
        "targetText",
        "targetDescription",
        "options",
        "optionsLeftToRight",
        "prompt",
        "rule",
        "ruleText",
        "category",
        "objectName",
        "correctLabel",
        "correctPosition",
        "correctOptionLabel",
        "correctOptionPosition",
        "wrongAttempts",
        "questionIndex",
        "totalQuestions",
        "questionId",
        "question_id",
        "itemId",
        "item_id",
        "speechTarget",
        "name",
        "label",
        "itemLabel",
    }
)


def set_interactive_page_context(session_id: Optional[str], context: Dict[str, Any]) -> None:
    sid = str(session_id or "").strip()
    if not sid or not isinstance(context, dict):
        return
    clears = {k for k, v in context.items() if v is None and k in _CLEAR_WHEN_NULL}
    # 空列表/空串也清掉互动字段（命名覆盖时）
    for k, v in context.items():
        if k not in _CLEAR_WHEN_NULL:
            continue
        if isinstance(v, str) and not v.strip():
            clears.add(k)
        elif isinstance(v, (list, dict)) and not v:
            clears.add(k)
    payload = {
        k: v
        for k, v in context.items()
        if v is not None and not (isinstance(v, (list, dict)) and not v)
        and not (isinstance(v, str) and not v.strip() and k in _CLEAR_WHEN_NULL)
    }
    payload["updatedAt"] = time.time()
    with _lock:
        prev = _store.get(sid) or {}
        merged = dict(prev)
        prev_ct = str(prev.get("courseType") or prev.get("course_type") or "").strip().lower()
        new_ct = str(
            payload.get("courseType") or payload.get("course_type") or prev_ct
        ).strip().lower()
        if new_ct and prev_ct and new_ct != prev_ct:
            for key in _COURSE_SCOPED_KEYS:
                merged.pop(key, None)
        # 题目/条目推进时丢掉上一题残留选项/目标，避免对话串题
        prev_q = prev.get("questionIndex")
        new_q = payload.get("questionIndex")
        prev_qid = prev.get("questionId") or prev.get("question_id")
        new_qid = payload.get("questionId") or payload.get("question_id")
        prev_item = prev.get("itemId") or prev.get("item_id")
        new_item = payload.get("itemId") or payload.get("item_id")
        question_changed = (
            (new_q is not None and prev_q is not None and new_q != prev_q)
            or (
                new_qid is not None
                and prev_qid is not None
                and str(new_qid) != str(prev_qid)
            )
            or (
                new_item is not None
                and prev_item is not None
                and str(new_item) != str(prev_item)
            )
        )
        if question_changed:
            for key in _COURSE_SCOPED_KEYS:
                merged.pop(key, None)
        # 排序课强制去掉上面目标，避免配对残留
        if new_ct in ("ordering", "sequencing"):
            clears.update({"target", "targetText", "targetDescription"})
        for key in clears:
            merged.pop(key, None)
        merged.update(payload)
        _store[sid] = merged


def get_interactive_page_context(session_id: Optional[str]) -> Dict[str, Any]:
    sid = str(session_id or "").strip()
    if not sid:
        return {}
    with _lock:
        data = _store.get(sid) or {}
        return dict(data)


def clear_interactive_page_context(session_id: Optional[str]) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    with _lock:
        _store.pop(sid, None)


def merge_page_context(
    client_or_session: Union[Optional[Dict[str, Any]], Optional[str]] = None,
    session_or_client: Union[Optional[str], Optional[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    服务端缓存 + 儿童端上报；客户端非空字段覆盖缓存。

    兼容两种调用：
    - merge_page_context(client_ctx, session_id)  # dialogue.sockets
    - merge_page_context(session_id, client_ctx)
    """
    client: Dict[str, Any] = {}
    session_id: Optional[str] = None

    if isinstance(client_or_session, dict):
        client = client_or_session
        session_id = str(session_or_client) if session_or_client else None
    elif isinstance(session_or_client, dict):
        client = session_or_client
        session_id = str(client_or_session) if client_or_session else None
    elif isinstance(client_or_session, str) and not session_or_client:
        session_id = client_or_session
    else:
        session_id = str(client_or_session) if client_or_session else None
        if isinstance(session_or_client, dict):
            client = session_or_client

    merged = get_interactive_page_context(session_id)
    client_ct = str(client.get("courseType") or client.get("course_type") or "").strip().lower()
    merged_ct = str(merged.get("courseType") or merged.get("course_type") or "").strip().lower()
    if client_ct and merged_ct and client_ct != merged_ct:
        for key in _COURSE_SCOPED_KEYS:
            merged.pop(key, None)
    client_q = client.get("questionIndex")
    merged_q = merged.get("questionIndex")
    client_qid = client.get("questionId") or client.get("question_id")
    merged_qid = merged.get("questionId") or merged.get("question_id")
    client_item = client.get("itemId") or client.get("item_id")
    merged_item = merged.get("itemId") or merged.get("item_id")
    if (
        (client_q is not None and merged_q is not None and client_q != merged_q)
        or (
            client_qid is not None
            and merged_qid is not None
            and str(client_qid) != str(merged_qid)
        )
        or (
            client_item is not None
            and merged_item is not None
            and str(client_item) != str(merged_item)
        )
    ):
        for key in _COURSE_SCOPED_KEYS:
            merged.pop(key, None)
    if client_ct in ("ordering", "sequencing"):
        merged.pop("target", None)
        merged.pop("targetText", None)

    for key, value in (client or {}).items():
        if value is None:
            if key in _CLEAR_WHEN_NULL:
                merged.pop(key, None)
            continue
        if isinstance(value, str) and not value.strip():
            if key in _CLEAR_WHEN_NULL:
                merged.pop(key, None)
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        merged[key] = value
    return merged
