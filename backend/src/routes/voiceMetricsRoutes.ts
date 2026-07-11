import { Router } from "express";
import { getVoiceMetricsForSession, getVoiceTurnSummary } from "../services/voiceObservabilityService.js";
import { ok } from "./response.js";

export function createVoiceMetricsRoutes() {
  const router = Router();

  router.get("/voice-metrics/:sessionId", (req, res) => {
    res.json(ok(getVoiceMetricsForSession(req.params.sessionId)));
  });

  router.get("/voice-metrics/:sessionId/turns/:turnId", (req, res) => {
    res.json(ok(getVoiceTurnSummary(req.params.sessionId, req.params.turnId)));
  });

  return router;
}
