import { Router } from "express";
import { z, ZodError } from "zod";
import {
  cancelVoiceTurn,
  completeVoiceTurn,
  getVoiceTurnSnapshot,
  markRobotSpeaking,
  retryVoiceTurn,
  startListeningTurn,
  stopListeningForTranscription
} from "../services/voiceTurnService.js";
import { synthesizeSpeech } from "../services/speechTtsService.js";
import { fail, ok } from "./response.js";

const startSchema = z.object({
  turnId: z.string().min(1),
  timeoutMs: z.number().int().positive().max(30000).optional(),
  maxRetries: z.number().int().nonnegative().max(5).optional()
});

const reasonSchema = z.object({
  turnId: z.string().optional(),
  reason: z.string().min(1).optional()
});

export function createVoiceTurnRoutes() {
  const router = Router();

  router.get("/voice-turns/:sessionId", (req, res) => {
    res.json(ok(getVoiceTurnSnapshot(req.params.sessionId)));
  });

  router.post("/voice-turns/:sessionId/start-listening", (req, res) => {
    try {
      const payload = startSchema.parse(req.body);
      res.json(ok(startListeningTurn({ sessionId: req.params.sessionId, ...payload })));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid voice turn start request");
        return res.status(result.status).json(result.body);
      }
      const result = fail("VOICE_TURN_START_FAILED", error instanceof Error ? error.message : "Voice turn start failed");
      return res.status(result.status).json(result.body);
    }
  });

  router.post("/voice-turns/:sessionId/stop-listening", (req, res) => {
    const payload = reasonSchema.parse(req.body);
    res.json(ok(stopListeningForTranscription(req.params.sessionId, payload.reason ?? "speech_end")));
  });

  router.post("/voice-turns/:sessionId/robot-speaking", (req, res) => {
    const payload = z.object({
      turnId: z.string().min(1),
      speaking: z.boolean(),
      reason: z.string().optional()
    }).parse(req.body);
    res.json(ok(markRobotSpeaking({ sessionId: req.params.sessionId, ...payload })));
  });

  router.post("/voice-turns/:sessionId/cancel", (req, res) => {
    const payload = reasonSchema.parse(req.body);
    res.json(ok(cancelVoiceTurn(req.params.sessionId, payload.reason ?? "cancelled")));
  });

  router.post("/voice-turns/:sessionId/retry", (req, res) => {
    const payload = reasonSchema.parse(req.body);
    res.json(ok(retryVoiceTurn(req.params.sessionId, payload.reason ?? "retry")));
  });

  router.post("/voice-turns/:sessionId/complete", (req, res) => {
    const payload = reasonSchema.parse(req.body);
    res.json(ok(completeVoiceTurn(req.params.sessionId, payload.reason ?? "completed")));
  });

  router.post("/voice-turns/:sessionId/tts", async (req, res) => {
    try {
      const payload = z.object({
        turnId: z.string().min(1),
        correlationId: z.string().min(1),
        text: z.string().min(1).max(500),
        voice: z.string().optional(),
        timeoutMs: z.number().int().positive().max(15000).optional()
      }).parse(req.body);
      const result = await synthesizeSpeech({ sessionId: req.params.sessionId, ...payload });
      if (!result.ok) {
        return res.status(502).json(ok(result));
      }
      return res.json(ok(result));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid TTS request");
        return res.status(result.status).json(result.body);
      }
      const result = fail("VOICE_TTS_FAILED", error instanceof Error ? error.message : "Voice TTS failed");
      return res.status(result.status).json(result.body);
    }
  });

  return router;
}
