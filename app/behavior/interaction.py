"""Server-authoritative classroom interaction timeline and state machine."""
from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
from typing import Any, Dict, Optional, Tuple

from app.behavior.models import InteractionEvent
from app.behavior.store import BehaviorStore, get_behavior_store


EVENT_STATES = {
    "question_presented": "presenting_question",
    "question_audio_ended": "awaiting_response",
    "no_response": "no_response",
    "question_repeat": "repeating_question",
    "hint": "hinting",
    "reminder": "reminding",
    "child_response": "responded",
    "praise": "praising",
    "rating": "rated",
    "next_question": "completed",
}


class InteractionStateService:
    def __init__(self, store: Optional[BehaviorStore] = None):
        self.store = store or get_behavior_store()
        self._lock = threading.RLock()
        self._state: Dict[Tuple[str, str], Dict[str, Any]] = {}

    @staticmethod
    def _key(training_session_id: str, question_id: Optional[str]) -> Tuple[str, str]:
        return str(training_session_id), str(question_id or "")

    def _restore(self, training_session_id: str, question_id: Optional[str]) -> Dict[str, Any]:
        key = self._key(training_session_id, question_id)
        cached = self._state.get(key)
        if cached is not None:
            return cached
        state: Dict[str, Any] = {
            "state": "idle",
            "firstQuestionEndedAtMs": None,
            "latestPromptEndedAtMs": None,
            "firstResponseAtMs": None,
            "responseMsFromFirstQuestion": None,
            "responseMsFromLatestPrompt": None,
            "questionPresentationCount": 0,
            "hintCount": 0,
            "lastEventType": None,
        }
        for event in self.store.list_interaction_events(training_session_id, question_id):
            state["state"] = event.state_after
            state["lastEventType"] = event.event_type
            if event.event_type == "question_presented":
                state["questionPresentationCount"] += 1
            elif event.event_type in ("hint", "reminder"):
                state["hintCount"] += 1
            elif event.event_type == "question_audio_ended":
                if state["firstQuestionEndedAtMs"] is None:
                    state["firstQuestionEndedAtMs"] = event.server_epoch_ms
                state["latestPromptEndedAtMs"] = event.server_epoch_ms
            elif event.event_type == "child_response" and state["firstResponseAtMs"] is None:
                self._set_response_metrics(state, event.server_epoch_ms)
        self._state[key] = state
        return state

    @staticmethod
    def _set_response_metrics(state: Dict[str, Any], response_at_ms: float) -> None:
        state["firstResponseAtMs"] = response_at_ms
        first = state.get("firstQuestionEndedAtMs")
        latest = state.get("latestPromptEndedAtMs")
        if first is not None:
            state["responseMsFromFirstQuestion"] = max(0.0, response_at_ms - first)
        if latest is not None:
            state["responseMsFromLatestPrompt"] = max(0.0, response_at_ms - latest)

    def record(
        self,
        event_type: str,
        training_session_id: str,
        *,
        question_id: Optional[str] = None,
        runtime_session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        behavior_id: Optional[str] = None,
        actor: str = "server",
        client_timestamp: Optional[str] = None,
        degraded: bool = False,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        server_epoch_ms: Optional[float] = None,
    ) -> InteractionEvent:
        if not training_session_id:
            raise ValueError("training_session_id_missing")
        now_ms = float(server_epoch_ms if server_epoch_ms is not None else time.time() * 1000.0)
        with self._lock:
            state = self._restore(training_session_id, question_id)
            before = str(state["state"])
            effective_type = str(event_type)
            if effective_type == "question_presented":
                if int(state["questionPresentationCount"]) > 0:
                    effective_type = "question_repeat"
                state["questionPresentationCount"] += 1
            elif effective_type == "hint":
                if int(state["hintCount"]) > 0:
                    effective_type = "reminder"
                state["hintCount"] += 1
            after = EVENT_STATES.get(effective_type, before)
            if effective_type == "question_audio_ended":
                if state["firstQuestionEndedAtMs"] is None:
                    state["firstQuestionEndedAtMs"] = now_ms
                state["latestPromptEndedAtMs"] = now_ms
            elif effective_type == "child_response" and state["firstResponseAtMs"] is None:
                self._set_response_metrics(state, now_ms)
            state["state"] = after
            state["lastEventType"] = effective_type
            event_metadata = dict(metadata or {})
            event_metadata.update({
                "firstQuestionEndedAtMs": state["firstQuestionEndedAtMs"],
                "latestPromptEndedAtMs": state["latestPromptEndedAtMs"],
                "responseMsFromFirstQuestion": state["responseMsFromFirstQuestion"],
                "responseMsFromLatestPrompt": state["responseMsFromLatestPrompt"],
            })
            timestamp = datetime.fromtimestamp(
                now_ms / 1000.0, tz=timezone.utc
            ).isoformat().replace("+00:00", "Z")
            event = InteractionEvent(
                event_type=effective_type,
                training_session_id=str(training_session_id),
                runtime_session_id=str(runtime_session_id) if runtime_session_id else None,
                question_id=str(question_id) if question_id else None,
                request_id=str(request_id) if request_id else None,
                behavior_id=str(behavior_id) if behavior_id else None,
                actor=str(actor),
                timestamp=timestamp,
                server_epoch_ms=now_ms,
                client_timestamp=client_timestamp,
                state_before=before,
                state_after=after,
                degraded=bool(degraded),
                error=str(error) if error else None,
                metadata=event_metadata,
            )
            self.store.add_interaction_event(event)
            try:
                from app.behavior.audit_timeline import record_audit_event
                record_audit_event(
                    effective_type,
                    training_session_id=training_session_id,
                    runtime_session_id=runtime_session_id,
                    question_id=question_id,
                    request_id=request_id,
                    behavior_id=behavior_id,
                    actor=actor,
                    source="interaction_state",
                    category="course_interaction",
                    phase="observed",
                    status="degraded" if degraded else "ok",
                    client_timestamp=client_timestamp,
                    degraded=degraded,
                    error=error,
                    details=event_metadata,
                )
            except Exception:
                # The audit stream must never interrupt the live classroom path.
                pass
            return event

    def response_metrics(
        self, training_session_id: str, question_id: Optional[str]
    ) -> Dict[str, Optional[float]]:
        with self._lock:
            state = self._restore(training_session_id, question_id)
            return {
                "responseMsFromFirstQuestion": state["responseMsFromFirstQuestion"],
                "responseMsFromLatestPrompt": state["responseMsFromLatestPrompt"],
            }

    def snapshot(
        self, training_session_id: str, question_id: Optional[str]
    ) -> Dict[str, Any]:
        with self._lock:
            return dict(self._restore(training_session_id, question_id))


_service: Optional[InteractionStateService] = None
_service_lock = threading.Lock()


def get_interaction_service() -> InteractionStateService:
    global _service
    with _service_lock:
        if _service is None:
            _service = InteractionStateService()
        return _service
