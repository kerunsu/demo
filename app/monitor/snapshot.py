"""
MonitorSnapshot 聚合服务（阶段 D）

遵守连续录制方案 B：整场一个 mediaSessionId；
切题只反映在 course/question，不按多段 AVI 建模。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import time

from app.utils.logger import setup_logger

logger = setup_logger("monitor_snapshot")

POLL_INTERVAL_MS = 1000
RECENT_ATTENTION_SEC = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        s = str(ts).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _elapsed_sec(opened_at: Optional[str]) -> Optional[float]:
    started = _parse_iso(opened_at)
    if not started:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - started).total_seconds())


def _resolve_training_session_id(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return str(explicit).strip() or None

    # 1) 连续录制活跃会话（方案 B 首选）
    try:
        from app.services.recording_timeline import list_active_recording_sessions

        active_rs = list_active_recording_sessions()
        if active_rs:
            active_rs.sort(key=lambda r: r.recording_started_at or 0, reverse=True)
            tid = active_rs[0].training_session_id
            if tid:
                return tid
    except Exception as e:
        logger.debug("resolve via recording_timeline failed: %s", e)

    # 2) SessionManager 活跃 runtime（含 warmup）
    try:
        from app.session import get_session_manager

        sessions = get_session_manager().list_active_sessions()
        # 优先 continuous / 有 human_dir 的整场会话
        ranked = []
        for s in sessions:
            tid = getattr(s, "training_session_id", None)
            if not tid:
                continue
            meta = s.metadata or {}
            score = 0
            if meta.get("continuous_recording") or meta.get("recording_mode") == "continuous":
                score += 2
            if meta.get("human_dir_name"):
                score += 1
            if meta.get("warmup"):
                score += 1  # warmup 也算活跃
            ranked.append((score, s.started_at or s.created_at, tid))
        if ranked:
            ranked.sort(key=lambda x: (x[0], x[1] or datetime.min), reverse=True)
            return ranked[0][2]
    except Exception as e:
        logger.debug("resolve via session_manager failed: %s", e)

    # 3) BehaviorStore 按学生的 active 映射
    try:
        from app.behavior.store import get_behavior_store

        store = get_behavior_store()
        ids = store.list_active_training_ids()
        if ids:
            return ids[0]
    except Exception as e:
        logger.debug("resolve via behavior_store failed: %s", e)

    return None


def _lookup_course_title(course_id: Optional[int]) -> Optional[str]:
    if course_id is None:
        return None
    try:
        from database.models import Course

        course = Course.query.get(int(course_id))
        if course:
            return course.title
    except Exception:
        pass
    return None


def _session_status(training, runtime_session, recording) -> str:
    if training and training.status == "finalized":
        return "ended"
    meta = {}
    if runtime_session:
        meta = runtime_session.metadata or {}
    if meta.get("warmup") or (recording and recording.status == "warmup"):
        # 尚无非 aux 课点
        if not training or not training.current_question_id:
            return "warmup"
        # prepare 时可能已有 warmup question_id
        if meta.get("warmup"):
            return "warmup"
    if training and training.status == "active":
        return "active"
    if recording and recording.status in ("recording", "active", "warmup"):
        return "active" if recording.status != "warmup" else "warmup"
    return "active" if training else "ended"


def _build_attention_block(store, training_session_id: str, question_id: Optional[str]) -> Dict[str, Any]:
    from app.behavior.camera_config import should_prefer_browser_for_report
    from app.behavior.emotion_scoring import select_attention_observations

    all_obs = store.list_attention(training_session_id)
    prefer_browser = should_prefer_browser_for_report()
    selected = select_attention_observations(all_obs, prefer_browser)

    q_obs = [o for o in selected if not question_id or o.question_id == question_id]
    # 当前分：优先本题最近一条；否则全局最近
    current_pool = q_obs or selected
    latest = current_pool[-1] if current_pool else None

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=RECENT_ATTENTION_SEC)
    recent = []
    for o in selected:
        t = _parse_iso(o.timestamp)
        if t is None:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t >= cutoff:
            dq = str(o.data_quality or "MISSING").upper()
            score_val = None if dq == "MISSING" else round(float(o.score), 1)
            recent.append(
                {
                    "t": o.timestamp,
                    "score": score_val,
                    "quality": o.data_quality or "MISSING",
                }
            )
    # 最多约 60 点，避免 payload 过大
    if len(recent) > 60:
        recent = recent[-60:]

    valid_q = [o for o in q_obs if str(o.data_quality or "").upper() != "MISSING"]
    ratio = None
    if valid_q:
        ratio = round(sum(float(o.score) for o in valid_q) / (len(valid_q) * 100.0), 3)

    provider = "server"
    if latest:
        provider = latest.provider or "server"
    elif prefer_browser:
        provider = "browser"

    quality = (latest.data_quality if latest else "MISSING") or "MISSING"
    quality_u = str(quality).upper()
    current_score = None
    if latest is not None and quality_u != "MISSING":
        current_score = round(float(latest.score), 1)

    return {
        "currentScore": current_score,
        "currentQuality": quality,
        "provider": provider,
        "sampleCount": len(q_obs) if question_id else len(selected),
        "questionAttentionRatio": ratio,
        "recentSamples": recent,
    }


def _build_preview(media_session_id: Optional[str]) -> Dict[str, Any]:
    from app.config import Config

    enabled = bool(getattr(Config, "MONITOR_PREVIEW_ENABLED", True))
    if not enabled:
        return {
            "enabled": False,
            "jpegBase64": None,
            "updatedAt": None,
            "stale": False,
            "reason": "PREVIEW_DISABLED",
        }
    if not media_session_id:
        return {
            "enabled": True,
            "jpegBase64": None,
            "updatedAt": None,
            "stale": True,
            "reason": "PREVIEW_UNAVAILABLE",
        }

    try:
        from app.routes.media_upload import get_last_probe_meta

        meta = get_last_probe_meta(media_session_id)
    except Exception:
        meta = None

    if not meta or not meta.get("frame"):
        return {
            "enabled": True,
            "jpegBase64": None,
            "updatedAt": None,
            "stale": True,
            "reason": "PREVIEW_UNAVAILABLE",
        }

    frame = meta.get("frame")
    updated_at = meta.get("updatedAt")
    max_bytes = int(getattr(Config, "MONITOR_PREVIEW_MAX_BYTES", 350_000) or 350_000)
    if isinstance(frame, str) and len(frame) > max_bytes:
        # 超限则仍标记有预览但不下发超大 payload
        return {
            "enabled": True,
            "jpegBase64": None,
            "updatedAt": updated_at,
            "stale": True,
            "reason": "PREVIEW_TOO_LARGE",
        }

    ttl_ms = int(getattr(Config, "MONITOR_PREVIEW_TTL_MS", 3000) or 3000)
    stale = True
    if updated_at is not None:
        try:
            stale = (int(time.time() * 1000) - int(updated_at)) > ttl_ms
        except Exception:
            stale = True

    return {
        "enabled": True,
        "jpegBase64": frame,
        "updatedAt": updated_at,
        "stale": stale,
        "reason": "PREVIEW_STALE" if stale else None,
    }


def _build_health_block(
    limitations: List[str],
    *,
    preview_stale: bool = False,
) -> Dict[str, Any]:
    from app.config import Config
    from app.report.limitations_copy import translate_limitations

    media_mode = Config.get_child_media_mode()
    socket_clients = {"teacher": 0, "child": 0, "server": 0}
    child_agent_online = False
    media_agent_online = False
    presence: Dict[str, Any] = {}
    try:
        from app.sockets.events import get_online_presence_snapshot

        presence = get_online_presence_snapshot()
        socket_clients = {
            "teacher": int(presence.get("teacherOnline") or 0),
            "child": int(presence.get("childOnline") or 0),
            "server": 1,
        }
        child_agent_online = bool(presence.get("childAgentOnline"))
        media_agent_online = bool(presence.get("childMediaAgentOnline"))
    except Exception:
        pass

    analyzers = {"attention": "mock", "speech": "mock"}
    try:
        from app.core.config_manager import get_config_manager

        cm = get_config_manager()
        analyzers = {
            "attention": cm.get_analyzer_mode("attention").value,
            "speech": cm.get_analyzer_mode("speech").value,
        }
    except Exception:
        pass

    lim = list(limitations)
    attn_mode = str(analyzers.get("attention") or "").lower()
    speech_mode = str(analyzers.get("speech") or "").lower()
    if attn_mode == "mock" or speech_mode == "mock":
        lim.append("DEMO_OR_MOCK_ANALYZERS")
    if attn_mode == "mock":
        lim.append("ATTENTION_PROVIDER_DEGRADED_OR_MOCK")
    if speech_mode == "mock":
        lim.append("SPEECH_PROVIDER_MOCK")

    readiness = None
    try:
        from app.services.readiness_service import get_readiness_service

        svc = get_readiness_service()
        gate = getattr(svc, "get_active_gate", None)
        if callable(gate):
            g = gate()
            if g:
                readiness = g.snapshot()
        elif hasattr(svc, "_active") and svc._active:
            g = svc._active
            readiness = {
                "status": getattr(g, "status", None),
                "trainingSessionId": getattr(g, "training_session_id", None),
            }
    except Exception:
        pass

    labels = translate_limitations(lim)
    connection_summary = _build_connection_summary(presence, readiness)
    return {
        "socketClients": socket_clients,
        "mediaMode": media_mode,
        "analyzers": analyzers,
        "childAgentOnline": child_agent_online,
        "mediaAgentOnline": media_agent_online,
        "previewStale": bool(preview_stale),
        "limitations": lim,
        "limitationLabels": labels,
        "connections": presence.get("connections") or {},
        "readiness": readiness,
        "connectionSummary": connection_summary,
    }


def _build_connection_summary(
    presence: Dict[str, Any], readiness: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Translate low-level connectivity into operator-facing diagnoses."""
    connections = presence.get("connections") or {}
    teacher_items = list(connections.get("teacher") or [])
    child_items = list(connections.get("child") or [])
    teacher_count = int(presence.get("teacherOnline") or 0)
    child_count = int(presence.get("childOnline") or 0)
    cards: List[Dict[str, Any]] = [{
        "id": "server",
        "level": "ok",
        "title": "服务端",
        "summary": "服务端正在运行，可通过 8080 端口提供教师端和接口。",
        "detail": "部署时让教师端和儿童端都访问这台电脑的局域网 IP。",
    }]

    teacher_ip = teacher_items[0].get("ip") if teacher_items else None
    controller_count = sum(1 for item in teacher_items if item.get("isController"))
    if teacher_count == 1:
        teacher_summary = f"已连接，IP：{teacher_ip or '暂未识别'}"
    elif teacher_count > 1:
        teacher_summary = (
            f"检测到 {teacher_count} 条教师连接（{controller_count} 条为当前控制），"
            "只有当前控制连接可操作。"
        )
    else:
        teacher_summary = "未连接教师端。"
    cards.append({
        "id": "teacher",
        "level": "ok" if teacher_count == 1 else "warn" if teacher_count > 1 else "error",
        "title": "教师端",
        "summary": teacher_summary,
        "detail": (
            "同一浏览器页面可能建立多条连接（均计为在线）。控制权按最后操作者切换："
            "需要接管时在只读页面点击「接管控制」；也可在下方连接列表终止多余连接。"
            if teacher_count > 1 else
            ("保持一个教师页面即可；重复打开时系统会把其他页面降为只读。"
             if teacher_count else "请打开 /teacher/ 登录，并确认设备与服务端在同一局域网。")
        ),
    })

    child_ip = child_items[0].get("ip") if child_items else None
    child_binding = child_items[0] if child_items else {}
    cards.append({
        "id": "child",
        "level": "ok" if child_count == 1 else "warn" if child_count > 1 else "error",
        "title": "儿童端",
        "summary": (
            f"已连接，IP：{child_ip or '暂未识别'}"
            if child_count == 1 else
            f"检测到 {child_count} 个儿童端，课程可能无法唯一投递。"
            if child_count > 1 else "未连接儿童端，课程内容和声音无法送达。"
        ),
        "detail": (
            f"当前绑定学生：{child_binding.get('studentId') or '尚未选课绑定'}；只保留一个儿童端窗口。"
            if child_count else "请在 Demo 机打开儿童端页面，并允许浏览器使用摄像头和麦克风。"
        ),
    })

    issues: List[Dict[str, str]] = []
    for card in cards:
        if card["level"] != "ok":
            issues.append({"level": card["level"], "problem": card["summary"], "action": card["detail"]})
    return {"cards": cards, "issues": issues}


