import { Router } from "express";
import { z, ZodError } from "zod";
import { startSessionSchema } from "../schemas/requestSchemas.js";
import { getLatestSessionInfo, getSession, startSession } from "../services/sessionService.js";
import { getSessionSnapshot } from "../services/sessionSnapshotService.js";
import { recordSessionMediaConsent } from "../services/rawMediaPersistenceService.js";
import { fail, ok } from "./response.js";

export function createSessionRoutes() {
  const router = Router();

  router.post("/session/start", (req, res) => {
    try {
      const payload = startSessionSchema.parse(req.body);
      const data = startSession(payload.childName, payload.courseType);
      res.json(ok(data));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid request");
        return res.status(result.status).json(result.body);
      }
      const result = fail("SESSION_START_FAILED", error instanceof Error ? error.message : "Unknown error");
      return res.status(result.status).json(result.body);
    }
  });

  router.get("/session/active/latest", (_req, res) => {
    res.json(ok(getLatestSessionInfo()));
  });

  router.get("/session/:sessionId", (req, res) => {
    try {
      const data = getSession(req.params.sessionId);
      res.json(ok(data));
    } catch (error) {
      const result = fail("SESSION_NOT_FOUND", error instanceof Error ? error.message : "Session not found", 404);
      res.status(result.status).json(result.body);
    }
  });

  router.get("/session/:sessionId/snapshot", (req, res) => {
    try {
      const after = typeof req.query.afterEventId === "string" ? req.query.afterEventId : undefined;
      const data = getSessionSnapshot(req.params.sessionId, after);
      res.json(ok(data));
    } catch (error) {
      const result = fail("SESSION_SNAPSHOT_NOT_FOUND", error instanceof Error ? error.message : "Session not found", 404);
      res.status(result.status).json(result.body);
    }
  });

  router.post("/session/:sessionId/media/consent", async (req, res) => {
    try {
      getSession(req.params.sessionId);
      const payload = z
        .object({
          consentedBy: z.string().min(1).default("training_start"),
          recordedAt: z.string().datetime().optional()
        })
        .parse(req.body ?? {});
      const manifest = await recordSessionMediaConsent(req.params.sessionId, {
        recordedAt: payload.recordedAt ?? new Date().toISOString(),
        consentedBy: payload.consentedBy,
        scope: "raw_audio_video"
      });
      res.json(ok({ sessionId: manifest.sessionId, consent: manifest.consent }));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid consent request");
        return res.status(result.status).json(result.body);
      }
      const result = fail("MEDIA_CONSENT_FAILED", error instanceof Error ? error.message : "Media consent failed", 400);
      return res.status(result.status).json(result.body);
    }
  });

  return router;
}
