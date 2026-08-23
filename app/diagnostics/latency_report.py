"""Correlate existing interaction telemetry into operator-facing latency reports.

The report is deliberately read-only.  It measures and classifies the existing
playback path without changing scheduling, media selection, or state-machine
semantics.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import math
from typing import Any, Iterable, Mapping, Optional


SCHEMA_VERSION = "interaction-latency-report-v1"
MODALITY_LABELS = {
    "expression": "表情",
    "motion": "动作",
    "display": "下屏显示",
    "audio": "语音",
    "childAnimation": "鼓励动画",
}

VOICE_STRATEGY_REVIEW = {
    "title": "儿童真实语音交互策略检查",
    "summary": "课程答案优先于普通对话；机器人播音期间为防回声暂停 ASR。",
    "scenarios": [
        {
            "id": "wake_then_fast_answer",
            "name": "唤醒后立即回答",
            "expected": "保留唤醒回复结束后的句首，课程关键词命中后走表扬链路。",
            "status": "covered",
            "evidence": "180ms 输出冷却 + 700ms pre-roll；关键词判断先于 LLM。",
        },
        {
            "id": "answer_during_robot_speech",
            "name": "机器人仍在说话时抢答",
            "expected": "当前会被回声保护门丢弃，需要等机器人说完后再答。",
            "status": "risk",
            "evidence": "asrPausedForTts=true 时持续清空采集缓冲。",
        },
        {
            "id": "soft_voice_in_noisy_classroom",
            "name": "教室噪声中轻声回答",
            "expected": "固定 VAD 门限可能漏掉轻声，或被持续背景声延后截句。",
            "status": "risk",
            "evidence": "浏览器端使用固定 START/SILENCE/RESET_LEVEL。",
        },
        {
            "id": "wrong_answer_then_correct",
            "name": "先答错再答对",
            "expected": "未命中保留聆听；后续命中仍可触发一次表扬并去重。",
            "status": "covered",
            "evidence": "关键词状态在 hit 后才 praised/disarm。",
        },
        {
            "id": "question_switch_after_wake",
            "name": "唤醒后切换到下一题",
            "expected": "题目指纹改变会清空唤醒状态，避免上一题上下文串入下一题。",
            "status": "intentional",
            "evidence": "awake 状态绑定 course/question/item/options 指纹。",
        },
    ],
    "findings": [
        {
            "severity": "high",
            "title": "抢答与回声保护存在策略冲突",
            "detail": "儿童在机器人朗读尚未结束时回答不会进入 ASR；现场会表现为‘没听见’。这是当前策略而非网络故障。",
        },
        {
            "severity": "medium",
            "title": "固定 VAD 门限缺少环境自适应",
            "detail": "轻声儿童、远场麦克风和持续教室噪声需要分别观察漏检率与截句耗时。",
        },
        {
            "severity": "info",
            "title": "课程识别与闲聊已有明确优先级",
            "detail": "已武装课程关键词先判定；命中后不调用 LLM，避免正确答案被当成闲聊。",
        },
    ],
}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _round_ms(value: Any) -> Optional[int]:
    number = _number(value)
    return max(0, int(round(number))) if number is not None else None


def _percentile(values: Iterable[Any], percentile: float) -> Optional[int]:
    ordered = sorted(value for item in values if (value := _number(item)) is not None)
    if not ordered:
        return None
    if len(ordered) == 1:
        return int(round(ordered[0]))
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return int(round(value))


def _summary(values: Iterable[Any]) -> dict[str, Any]:
    valid = [float(value) for item in values if (value := _number(item)) is not None]
    return {
        "samples": len(valid),
        "p50Ms": _percentile(valid, 0.50),
        "p95Ms": _percentile(valid, 0.95),
        "maxMs": _round_ms(max(valid)) if valid else None,
    }


def _details(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("details")
    return dict(value) if isinstance(value, Mapping) else {}


def _payload(row: Mapping[str, Any]) -> dict[str, Any]:
    value = _details(row).get("payload")
    return dict(value) if isinstance(value, Mapping) else {}


def _event_time(row: Optional[Mapping[str, Any]]) -> Optional[float]:
    return _number((row or {}).get("serverEpochMs"))


def _first(rows: list[dict[str, Any]], predicate) -> Optional[dict[str, Any]]:
    return next((row for row in rows if predicate(row)), None)


def _intent_from_payload(payload: Mapping[str, Any]) -> str:
    aux = payload.get("aux") if isinstance(payload.get("aux"), Mapping) else {}
    for key, label in (
        ("praise", "表扬"), ("hint", "提示"), ("question", "提问"),
        ("socialGreetingIntro", "社交问候"), ("socialGreetingPlay", "社交邀请"),
        ("socialFarewellBye", "社交告别"), ("socialFarewellReply", "社交回应"),
    ):
        if aux.get(key):
            return label
    return "切换课点"


def _modality_from_row(row: Mapping[str, Any]) -> Optional[str]:
    event = str(row.get("event") or "")
    payload = _payload(row)
    modality = str(payload.get("modality") or row.get("modality") or "")
    if event == "child_socket_emit.resource_ready":
        return "display"
    if modality == "speech":
        return "audio"
    if modality in MODALITY_LABELS:
        return modality
    if event == "child_socket_emit.audio_status" and str(payload.get("status") or "") == "playing":
        return "audio"
    return None


def _is_started(row: Mapping[str, Any]) -> bool:
    event = str(row.get("event") or "")
    status = str(row.get("status") or "").lower()
    payload = _payload(row)
    payload_status = str(payload.get("status") or "").lower()
    if event == "child_socket_emit.resource_ready":
        return True
    if event == "latency.modality_started_callback":
        return True
    if event == "child_socket_emit.behavior_modality_started":
        return True
    if event == "child_socket_emit.audio_status" and payload_status == "playing":
        return True
    if (
        event == "robot_motion_status"
        and status in {"dispatched", "playing", "started"}
    ):
        # Runtime currently acknowledges command dispatch, not the first
        # physical servo movement.  Expose this useful proxy explicitly.
        return True
    return status in {"playing", "started"} and str(row.get("category") or "") == "robot_execution"


def _is_ready(row: Mapping[str, Any]) -> bool:
    event = str(row.get("event") or "")
    status = str(row.get("status") or "").lower()
    payload_status = str(_payload(row).get("status") or "").lower()
    return (
        event == "latency.modality_ready_callback"
        or
        event == "child_socket_emit.behavior_modality_ready"
        or (event.startswith("robot_") and status in {"prepared", "ready"})
        or payload_status == "ready"
    )


def _client_stage_ms(row: Optional[Mapping[str, Any]], *, ready: bool = False) -> Optional[int]:
    payload = _payload(row or {}) or _details(row or {})
    received = _number(payload.get("commandReceivedAtClientMs"))
    actual = _number(payload.get("readyAtClientMs") if ready else payload.get("actualAtClientMs"))
    if received is None or actual is None or actual < received:
        return None
    return _round_ms(actual - received)


def _diagnose_contributors(
    *, network_rtt_ms: Optional[int], server_queue_ms: Optional[int],
    planned_lead_ms: Optional[int], late_from_plan_ms: Optional[int],
) -> list[dict[str, Any]]:
    values = [
        ("network", "网络单程估计", _round_ms((network_rtt_ms or 0) / 2), "estimated"),
        ("server", "Server 解析/排队", server_queue_ms, "measured"),
        ("sync", "系统同步预留", planned_lead_ms, "intentional"),
        ("endpoint", "终端准备/回执尾延迟", late_from_plan_ms, "observed"),
    ]
    return [
        {"source": source, "label": label, "ms": value, "confidence": confidence}
        for source, label, value, confidence in values
        if value is not None and value > 0
    ]


def _build_interaction(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows.sort(key=lambda row: _number(row.get("serverEpochMs")) or 0)
    teacher = _first(rows, lambda row: row.get("event") == "teacher_socket_emit.play_resource")
    received = _first(rows, lambda row: row.get("event") == "latency.play_resource_received")
    queued = _first(rows, lambda row: row.get("event") == "robot_behavior_queued")
    dispatched = _first(rows, lambda row: row.get("event") == "latency.multimodal_dispatched")
    ack = _first(rows, lambda row: row.get("event") == "play_resource_ack")
    source_payload = _payload(teacher or {}) or _details(received or {}).get("request") or {}
    if not isinstance(source_payload, Mapping):
        source_payload = {}

    received_at = _event_time(received) or _event_time(teacher) or _event_time(queued)
    queued_at = _event_time(queued)
    dispatched_at = _event_time(dispatched)
    ack_at = _event_time(ack)
    queued_details = _details(queued or {})
    planned_start = _number(queued_details.get("startAtEpochMs"))
    network_rtt = _round_ms(
        _details(received or {}).get("teacherNetworkRttMs")
        or source_payload.get("teacherNetworkRttMs")
    )
    server_queue = _round_ms(queued_at - received_at) if queued_at is not None and received_at is not None else None
    planned_lead = _round_ms(planned_start - queued_at) if planned_start is not None and queued_at is not None else None

    modalities: dict[str, Any] = {}
    dominant_candidates: list[tuple[str, int]] = []
    for modality in MODALITY_LABELS:
        candidates = [row for row in rows if _modality_from_row(row) == modality]
        ready_row = _first(candidates, _is_ready)
        started_row = _first(candidates, _is_started)
        if not ready_row and not started_row:
            continue
        ready_at = _event_time(ready_row)
        started_at = _event_time(started_row)
        total = _round_ms(started_at - received_at) if started_at is not None and received_at is not None else None
        late_from_plan = (
            _round_ms(started_at - planned_start)
            if started_at is not None and planned_start is not None
            else None
        )
        client_prepare = _client_stage_ms(ready_row, ready=True)
        client_start = _client_stage_ms(started_row)
        contributors = _diagnose_contributors(
            network_rtt_ms=network_rtt,
            server_queue_ms=server_queue,
            planned_lead_ms=planned_lead,
            late_from_plan_ms=late_from_plan,
        )
        if contributors:
            dominant = max(contributors, key=lambda item: item["ms"])
            dominant_candidates.append((dominant["source"], dominant["ms"]))
        else:
            dominant = None
        modalities[modality] = {
            "label": MODALITY_LABELS[modality],
            "readyObservedMs": _round_ms(ready_at - received_at) if ready_at is not None and received_at is not None else None,
            "startObservedMs": total,
            "lateFromPlannedStartMs": late_from_plan,
            "clientPrepareMs": client_prepare,
            "clientReceiveToStartMs": client_start,
            "dominantSource": dominant,
            "contributors": contributors,
            "measurementQuality": (
                "dispatch_proxy"
                if modality == "motion"
                and started_row
                and started_row.get("event") == "robot_motion_status"
                and str(started_row.get("status") or "").lower() == "dispatched"
                else "observed"
            ),
            "endpointStages": (
                dict(
                    (_payload(started_row) or _details(started_row)).get(
                        "timing"
                    ) or {}
                )
                if modality == "display"
                and isinstance(
                    (_payload(started_row) or _details(started_row)).get(
                        "timing"
                    ),
                    Mapping,
                )
                else {}
            ),
        }

    primary_source = max(dominant_candidates, key=lambda item: item[1])[0] if dominant_candidates else "insufficient_data"
    return {
        "requestId": str((rows[0].get("requestId") if rows else "") or ""),
        "behaviorId": str(next((row.get("behaviorId") for row in rows if row.get("behaviorId")), "") or ""),
        "intent": _intent_from_payload(source_payload),
        "courseType": source_payload.get("courseType"),
        "questionId": next((row.get("questionId") for row in rows if row.get("questionId")), None),
        "accepted": bool(ack and str(ack.get("status") or "") == "accepted"),
        "status": str((ack or {}).get("status") or "incomplete"),
        "observedAt": (received or teacher or queued or rows[0]).get("timestamp") if rows else None,
        "metrics": {
            "teacherNetworkRttMs": network_rtt,
            "serverQueueMs": server_queue,
            "serverDispatchMs": _round_ms(dispatched_at - received_at) if dispatched_at is not None and received_at is not None else None,
            "serverAckMs": _round_ms(ack_at - received_at) if ack_at is not None and received_at is not None else None,
            "plannedSyncLeadMs": planned_lead,
        },
        "primarySource": primary_source,
        "modalities": modalities,
    }


def _build_dialogue_round(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows.sort(key=lambda row: _number(row.get("serverEpochMs")) or 0)
    events = {str(row.get("event") or ""): row for row in rows}
    received = events.get("dialogue.audio_received") or events.get("dialogue.text_received")
    stt = events.get("dialogue.stt_completed")
    utterance = events.get("dialogue_utterance_received")
    reply = events.get("dialogue_reply_generated")
    keyword = events.get("dialogue_keyword_hit")
    course_miss = events.get("dialogue_course_answer_miss")
    wake = events.get("dialogue_wake_word_matched")
    tts_dispatch = events.get("dialogue.tts_dispatched")
    result_received = events.get("dialogue.client_result_received")
    tts_received = events.get("dialogue.client_tts_command_received")
    tts_started = events.get("dialogue.client_tts_started")
    terminal = reply or keyword or course_miss or wake or stt or received
    received_at = _event_time(received)

    client_timing = _details(received or {}).get("clientTiming")
    if not isinstance(client_timing, Mapping):
        client_timing = {}
    stt_details = _details(stt or {})
    stt_timing = (
        stt_details.get("timing")
        if isinstance(stt_details.get("timing"), Mapping)
        else {}
    )
    reply_details = _details(reply or {})
    tts_started_details = _details(tts_started or {})

    def since_received(row: Optional[Mapping[str, Any]]) -> Optional[int]:
        current = _event_time(row)
        if current is None or received_at is None:
            return None
        return _round_ms(current - received_at)

    outcome = "incomplete"
    if keyword:
        outcome = "course_keyword_hit"
    elif course_miss:
        outcome = "course_answer_miss"
    elif wake:
        outcome = "wake"
    elif reply:
        outcome = "reply"
    elif stt and str(stt.get("status") or "") == "failed":
        outcome = "stt_failed"

    return {
        "requestId": str(rows[0].get("requestId") or ""),
        "observedAt": (received or rows[0]).get("timestamp"),
        "outcome": outcome,
        "provider": reply_details.get("provider") or stt_details.get("provider"),
        "strategy": reply_details.get("strategy"),
        "status": str((terminal or {}).get("status") or "incomplete"),
        "metrics": {
            "vadSilenceTailMs": _round_ms(client_timing.get("vadSilenceTailMs")),
            "audioEncodingMs": _round_ms(client_timing.get("encodingMs")),
            "sttMs": _round_ms(stt_details.get("durationMs")),
            "sttDecodeMs": _round_ms(stt_timing.get("base64DecodeMs")),
            "sttConvertMs": _round_ms(stt_timing.get("audioConvertMs")),
            "sttLocalAttemptMs": _round_ms(stt_timing.get("localAttemptMs")),
            "sttRemoteFallbackMs": _round_ms(stt_timing.get("remoteFallbackMs")),
            "serverToTranscriptMs": since_received(utterance),
            "replyGenerationMs": _round_ms(reply_details.get("replyDurationMs")),
            "serverToDecisionMs": since_received(reply or keyword or course_miss or wake),
            "serverToTtsDispatchMs": since_received(tts_dispatch),
            "resultObservedMs": since_received(result_received),
            "ttsCommandObservedMs": since_received(tts_received),
            "ttsStartObservedMs": since_received(tts_started),
            "clientTtsStartupMs": _round_ms(tts_started_details.get("clientStageMs")),
        },
        "clientCapture": dict(client_timing),
    }


def build_latency_report(
    training_session_id: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    media_session_id: Optional[str] = None,
) -> dict[str, Any]:
    normalized = [dict(row) for row in rows if isinstance(row, Mapping)]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in normalized:
        request_id = str(row.get("requestId") or "").strip()
        if request_id:
            grouped.setdefault(request_id, []).append(row)
    interactions = [
        _build_interaction(items)
        for items in grouped.values()
        if any(
            row.get("event") in {
                "teacher_socket_emit.play_resource",
                "latency.play_resource_received",
                "robot_behavior_queued",
                "play_resource_ack",
            }
            for row in items
        )
    ]
    interactions.sort(key=lambda item: str(item.get("observedAt") or ""), reverse=True)

    dialogue_groups: dict[str, list[dict[str, Any]]] = {}
    for row in normalized:
        request_id = str(row.get("requestId") or "").strip()
        if request_id and str(row.get("event") or "").startswith("dialogue"):
            dialogue_groups.setdefault(request_id, []).append(row)
    dialogue_rounds = [
        _build_dialogue_round(items)
        for items in dialogue_groups.values()
        if any(
            row.get("event") in {"dialogue.audio_received", "dialogue.text_received"}
            for row in items
        )
    ]
    dialogue_rounds.sort(
        key=lambda item: str(item.get("observedAt") or ""), reverse=True
    )

    modality_totals: dict[str, Any] = {}
    for modality, label in MODALITY_LABELS.items():
        details = [
            detail
            for item in interactions
            if (detail := item.get("modalities", {}).get(modality))
        ]
        values = [detail.get("startObservedMs") for detail in details]
        modality_totals[modality] = {
            "label": label,
            **_summary(values),
            "proxySamples": sum(
                1 for detail in details
                if detail.get("measurementQuality") == "dispatch_proxy"
            ),
        }
        if modality == "display":
            stage_keys = (
                "commandToTransitionMs", "preflightMs", "preloadMs",
                "iframeLoadMs", "paintWaitMs", "crossfadeMs", "totalClientMs",
            )
            modality_totals[modality]["endpointStages"] = {
                key: _summary(
                    detail.get("endpointStages", {}).get(key)
                    for detail in details
                )
                for key in stage_keys
            }

    network_values = [item["metrics"].get("teacherNetworkRttMs") for item in interactions]
    server_values = [item["metrics"].get("serverDispatchMs") for item in interactions]
    lead_values = [item["metrics"].get("plannedSyncLeadMs") for item in interactions]
    source_counts = Counter(item.get("primarySource") for item in interactions if item.get("primarySource"))
    primary_source = source_counts.most_common(1)[0][0] if source_counts else "insufficient_data"

    findings: list[dict[str, Any]] = []
    network_summary = _summary(network_values)
    server_summary = _summary(server_values)
    lead_summary = _summary(lead_values)
    if (network_summary.get("p95Ms") or 0) >= 200:
        findings.append({"severity": "warning", "source": "network", "title": "教师端网络往返偏高", "detail": f"RTT P95 为 {network_summary['p95Ms']}ms。"})
    if (server_summary.get("p95Ms") or 0) >= 300:
        findings.append({"severity": "warning", "source": "server", "title": "Server 内部处理偏慢", "detail": f"接收到多模态下发 P95 为 {server_summary['p95Ms']}ms。"})
    if (lead_summary.get("p50Ms") or 0) >= 500:
        findings.append({"severity": "info", "source": "sync", "title": "存在有意的同步预留", "detail": f"同步起播预留 P50 为 {lead_summary['p50Ms']}ms；这是为了动作、表情、语音对齐，并非网络阻塞。"})
    if not interactions:
        findings.append({"severity": "info", "source": "data", "title": "暂无可关联的播放样本", "detail": "开始一场课程并触发提问、提示或表扬后刷新本页。"})

    dialogue_metrics = {
        key: _summary(
            item.get("metrics", {}).get(key) for item in dialogue_rounds
        )
        for key in (
            "vadSilenceTailMs", "audioEncodingMs", "sttMs",
            "sttDecodeMs", "sttConvertMs", "sttLocalAttemptMs",
            "sttRemoteFallbackMs",
            "replyGenerationMs", "serverToDecisionMs",
            "clientTtsStartupMs", "ttsStartObservedMs",
        )
    }
    if (dialogue_metrics["vadSilenceTailMs"].get("p50Ms") or 0) >= 750:
        findings.append({
            "severity": "info", "source": "voice",
            "title": "自然对话包含 VAD 等待",
            "detail": (
                f"儿童停声后等待 P50 为 "
                f"{dialogue_metrics['vadSilenceTailMs']['p50Ms']}ms；"
                "这是截句完整性预留，不是网络延迟。"
            ),
        })
    if (dialogue_metrics["sttMs"].get("p95Ms") or 0) >= 1000:
        findings.append({
            "severity": "warning", "source": "voice",
            "title": "语音识别偏慢",
            "detail": f"STT P95 为 {dialogue_metrics['sttMs']['p95Ms']}ms。",
        })

    session_ids = sorted({
        str(row.get("sessionId")) for row in normalized if row.get("sessionId")
    })
    recovered_legacy_rows = sum(
        1 for row in normalized if row.get("_legacyMisplacedAuditRow")
    )
    isolated = (
        session_ids in ([], [str(media_session_id)])
        if media_session_id
        else len(session_ids) <= 1
    )
    if not isolated:
        findings.insert(0, {
            "severity": "high", "source": "data",
            "title": "日志包含其他媒体会话",
            "detail": "当前报告检测到多个媒体会话，已标记为不可信。",
        })
    elif recovered_legacy_rows:
        findings.insert(0, {
            "severity": "warning", "source": "data",
            "title": "已隔离恢复旧版错位日志",
            "detail": (
                f"按媒体会话 ID 从旧目录恢复 {recovered_legacy_rows} 条事件；"
                "报告仍只包含当前录制轮次。新版写入已改为直接落到正确目录。"
            ),
        })

    return {
        "success": True,
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "trainingSessionId": str(training_session_id),
        "mediaSessionId": str(media_session_id) if media_session_id else None,
        "summary": {
            "interactionCount": len(interactions),
            "acceptedCount": sum(1 for item in interactions if item.get("accepted")),
            "primarySource": primary_source,
            "network": network_summary,
            "serverDispatch": server_summary,
            "plannedSyncLead": lead_summary,
        },
        "modalities": modality_totals,
        "findings": findings,
        "interactions": interactions[:200],
        "dialogue": {
            "roundCount": len(dialogue_rounds),
            "metrics": dialogue_metrics,
            "rounds": dialogue_rounds[:200],
        },
        "dataQuality": {
            "isolated": isolated,
            "requestedMediaSessionId": media_session_id,
            "observedMediaSessionIds": session_ids,
            "rowCount": len(normalized),
            "recoveredLegacyRows": recovered_legacy_rows,
        },
        "voiceStrategy": VOICE_STRATEGY_REVIEW,
        "measurementNotes": [
            "Server 内部耗时与同步预留使用同一 Server 时钟，可直接比较。",
            "教师端网络使用 Socket 往返时间；单程值只能估计为 RTT/2。",
            "终端启动回执包含终端处理与回传网络，跨电脑时不把墙上时钟差误当作延迟。",
            "缺少某模态表示该行为未配置该模态、终端离线，或旧终端尚未上报。",
        ],
    }


def render_latency_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    lines = [
        "# 交互延迟诊断报告",
        "",
        f"- 训练会话：`{report.get('trainingSessionId')}`",
        f"- 媒体会话：`{report.get('mediaSessionId') or '未限定'}`",
        f"- 生成时间：{report.get('generatedAt')}",
        f"- 可关联交互：{summary.get('interactionCount', 0)}",
        f"- 主要来源：{summary.get('primarySource', 'insufficient_data')}",
        "",
        "## 总体指标",
        "",
        "| 环节 | 样本 | P50 | P95 | 最大值 |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, item in (
        ("教师端网络 RTT", summary.get("network") or {}),
        ("Server 接收至下发", summary.get("serverDispatch") or {}),
        ("系统同步预留", summary.get("plannedSyncLead") or {}),
    ):
        lines.append(f"| {label} | {item.get('samples', 0)} | {item.get('p50Ms')}ms | {item.get('p95Ms')}ms | {item.get('maxMs')}ms |")
    lines.extend(["", "## 四模态观测", "", "| 模态 | 样本 | P50 | P95 | 最大值 |", "|---|---:|---:|---:|---:|"])
    for item in (report.get("modalities") or {}).values():
        lines.append(f"| {item.get('label')} | {item.get('samples', 0)} | {item.get('p50Ms')}ms | {item.get('p95Ms')}ms | {item.get('maxMs')}ms |")
    lines.extend(["", "## 自然对话分段", "", "| 阶段 | 样本 | P50 | P95 | 最大值 |", "|---|---:|---:|---:|---:|"])
    dialogue = report.get("dialogue") or {}
    dialogue_labels = {
        "vadSilenceTailMs": "停声到截句",
        "audioEncodingMs": "浏览器音频编码",
        "sttMs": "FunASR 识别",
        "sttDecodeMs": "Server Base64 解码",
        "sttConvertMs": "音频转 WAV",
        "sttLocalAttemptMs": "本机 FunASR 尝试",
        "sttRemoteFallbackMs": "语音服务回退",
        "replyGenerationMs": "回复生成",
        "serverToDecisionMs": "Server 收到到决策",
        "clientTtsStartupMs": "浏览器 TTS 启动",
        "ttsStartObservedMs": "Server 收到到实际开口",
    }
    for key, item in (dialogue.get("metrics") or {}).items():
        lines.append(
            f"| {dialogue_labels.get(key, key)} | {item.get('samples', 0)} | "
            f"{item.get('p50Ms')}ms | {item.get('p95Ms')}ms | {item.get('maxMs')}ms |"
        )
    lines.extend(["", "## 自动判断", ""])
    for finding in report.get("findings") or []:
        lines.append(f"- **{finding.get('title')}**：{finding.get('detail')}")
    lines.extend(["", "## 语音策略模拟", ""])
    voice = report.get("voiceStrategy") or {}
    for scenario in voice.get("scenarios") or []:
        lines.append(f"- **{scenario.get('name')}**（{scenario.get('status')}）：{scenario.get('expected')}")
    lines.extend(["", "## 测量说明", ""])
    lines.extend(f"- {note}" for note in report.get("measurementNotes") or [])
    return "\n".join(lines) + "\n"
