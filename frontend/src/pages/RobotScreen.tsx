import { useEffect, useMemo, useRef, useState } from "react";
import { ROBOT_ANIMATION_IDS, type RobotAnimationId, type RobotAnimationIntent } from "child-education-training-demo/shared/animations";
import type { DomainEvent } from "child-education-training-demo/shared/domain-events";
import { createAckDomainEvent, sendEventAck, type EventAckPayload } from "../services/eventAck";
import { connectRealtime } from "../services/realtimeClient";
import { getSessionSnapshot, resolveRobotScreenSessionId } from "../services/sessionSnapshot";
import { GifAnimationAdapter, type GifPlaybackEvent } from "../features/robot/gifAnimationAdapter";
import { RobotGifStage } from "../features/robot/RobotGifStage";
import { playSpeechAudio } from "../features/robot/speechPlayback";
import { requestRobotSpeech } from "../features/voice/voiceTurnClient";
import { useScreenMirrorSource } from "../features/screenMirror/screenMirror";

const IDLE_ANIMATION_ID = "eye";
const AMBIENT_EXPRESSION_INTERVAL_MS = 60_000;
const ACTIVE_SESSION_POLL_INTERVAL_MS = 500;
const SNAPSHOT_POLL_INTERVAL_MS = 500;
const FALLBACK_EXPRESSION_DURATION_MS = 1800;
const ACTIVE_SESSION_STORAGE_KEY = "m3.activeSessionId";
const AMBIENT_ANIMATIONS = ROBOT_ANIMATION_IDS.filter((animationId) => animationId !== IDLE_ANIMATION_ID) as RobotAnimationId[];

