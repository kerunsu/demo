import { Router } from "express";
import { z, ZodError } from "zod";
import { runtimeConfig } from "../config/runtime.js";
import { processPartnerVoiceTurn, probeVoicePartnerHealth } from "../services/voicePartnerProxyService.js";
import { persistChildTranscriptObservations } from "../services/chatService.js";
import { fail, ok } from "./response.js";

const pageContextTextSchema = z.object({
  schemaVersion: z.literal("voice-page-context-v1"),
  courseType: z.enum(["matching", "ordering"]),
  questionIndex: z.number().int().nonnegative(),
  totalQuestions: z.number().int().positive(),
  prompt: z.string(),
  target: z.string(),
  targetImageUrl: z.string().optional(),
  options: z.array(
    z.object({
      id: z.string(),
      label: z.string(),
      imageUrl: z.string().optional()
    })
  ),
  interaction: z.object({
    selectedOptionIds: z.array(z.string()),
    wrongAttempts: z.number().int().nonnegative(),
    elapsedMs: z.number().int().nonnegative()
  }),
  narrative: z.string()
});

const partnerTurnSchema = z.object({
  streamId: z.string().min(1),
  turnId: z.string().min(1),
  correlationId: z.string().min(1),
  locale: z.string().optional(),
  capturedAt: z.string().optional(),
  pageContext: z.object({
    text: pageContextTextSchema,
    screenshot: z
      .object({
        mimeType: z.enum(["image/jpeg", "image/png"]),
        base64: z.string().min(1),
        width: z.number().int().positive(),
        height: z.number().int().positive()
      })
      .nullable(),
    screenshotUnavailableReason: z.string().optional()
  })
});

const transcriptObservationSchema = z.object({
  text: z.string().min(1).max(500),
  turnId: z.string().optional(),
  correlationId: z.string().optional(),
  confidence: z.number().min(0).max(1).optional()
});

export function createVoicePartnerRoutes() {
  const router = Router();

  router.get("/voice-partner/health", async (_req, res) => {
    const partner = await probeVoicePartnerHealth();
    res.json(
      ok({
        dialogProvider: runtimeConfig.voiceDialogProvider,
        partner,
        configured: Boolean(runtimeConfig.voicePartnerBaseUrl)
      })
    );
  });

  router.post("/voice-partner/:sessionId/turn", async (req, res) => {
    try {
      const payload = partnerTurnSchema.parse(req.body);
      const data = await processPartnerVoiceTurn({
        sessionId: req.params.sessionId,
        ...payload
      });
      res.json(ok(data));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid partner turn request");
        return res.status(result.status).json(result.body);
      }
      const message = error instanceof Error ? error.message : "Partner turn failed";
      const status = message === "AUDIO_NOT_AVAILABLE" ? 404 : message.startsWith("PARTNER") ? 502 : 400;
      const result = fail(message, message === "Course already completed" ? "训练已结束" : "对话暂时不可用，请稍后再试。", status);
      return res.status(result.status).json(result.body);
    }
  });

  router.post("/voice-partner/:sessionId/transcript-observations", async (req, res) => {
    try {
      const payload = transcriptObservationSchema.parse(req.body);
      const data = await persistChildTranscriptObservations(req.params.sessionId, payload.text, {
        turnId: payload.turnId,
        correlationId: payload.correlationId,
        confidence: payload.confidence
      });
      res.json(ok(data));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid transcript observation request");
        return res.status(result.status).json(result.body);
      }
      const result = fail("TRANSCRIPT_OBSERVATION_FAILED", error instanceof Error ? error.message : "Failed");
      return res.status(result.status).json(result.body);
    }
  });

  return router;
}