def _build_emotion_block(store, training_session_id: str, question_id: Optional[str]) -> Dict[str, Any]:
    obs = store.list_emotion(training_session_id, question_id)
    valid = [
        o
        for o in obs
        if str(o.data_quality or "").upper() not in ("MISSING", "INSUFFICIENT", "MISSING_DEVICE")
        and not (o.positive == 0 and o.focused == 0 and o.frustrated == 0 and o.degraded)
    ]
    if len(valid) < 1:
        return {
            "available": False,
            "positiveRatio": None,
            "neutralRatio": None,
            "negativeRatio": None,
            "sampleCount": len(obs),
        }

    p = sum(o.positive for o in valid) / len(valid)
    f = sum(o.focused for o in valid) / len(valid)
    r = sum(o.frustrated for o in valid) / len(valid)
    tot = p + f + r
    if tot > 0:
        p, f, r = p / tot, f / tot, r / tot
    return {
        "available": True,
        "positiveRatio": round(p, 3),
        "neutralRatio": round(f, 3),  # focused ≈ 中性/专注
        "negativeRatio": round(r, 3),
        "sampleCount": len(valid),
    }


def _build_voice_block(store, training_session_id: str, question_id: Optional[str]) -> Dict[str, Any]:
    lang = store.list_language(training_session_id, question_id)
    last_transcript = None
    last_match_ok = None
    speech_ratio = None
    quality = "MISSING"

    for o in reversed(lang):
        if last_transcript is None and o.transcript:
            last_transcript = o.transcript
        if speech_ratio is None and o.speech_ratio is not None:
            speech_ratio = float(o.speech_ratio)
            quality = o.data_quality or "VALID"
        if last_transcript and speech_ratio is not None:
            break

    # 全局最近转录（本题可能没有）
    if last_transcript is None:
        for o in reversed(store.list_language(training_session_id)):
            if o.transcript:
                last_transcript = o.transcript
                break

    pipeline_active = False
    try:
        from app.services import get_analysis_service

        stats = get_analysis_service().get_statistics() or {}
        ap = stats.get("audio_pipeline") or {}
        pipeline_active = bool(ap.get("is_running") or ap.get("is_initialized"))
        # 活跃分析会话数也算收声中
        if int(stats.get("active_sessions") or 0) > 0:
            pipeline_active = True
    except Exception:
        pass

    try:
        from app.services import get_analysis_service

        svc = get_analysis_service()
        audio = getattr(svc, "_audio_pipeline", None)
        matcher = getattr(audio, "_speech_matcher", None) if audio else None
        if matcher and hasattr(matcher, "get_statistics"):
            st = matcher.get_statistics() or {}
            attempts = int(st.get("total_attempts") or 0)
            matches = int(st.get("total_matches") or 0)
            if attempts > 0:
                # 最近一轮是否曾匹配成功（粗粒度，无逐次历史时的近似）
                last_match_ok = matches > 0
    except Exception:
        pass

    return {
        "pipelineActive": pipeline_active,
        "lastTranscript": last_transcript,
        "lastMatchOk": last_match_ok,
        "expressive": {
            "speechRatio": speech_ratio,
            "quality": quality if speech_ratio is not None else "MISSING",
        },
    }


