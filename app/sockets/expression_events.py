"""Socket callbacks for the Demo browser expression display only.

This module deliberately contains no pose, recording, motion-playback, OSC or
Robot Runtime handlers.  The legacy ``robot_*`` event names are retained for
wire compatibility with the expression page and command ledger.
"""
from __future__ import annotations

import random

from app.robot import get_robot_service
from app.utils.logger import setup_logger


logger = setup_logger("screen_expression_events")


def register_expression_events(socketio) -> None:
    @socketio.on("robot_emotion_ended")
    def handle_robot_emotion_ended(data):
        payload = data or {}
        command_id = payload.get("behaviorId") or payload.get("sequenceId")
        try:
            status = get_robot_service().mark_expression_terminal(
                command_id,
                status=str(payload.get("status") or "ended"),
                request_id=payload.get("requestId") or payload.get("request_id"),
                session_id=payload.get("sessionId") or payload.get("session_id"),
                modality=payload.get("modality"),
                reason=payload.get("reason"),
            )
            if status is None:
                logger.debug("Ignoring unknown expression terminal: %s", command_id)
        except Exception as exc:
            logger.error("Failed to process expression terminal: %s", exc)

    @socketio.on("robot_emotion_started")
    def handle_robot_emotion_started(data):
        payload = data or {}
        try:
            from app.sockets.events import _record_latency_modality_callback

            _record_latency_modality_callback(
                payload,
                phase="started",
                modality="expression",
                actor="robot_display",
            )
            result = get_robot_service().mark_behavior_modality_started(
                behavior_id=payload.get("behaviorId"),
                request_id=payload.get("requestId"),
                session_id=payload.get("sessionId"),
                modality=payload.get("modality"),
                actual_at_ms=payload.get("actualAtClientMs"),
            )
            if result is None:
                logger.debug("Ignoring unmatched expression started callback")
        except Exception as exc:
            logger.error("Failed to process expression started callback: %s", exc)

    @socketio.on("robot_emotion_ready")
    def handle_robot_emotion_ready(data):
        payload = data or {}
        try:
            from app.sockets.events import _record_latency_modality_callback

            _record_latency_modality_callback(
                payload,
                phase="ready",
                modality="expression",
                actor="robot_display",
            )
            result = get_robot_service().mark_behavior_modality_ready(
                behavior_id=payload.get("behaviorId"),
                request_id=payload.get("requestId"),
                session_id=payload.get("sessionId"),
                modality=payload.get("modality"),
            )
            if result is None:
                logger.debug("Ignoring unmatched expression ready callback")
        except Exception as exc:
            logger.error("Failed to process expression ready callback: %s", exc)

    @socketio.on("robot_emotion_auto_random")
    def handle_emotion_auto_random():
        try:
            service = get_robot_service()
            busy_state = getattr(service, "get_behavior_busy_state", None)
            if callable(busy_state):
                state = busy_state() or {}
                if state.get("busy"):
                    logger.info(
                        "Ignoring idle expression while formal behavior is busy: %s",
                        state.get("eventId"),
                    )
                    return
            emotions = service.get_available_emotions()
            if not emotions:
                logger.warning("No screen expressions available for idle selection")
                return
            service.trigger_emotion(random.choice(emotions))
        except Exception as exc:
            logger.error("Failed to select random idle expression: %s", exc)

    logger.info("Browser expression Socket events registered (motion disabled)")


__all__ = ["register_expression_events"]