export function RobotScreen() {
  useScreenMirrorSource("robot");
  const [sessionId, setSessionId] = useState("");
  const [connectionState, setConnectionState] = useState("disconnected");
  const [animationState, setAnimationState] = useState<RobotAnimationId | "failed" | "interrupted" | "completed">(IDLE_ANIMATION_ID);
  const [speechState, setSpeechState] = useState("idle");
  const [currentImage, setCurrentImage] = useState<string | null>(null);
  const [lastEventId, setLastEventId] = useState<string | undefined>();
  const [soundEnabled] = useState(true);
  const seenEvents = useRef(new Set<string>());
  const processedCommands = useRef(new Set<string>());
  const processedSpeechTurns = useRef(new Set<string>());
  const pendingSpeechEvent = useRef<DomainEvent | null>(null);
  const stopSpeechPlayback = useRef<(() => void) | undefined>();
  const realtimeRef = useRef<ReturnType<typeof connectRealtime> | null>(null);
  const sessionIdRef = useRef("");
  const lastSnapshotEventIdRef = useRef<string | undefined>();
  const ambientTimerRef = useRef<number | null>(null);
  const lastAmbientIndexRef = useRef(-1);
  sessionIdRef.current = sessionId;

  const adapter = useMemo(
    () =>
      new GifAnimationAdapter((event: GifPlaybackEvent) => {
        if (event.type === "started") {
          setCurrentImage(event.src);
          setAnimationState(event.animationId);
          sendAck(sessionIdRef.current, {
            eventType: "ANIMATION_STARTED",
            commandId: event.commandId,
            animationId: event.animationId
          });
          return;
        }

        setAnimationState(event.status);
        sendAck(sessionIdRef.current, {
          eventType: "ANIMATION_FINISHED",
          commandId: event.commandId,
          status: event.status,
          durationMs: event.durationMs,
          errorCode: event.errorCode
        });
        if (event.animationId !== IDLE_ANIMATION_ID) {
          showIdle("animation_finished");
        }
      }),
    []
  );

  useEffect(() => {
    const pinnedSessionId = new URLSearchParams(window.location.search).get("sessionId");
    const syncSessionId = async () => {
      const storedSessionId = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY) || "";
      const nextSessionId = await resolveRobotScreenSessionId(pinnedSessionId, storedSessionId);
      setSessionId((current) => (current === nextSessionId ? current : nextSessionId));
    };

    void syncSessionId();
    showIdle("initial");
    if (pinnedSessionId) return;

    window.addEventListener("storage", syncSessionId);
    const timer = window.setInterval(syncSessionId, ACTIVE_SESSION_POLL_INTERVAL_MS);
    return () => {
      window.removeEventListener("storage", syncSessionId);
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    let closed = false;
    seenEvents.current.clear();
    processedCommands.current.clear();
    processedSpeechTurns.current.clear();
    lastSnapshotEventIdRef.current = undefined;
    pendingSpeechEvent.current = null;
    stopSpeechPlayback.current?.();
    stopSpeechPlayback.current = undefined;
    setLastEventId(undefined);
    showIdle(`session:${sessionId}:connected`);
    const refreshSnapshot = async () => {
      const snapshot = await getSessionSnapshot(sessionId, lastSnapshotEventIdRef.current);
      if (closed) return;
      setLastEventId(snapshot.lastEventId ?? undefined);
      lastSnapshotEventIdRef.current = snapshot.lastEventId ?? lastSnapshotEventIdRef.current;
      for (const event of snapshot.events) {
        handleDomainEvent(event);
      }
    };
    void refreshSnapshot();
    const snapshotTimer = window.setInterval(() => {
      void refreshSnapshot();
    }, SNAPSHOT_POLL_INTERVAL_MS);
    const client = connectRealtime({
      sessionId,
      screenRole: "robot",
      clientId: "robot-screen",
      onStatus: (status) => setConnectionState(status),
      onMessage: (message) => {
        if (message.type === "event") {
          handleDomainEvent(message.event);
        }
      }
    });
    realtimeRef.current = client;
    return () => {
      closed = true;
      realtimeRef.current = null;
      stopSpeechPlayback.current?.();
      stopSpeechPlayback.current = undefined;
      window.clearInterval(snapshotTimer);
      client.close();
    };
  }, [sessionId]);

  useEffect(() => {
    ambientTimerRef.current = window.setInterval(() => {
      if (!adapter.isIdleLoop() || AMBIENT_ANIMATIONS.length === 0) return;
      lastAmbientIndexRef.current = (lastAmbientIndexRef.current + 1) % AMBIENT_ANIMATIONS.length;
      adapter.play({
        commandId: `ambient:${Date.now().toString(36)}`,
        sessionId: sessionIdRef.current || "ambient-idle",
        sourceEventId: "ambient-expression-timer",
        animationId: AMBIENT_ANIMATIONS[lastAmbientIndexRef.current],
        intent: "special_state",
        expectedDurationMs: FALLBACK_EXPRESSION_DURATION_MS,
        loop: false,
        priority: "low",
        interruptPolicy: "interrupt"
      });
    }, AMBIENT_EXPRESSION_INTERVAL_MS);
    return () => {
      if (ambientTimerRef.current !== null) {
        window.clearInterval(ambientTimerRef.current);
        ambientTimerRef.current = null;
      }
    };
  }, [adapter]);

  function sendAck(targetSessionId: string, payload: EventAckPayload) {
    if (!targetSessionId) return;
    const domainEvent = createAckDomainEvent(targetSessionId, payload);
    if (realtimeRef.current) {
      realtimeRef.current.sendEvent(domainEvent);
      return;
    }
    void sendEventAck(targetSessionId, payload);
  }

  function showIdle(sourceEventId: string) {
    adapter.showIdle(sessionIdRef.current || "robot-idle", sourceEventId);
    setAnimationState(IDLE_ANIMATION_ID);
  }

  function handleDomainEvent(event: DomainEvent) {
    if (seenEvents.current.has(event.eventId)) return;
    seenEvents.current.add(event.eventId);
    setLastEventId(event.eventId);
    lastSnapshotEventIdRef.current = event.eventId;
    if (event.eventType === "FEEDBACK_REQUESTED") {
      const turnId = `tts_${event.eventId}`;
      if (!soundEnabled) {
        pendingSpeechEvent.current = event;
        setSpeechState("waiting_for_audio_permission");
        return;
      }
      if (!processedSpeechTurns.current.has(turnId)) {
        playFeedbackSpeech(event);
      }
    }
    if (event.eventType === "ANIMATION_REQUESTED") {
      if (processedCommands.current.has(event.payload.commandId)) return;
      processedCommands.current.add(event.payload.commandId);
      adapter.play({
        commandId: event.payload.commandId,
        sessionId: event.sessionId,
        sourceEventId: event.eventId,
        animationId: event.payload.animationId as RobotAnimationId,
        intent: event.payload.intent as RobotAnimationIntent,
        priority: event.payload.priority >= 3 ? "high" : "normal",
        interruptPolicy: event.payload.interruptPolicy === "queue" ? "queue" : "interrupt",
        expectedDurationMs: FALLBACK_EXPRESSION_DURATION_MS,
        loop: false
      });
    }
  }

  function playFeedbackSpeech(event: DomainEvent) {
    if (event.eventType !== "FEEDBACK_REQUESTED") return;
    const turnId = `tts_${event.eventId}`;
    if (processedSpeechTurns.current.has(turnId)) return;
    processedSpeechTurns.current.add(turnId);
    stopSpeechPlayback.current?.();
    setSpeechState("synthesizing");
    void requestRobotSpeech({
      sessionId: event.sessionId,
      turnId,
      correlationId: event.correlationId,
      text: event.payload.text
    })
      .then((tts) => {
        const audio = tts.ok ? tts.data : undefined;
        stopSpeechPlayback.current = playSpeechAudio({
          turnId,
          text: event.payload.text,
          audioBase64: audio?.audioBase64,
          mimeType: audio?.mimeType,
          durationMs: audio?.durationMs,
          onStarted: () => {
            setSpeechState("playing");
            sendAck(event.sessionId, { eventType: "TTS_STARTED", turnId });
          },
          onFinished: (durationMs) => {
            stopSpeechPlayback.current = undefined;
            setSpeechState("completed");
            sendAck(event.sessionId, {
              eventType: "TTS_FINISHED",
              turnId,
              durationMs,
              audioRef: audio?.audioRef ?? "mock://local-feedback"
            });
          },
          onFailed: () => {
            stopSpeechPlayback.current = undefined;
            setSpeechState("failed");
            sendAck(event.sessionId, {
              eventType: "TTS_FINISHED",
              turnId,
              durationMs: 0,
              audioRef: "failed://robot-speech"
            });
          }
        });
      })
      .catch(() => {
        setSpeechState("degraded_playback");
        stopSpeechPlayback.current = playSpeechAudio({
          turnId,
          text: event.payload.text,
          onStarted: () => sendAck(event.sessionId, { eventType: "TTS_STARTED", turnId }),
          onFinished: (durationMs) => {
            stopSpeechPlayback.current = undefined;
            setSpeechState("completed");
            sendAck(event.sessionId, {
              eventType: "TTS_FINISHED",
              turnId,
              durationMs,
              audioRef: "mock://local-feedback"
            });
          },
          onFailed: () => {
            stopSpeechPlayback.current = undefined;
            setSpeechState("failed");
          }
        });
      });
  }

  return (
    <main
      className="robot-screen-shell robot-screen-pure"
      aria-label="机器人全屏表情页"
      data-session-id={sessionId}
      data-connection-state={connectionState}
      data-animation-state={animationState}
      data-speech-state={speechState}
    >
      <RobotGifStage src={currentImage} onError={() => adapter.failCurrent("RESOURCE_MISSING")} />
    </main>
  );
}