def _build_robot_block() -> Dict[str, Any]:
    try:
        from app.robot import get_robot_service

        control = get_robot_service().get_control_snapshot()
        command = control.get("lastCommand") or None
        components = (command or {}).get("components") or {}
        audio = components.get("audio") or {}
        command_phase = (command or {}).get("phase")
        return {
            "online": False,
            "runtimeOnline": False,
            "controlMode": "disabled",
            "targets": {},
            "busy": control.get("busy") or {},
            "lastCommand": command,
            "audioPlaying": bool(
                command_phase == "running"
                and audio.get("required")
                and audio.get("status") not in ("completed", "skipped", "failed", "timeout")
            ),
        }
    except Exception:
        return {
            "online": False,
            "runtimeOnline": False,
            "controlMode": "disabled",
            "targets": {},
            "busy": {},
            "lastCommand": None,
            "audioPlaying": False,
        }


def _empty_snapshot(limitations: Optional[List[str]] = None) -> Dict[str, Any]:
    preview = _build_preview(None)
    return {
        "generatedAt": _now_iso(),
        "active": False,
        "refreshHint": {"pollIntervalMs": POLL_INTERVAL_MS},
        "session": None,
        "course": None,
        "attention": {
            "currentScore": None,
            "currentQuality": "MISSING",
            "provider": "server",
            "sampleCount": 0,
            "questionAttentionRatio": None,
            "recentSamples": [],
        },
        "emotion": {
            "available": False,
            "positiveRatio": None,
            "neutralRatio": None,
            "negativeRatio": None,
            "sampleCount": 0,
        },
        "voice": {
            "pipelineActive": False,
            "lastTranscript": None,
            "lastMatchOk": None,
            "expressive": {"speechRatio": None, "quality": "MISSING"},
        },
        "robot": _build_robot_block(),
        "health": _build_health_block(limitations or [], preview_stale=bool(preview.get("stale"))),
        "events": [],
        "preview": preview,
    }


