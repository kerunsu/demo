import { Router } from "express";
import { probePythonVoiceServiceHealth } from "../services/pythonVoiceHealthService.js";
import { getVoiceProviderStatus } from "../services/voice/voiceOrchestrator.js";
import { ok } from "./response.js";

export function createHealthRoutes() {
  const router = Router();

  router.get("/health", async (_req, res) => {
    const pythonVoice = await probePythonVoiceServiceHealth();
    res.json(ok({ status: "ok", voice: getVoiceProviderStatus(), pythonVoice }));
  });

  router.get("/voice/providers", (_req, res) => {
    res.json(ok(getVoiceProviderStatus()));
  });

  return router;
}
