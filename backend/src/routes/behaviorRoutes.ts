import { Router } from "express";
import { z, ZodError } from "zod";
import { receiveBrowserAudioFeatures } from "../services/audioFeatureService.js";
import { getCameraFrameStreamSummary, receiveCameraFrameDescriptor } from "../services/behaviorFrameIngressService.js";
import { fail, ok } from "./response.js";

const BEHAVIOR_FRAME_SCHEMA_VERSION = "m5-frame-v1";

const frameDescriptorSchema = z.object({
  schemaVersion: z.literal(BEHAVIOR_FRAME_SCHEMA_VERSION),
  sessionId: z.string().min(1),
  streamId: z.string().min(1),
  frameId: z.string().min(1),
  sequence: z.number().int().nonnegative(),
  capturedAt: z.string().datetime(),
  correlationId: z.string().min(1),
  questionId: z.string().optional(),
  width: z.number().int().positive().max(640),
  height: z.number().int().positive().max(480),
  downsampled: z.literal(true),
  frameHash: z.string().min(1).max(128),
  byteLength: z.number().int().nonnegative().max(1024 * 256),
  mimeType: z.enum(["image/jpeg", "image/webp", "mock/frame-descriptor"]),
  rawFramePersisted: z.literal(false),
  visualFeatures: z
    .object({
      facePresent: z.boolean(),
      faceCount: z.number().int().nonnegative().max(4),
      headOrientation: z.enum(["screen", "left", "right", "up", "down", "away", "unknown"]),
      roughlyFacingScreen: z.boolean().optional(),
      facingScore: z.number().min(0).max(1).optional(),
      centerOffsetX: z.number().min(-1).max(1).optional(),
      centerOffsetY: z.number().min(-1).max(1).optional(),
      faceAreaRatio: z.number().min(0).max(1).optional(),
      imageQuality: z.enum(["good", "low_light", "blurred", "occluded", "unavailable"]),
      provider: z.enum([
        "browser-face-detector",
        "browser-mediapipe-face",
        "browser-frame-quality",
        "camera-device",
        "attention-scoring-v2"
      ]),
      algorithmVersion: z.string().min(1).max(80),
      confidence: z.number().min(0).max(1)
    })
    .optional(),
  emotionFeatures: z
    .object({
      positiveScore: z.number().min(0).max(1),
      focusedScore: z.number().min(0).max(1),
      frustratedScore: z.number().min(0).max(1),
      facePresent: z.boolean(),
      provider: z.literal("browser-mediapipe-landmarker"),
      algorithmVersion: z.string().min(1).max(80),
      confidence: z.number().min(0).max(1),
      degraded: z.boolean()
    })
    .optional()
});

const audioFeatureSchema = z.object({
  schemaVersion: z.literal("m5-audio-features-v1"),
  sessionId: z.string().min(1),
  turnId: z.string().min(1),
  correlationId: z.string().min(1),
  questionId: z.string().optional(),
  observedAt: z.string().datetime(),
  audioDurationMs: z.number().int().nonnegative(),
  provider: z.enum(["browser-web-audio", "server-merged-audio"]),
  features: z.object({
    loudnessRms: z.number().min(0).max(1),
    loudnessDb: z.number().max(0),
    speechRatio: z.number().min(0).max(1),
    clarityProxy: z.number().min(0).max(1),
    sampleCount: z.number().int().nonnegative(),
    algorithmVersion: z.string().min(1).max(80),
    degraded: z.boolean()
  })
});

export function createBehaviorRoutes() {
  const router = Router();

  router.post("/behavior/:sessionId/camera/frames/:frameId", async (req, res) => {
    try {
      const payload = frameDescriptorSchema.parse(req.body);
      if (payload.sessionId !== req.params.sessionId || payload.frameId !== req.params.frameId) {
        const result = fail("BEHAVIOR_FRAME_ROUTE_MISMATCH", "Route sessionId/frameId must match request body.");
        return res.status(result.status).json(result.body);
      }
      const result = await receiveCameraFrameDescriptor(payload);
      return res.json(ok(result.ack));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid behavior frame descriptor");
        return res.status(result.status).json(result.body);
      }
      const result = fail("BEHAVIOR_FRAME_FAILED", error instanceof Error ? error.message : "Behavior frame failed");
      return res.status(result.status).json(result.body);
    }
  });

  router.get("/behavior/:sessionId/camera/streams/:streamId", (req, res) => {
    const summary = getCameraFrameStreamSummary(req.params.sessionId, req.params.streamId);
    if (!summary) {
      const result = fail("BEHAVIOR_FRAME_STREAM_NOT_FOUND", "Behavior camera stream not found.", 404);
      return res.status(result.status).json(result.body);
    }
    return res.json(ok(summary));
  });

  router.post("/behavior/:sessionId/voice-turns/:turnId/audio-features", (req, res) => {
    try {
      const payload = audioFeatureSchema.parse(req.body);
      if (payload.sessionId !== req.params.sessionId || payload.turnId !== req.params.turnId) {
        const result = fail("BEHAVIOR_AUDIO_ROUTE_MISMATCH", "Route sessionId/turnId must match request body.");
        return res.status(result.status).json(result.body);
      }
      const result = receiveBrowserAudioFeatures({ descriptor: payload });
      return res.json(ok(result));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid audio feature descriptor");
        return res.status(result.status).json(result.body);
      }
      const result = fail("BEHAVIOR_AUDIO_FEATURE_FAILED", error instanceof Error ? error.message : "Audio feature failed");
      return res.status(result.status).json(result.body);
    }
  });

  return router;
}
