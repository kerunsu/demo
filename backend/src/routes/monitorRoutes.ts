import { Router, json } from "express";
import { z, ZodError } from "zod";
import { MONITOR_PREVIEW_SCHEMA_VERSION } from "child-education-training-demo/shared/monitor-preview";
import { getMonitorSnapshot } from "../services/monitorSnapshotService.js";
import {
  getLatestMonitorPreview,
  isMonitorPreviewEnabled,
  storeMonitorPreviewFrame
} from "../services/monitorPreviewFrameService.js";
import { getLatestScreenMirrorFrame, storeScreenMirrorFrame } from "../services/screenMirrorFrameService.js";
import { runtimeConfig } from "../config/runtime.js";
import { fail, ok } from "./response.js";

const previewJson = json({ limit: "512kb" });
const screenMirrorJson = json({ limit: "8mb" });

const faceBoxSchema = z.object({
  x: z.number().min(0).max(1),
  y: z.number().min(0).max(1),
  width: z.number().min(0).max(1),
  height: z.number().min(0).max(1)
});

const previewMetaSchema = z.object({
  schemaVersion: z.literal(MONITOR_PREVIEW_SCHEMA_VERSION),
  sessionId: z.string().min(1),
  streamId: z.string().min(1),
  frameId: z.string().min(1),
  sequence: z.number().int().nonnegative(),
  capturedAt: z.string().datetime(),
  width: z.number().int().positive().max(1280),
  height: z.number().int().positive().max(720),
  faceBox: faceBoxSchema.optional(),
  facePresent: z.boolean().optional(),
  attentionScore: z.number().min(0).max(100).optional(),
  emotionDominant: z.enum(["positive", "focused", "frustrated"]).optional(),
  emotionLabel: z.string().max(32).optional(),
  attentionProvider: z.string().max(80).optional(),
  emotionProvider: z.string().max(80).optional(),
  attentionAlgorithmVersion: z.string().max(80).optional(),
  emotionAlgorithmVersion: z.string().max(80).optional()
});

const previewUploadSchema = z.object({
  schemaVersion: z.literal(MONITOR_PREVIEW_SCHEMA_VERSION),
  sessionId: z.string().min(1),
  mimeType: z.enum(["image/jpeg", "image/webp"]),
  imageBase64: z.string().min(16).max(512_000),
  meta: previewMetaSchema
});

const screenMirrorRoleSchema = z.enum(["child", "robot"]);

const screenMirrorUploadSchema = z.object({
  role: screenMirrorRoleSchema,
  sessionId: z.string().optional(),
  capturedAt: z.string().datetime(),
  sequence: z.number().int().nonnegative(),
  srcDoc: z.string().min(64).max(7_500_000)
});

export function createMonitorRoutes() {
  const router = Router();

  router.get("/monitor/session/:sessionId/snapshot", async (req, res) => {
    try {
      res.json(ok(await getMonitorSnapshot(req.params.sessionId)));
    } catch (error) {
      const result = fail("MONITOR_SNAPSHOT_FAILED", error instanceof Error ? error.message : "Monitor snapshot failed", 404);
      res.status(result.status).json(result.body);
    }
  });

  router.get("/monitor/preview/config", (_req, res) => {
    res.json(
      ok({
        enabled: isMonitorPreviewEnabled(),
        maxFps: runtimeConfig.monitorPreviewMaxFps,
        width: runtimeConfig.monitorPreviewWidth,
        height: runtimeConfig.monitorPreviewHeight,
        ttlMs: runtimeConfig.monitorPreviewTtlMs
      })
    );
  });

  router.post("/monitor/session/:sessionId/preview-frame", previewJson, (req, res) => {
    try {
      const payload = previewUploadSchema.parse(req.body);
      if (payload.sessionId !== req.params.sessionId) {
        const result = fail("MONITOR_PREVIEW_ROUTE_MISMATCH", "Route sessionId must match request body.");
        return res.status(result.status).json(result.body);
      }
      const result = storeMonitorPreviewFrame(payload);
      return res.json(ok(result));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid monitor preview payload");
        return res.status(result.status).json(result.body);
      }
      const message = error instanceof Error ? error.message : "Monitor preview upload failed";
      const status = message === "MONITOR_PREVIEW_DISABLED" ? 503 : 400;
      const result = fail("MONITOR_PREVIEW_UPLOAD_FAILED", message, status);
      return res.status(result.status).json(result.body);
    }
  });

  router.get("/monitor/session/:sessionId/preview/latest", (req, res) => {
    try {
      res.json(ok(getLatestMonitorPreview(req.params.sessionId)));
    } catch (error) {
      const result = fail(
        "MONITOR_PREVIEW_READ_FAILED",
        error instanceof Error ? error.message : "Monitor preview read failed",
        404
      );
      res.status(result.status).json(result.body);
    }
  });

  router.post("/monitor/screen-frame", screenMirrorJson, (req, res) => {
    try {
      const payload = screenMirrorUploadSchema.parse(req.body);
      res.json(ok(storeScreenMirrorFrame(payload)));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid screen frame payload");
        return res.status(result.status).json(result.body);
      }
      const result = fail(
        "SCREEN_FRAME_UPLOAD_FAILED",
        error instanceof Error ? error.message : "Screen frame upload failed",
        400
      );
      return res.status(result.status).json(result.body);
    }
  });

  router.get("/monitor/screen-frame/:role/latest", (req, res) => {
    try {
      const role = screenMirrorRoleSchema.parse(req.params.role);
      res.json(ok(getLatestScreenMirrorFrame(role)));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid screen role");
        return res.status(result.status).json(result.body);
      }
      const result = fail(
        "SCREEN_FRAME_READ_FAILED",
        error instanceof Error ? error.message : "Screen frame read failed",
        404
      );
      return res.status(result.status).json(result.body);
    }
  });

  return router;
}
