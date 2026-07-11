import { Router } from "express";
import { z, ZodError } from "zod";
import {
  createAnimationFinishedEvent,
  createAnimationStartedEvent,
  createTtsFinishedEvent,
  createTtsStartedEvent,
  handleClientDomainEvent
} from "../services/domainEventService.js";
import { fail, ok } from "./response.js";

const ackSchema = z.discriminatedUnion("eventType", [
  z.object({
    eventType: z.literal("ANIMATION_STARTED"),
    commandId: z.string().min(1),
    animationId: z.string().min(1)
  }),
  z.object({
    eventType: z.literal("ANIMATION_FINISHED"),
    commandId: z.string().min(1),
    status: z.enum(["completed", "interrupted", "failed"]),
    durationMs: z.number().nonnegative(),
    errorCode: z.string().optional()
  }),
  z.object({
    eventType: z.literal("TTS_STARTED"),
    turnId: z.string().min(1)
  }),
  z.object({
    eventType: z.literal("TTS_FINISHED"),
    turnId: z.string().min(1),
    durationMs: z.number().nonnegative(),
    audioRef: z.string().min(1)
  })
]);

export function createEventRoutes() {
  const router = Router();

  router.post("/events/:sessionId/ack", (req, res) => {
    try {
      const payload = ackSchema.parse(req.body);
      const sessionId = req.params.sessionId;
      const event =
        payload.eventType === "ANIMATION_STARTED"
          ? createAnimationStartedEvent({
              sessionId,
              commandId: payload.commandId,
              animationId: payload.animationId as never
            })
          : payload.eventType === "ANIMATION_FINISHED"
            ? createAnimationFinishedEvent({
                sessionId,
                commandId: payload.commandId,
                status: payload.status,
                durationMs: payload.durationMs,
                errorCode: payload.errorCode
              })
            : payload.eventType === "TTS_STARTED"
              ? createTtsStartedEvent({ sessionId, turnId: payload.turnId })
              : createTtsFinishedEvent({
                  sessionId,
                  turnId: payload.turnId,
                  durationMs: payload.durationMs,
                  audioRef: payload.audioRef
                });
      handleClientDomainEvent(event);
      res.json(ok({ eventId: event.eventId }));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid event ACK");
        return res.status(result.status).json(result.body);
      }
      const result = fail("EVENT_ACK_FAILED", error instanceof Error ? error.message : "Event ACK failed");
      return res.status(result.status).json(result.body);
    }
  });

  return router;
}