def get_monitor_snapshot(training_session_id: Optional[str] = None) -> Dict[str, Any]:
    """
    组装 MonitorSnapshot。

    Args:
        training_session_id: 可选；缺省时解析当前活跃训练会话。
    """
    limitations: List[str] = []
    tid = _resolve_training_session_id(training_session_id)

    if not tid:
        return _empty_snapshot()

    try:
        from app.behavior.service import get_behavior_service

        behavior = get_behavior_service()
        store = behavior.store
        training = store.get_training(tid)
    except Exception as e:
        logger.warning("monitor snapshot: 无法加载 training %s: %s", tid, e)
        snap = _empty_snapshot(["behavior_store_unavailable"])
        return snap

    if not training:
        return _empty_snapshot()

    # runtime / recording（方案 B：整场同一 mediaSessionId）
    runtime_session = None
    media_session_id = None
    human_dir_name = None
    recording = None

    try:
        from app.services.recording_timeline import get_recording_session_by_training

        recording = get_recording_session_by_training(tid)
        if recording:
            media_session_id = recording.media_session_id
            human_dir_name = recording.human_dir_name
    except Exception:
        pass

    try:
        from app.session import get_session_manager

        for s in get_session_manager().list_all_sessions():
            if getattr(s, "training_session_id", None) == tid and s.is_active():
                runtime_session = s
                break
        if runtime_session is None:
            # 已结束也可能需要展示；取最近同 training 的会话
            candidates = [
                s
                for s in get_session_manager().list_all_sessions()
                if getattr(s, "training_session_id", None) == tid
            ]
            if candidates:
                candidates.sort(
                    key=lambda s: s.started_at or s.created_at or datetime.min,
                    reverse=True,
                )
                runtime_session = candidates[0]
    except Exception as e:
        logger.debug("resolve runtime session failed: %s", e)

    if runtime_session:
        media_session_id = media_session_id or runtime_session.session_id
        meta = runtime_session.metadata or {}
        human_dir_name = human_dir_name or meta.get("human_dir_name")

    train_meta = training.metadata or {}
    human_dir_name = human_dir_name or train_meta.get("human_dir_name")

    status = _session_status(training, runtime_session, recording)
    is_active = training.status == "active" or status in ("warmup", "active", "finalizing")

    question_id = training.current_question_id
    if runtime_session and getattr(runtime_session, "question_id", None):
        if not (runtime_session.metadata or {}).get("warmup"):
            question_id = runtime_session.question_id or question_id

    window = store.get_window(tid, question_id) if question_id else None
    course_id = None
    course_item_id = None
    course_type = "default"
    question_index = 0
    opened_at = None

    if window:
        course_id = window.course_id
        course_item_id = window.course_item_id
        course_type = window.course_type or "default"
        question_index = int(window.question_index or 0)
        opened_at = window.opened_at
    elif runtime_session:
        course_id = runtime_session.course_id
        course_item_id = runtime_session.course_item_id
        course_type = (runtime_session.metadata or {}).get("course_type") or "default"
        question_index = int(runtime_session.question_index or 0)

    title = _lookup_course_title(course_id)
    windows = store.list_windows(tid)
    # 非 warmup 窗口数作 progress 参考
    non_warmup = [w for w in windows if not str(w.question_id or "").endswith("_warmup")]

    attention = _build_attention_block(store, tid, question_id)
    emotion = _build_emotion_block(store, tid, question_id)
    voice = _build_voice_block(store, tid, question_id)

    # agent 下无样本时质量应为 MISSING，勿伪造低分
    from app.config import Config
    from app.monitor.events import list_monitor_events
    from app.report.limitations_copy import translate_limitation

    media_mode = Config.get_child_media_mode()
    if attention["currentScore"] is None and attention["sampleCount"] == 0:
        attention["currentQuality"] = "MISSING"
        if media_mode == "agent":
            limitations.append("NO_ATTENTION_OBSERVATIONS")
    if str(attention.get("currentQuality") or "").upper() == "MISSING":
        limitations.append("ATTENTION_DATA_MISSING")

    preview = _build_preview(media_session_id)
    if preview.get("enabled") is False:
        limitations.append("PREVIEW_DISABLED")
    elif preview.get("reason") == "PREVIEW_UNAVAILABLE":
        limitations.append("PREVIEW_UNAVAILABLE")
    elif preview.get("stale"):
        limitations.append("PREVIEW_STALE")

    # 去重 limitations 码
    limitations = list(dict.fromkeys(limitations))

    snap = {
        "generatedAt": _now_iso(),
        "active": bool(is_active and training.status != "finalized"),
        "refreshHint": {"pollIntervalMs": POLL_INTERVAL_MS},
        "session": {
            "trainingSessionId": tid,
            "mediaSessionId": media_session_id,
            "runtimeSessionId": media_session_id,  # 方案 B：整场通常同一 ID
            "humanDirName": human_dir_name,
            "recordingMode": "continuous",
            "studentId": training.student_id,
            "startedAt": training.created_at,
            "status": status if training.status != "finalized" else "ended",
        },
        "course": {
            "courseType": course_type,
            "courseTypeId": None,
            "courseItemId": course_item_id,
            "entryId": None,
            "title": title or course_type,
            "questionIndex": question_index,
            "questionTotal": len(non_warmup) if non_warmup else None,
            "questionElapsedSec": round(_elapsed_sec(opened_at) or 0, 1),
            "questionId": question_id,
        },
        "attention": attention,
        "emotion": emotion,
        "voice": voice,
        "robot": _build_robot_block(),
        "health": _build_health_block(
            limitations,
            preview_stale=bool(preview.get("stale")),
        ),
        "events": list_monitor_events(40),
        "preview": preview,
    }
    # 确保 labels 含中文（health 已翻译；再兜底）
    if snap["health"].get("limitationLabels") is None:
        snap["health"]["limitationLabels"] = [
            translate_limitation(c) for c in snap["health"].get("limitations") or []
        ]
    return snap
