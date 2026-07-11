import express, { Router } from "express";
import { z, ZodError } from "zod";
import { MEDIA_MAX_CHUNK_BYTES } from "child-education-training-demo/shared/media";
import { VIDEO_MAX_SEGMENT_BYTES } from "child-education-training-demo/shared/raw-media";
import { finishMediaStream, getMediaStreamSummary, receiveMediaChunk, startMediaStream } from "../services/mediaIngressService.js";
import {
  getRawMediaRuntimeConfig,
  getSessionMediaManifest,
  getSessionMediaSummary,
  recordSessionMediaConsent
} from "../services/rawMediaPersistenceService.js";
import { transcribeMediaStream } from "../services/speechSttService.js";
import {
  finishVideoStream,
  getVideoStreamSummary,
  receiveVideoSegment,
  startVideoStream,
  uploadVideoThumbnail
} from "../services/videoIngressService.js";
import { fail, ok } from "./response.js";

const audioFormatSchema = z.object({
  codec: z.enum(["pcm_s16le", "wav", "webm_opus", "webm", "ogg_opus", "unknown"]),
  mimeType: z.string().min(1),
  sampleRateHz: z.number().int().positive(),
  channels: z.number().int().positive().max(2),
  chunkDurationMs: z.number().int().positive().max(2000)
});

const streamStartSchema = z.object({
  sessionId: z.string().min(1),
  streamId: z.string().min(1),
  turnId: z.string().min(1),
  correlationId: z.string().min(1),
  deviceIdHash: z.string().optional(),
  startedAt: z.string().datetime(),
  format: audioFormatSchema,
  maxTurnDurationMs: z.number().int().positive().max(30000)
});

const streamFinishSchema = z.object({
  sessionId: z.string().min(1),
  streamId: z.string().min(1),
  turnId: z.string().min(1),
  correlationId: z.string().min(1),
  reason: z.enum(["speech_end", "manual_stop", "cancelled", "timeout", "disconnect", "device_lost"]),
  endedAt: z.string().datetime()
});

const videoStreamFinishSchema = z.object({
  sessionId: z.string().min(1),
  streamId: z.string().min(1),
  correlationId: z.string().min(1),
  reason: z.enum(["question_end", "manual_stop", "cancelled", "timeout", "disconnect", "device_lost"]),
  endedAt: z.string().datetime()
});

function routeMatchesBody(sessionId: string, streamId: string, body: { sessionId: string; streamId: string }) {
  return body.sessionId === sessionId && body.streamId === streamId;
}

export function createMediaRoutes() {
  const router = Router();

  router.get("/media/config", (_req, res) => {
    res.json(ok(getRawMediaRuntimeConfig()));
  });

  router.get("/media/:sessionId/summary", async (req, res) => {
    try {
      const summary = await getSessionMediaSummary(req.params.sessionId);
      res.json(ok(summary));
    } catch (error) {
      const result = fail("MEDIA_SUMMARY_FAILED", error instanceof Error ? error.message : "Media summary failed", 404);
      res.status(result.status).json(result.body);
    }
  });

  router.get("/media/:sessionId/manifest", async (req, res) => {
    try {
      const manifest = await getSessionMediaManifest(req.params.sessionId);
      if (!manifest) {
        const result = fail("MEDIA_MANIFEST_NOT_FOUND", "Media manifest not found.", 404);
        return res.status(result.status).json(result.body);
      }
      return res.json(ok(manifest));
    } catch (error) {
      const result = fail("MEDIA_MANIFEST_FAILED", error instanceof Error ? error.message : "Media manifest failed", 404);
      return res.status(result.status).json(result.body);
    }
  });

  router.post("/media/:sessionId/streams/:streamId/start", async (req, res) => {
    try {
      const payload = streamStartSchema.parse(req.body);
      if (!routeMatchesBody(req.params.sessionId, req.params.streamId, payload)) {
        const result = fail("MEDIA_ROUTE_MISMATCH", "Route sessionId/streamId must match request body.");
        return res.status(result.status).json(result.body);
      }
      res.json(ok(await startMediaStream(payload)));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid media stream start request");
        return res.status(result.status).json(result.body);
      }
      const result = fail("MEDIA_STREAM_START_FAILED", error instanceof Error ? error.message : "Media stream start failed");
      return res.status(result.status).json(result.body);
    }
  });

  router.post(
    "/media/:sessionId/streams/:streamId/chunks/:sequence",
    express.raw({ type: "application/octet-stream", limit: MEDIA_MAX_CHUNK_BYTES }),
    async (req, res) => {
      try {
        const sequence = Number.parseInt(req.params.sequence, 10);
        if (!Number.isSafeInteger(sequence) || sequence < 0) {
          const result = fail("MEDIA_BAD_SEQUENCE", "Chunk sequence must be a non-negative integer.");
          return res.status(result.status).json(result.body);
        }
        if (!Buffer.isBuffer(req.body)) {
          const result = fail("MEDIA_BAD_CONTENT_TYPE", "Audio chunks must use application/octet-stream.");
          return res.status(result.status).json(result.body);
        }
        const metadata = {
          sessionId: req.params.sessionId,
          streamId: req.params.streamId,
          turnId: String(req.header("x-turn-id") ?? ""),
          correlationId: String(req.header("x-correlation-id") ?? ""),
          sequence,
          capturedAt: String(req.header("x-captured-at") ?? new Date().toISOString()),
          durationMs: Number.parseInt(String(req.header("x-duration-ms") ?? "0"), 10),
          byteLength: req.body.byteLength,
          format: {
            codec: String(req.header("x-audio-codec") ?? "unknown") as never,
            mimeType: String(req.header("x-audio-mime-type") ?? "application/octet-stream"),
            sampleRateHz: Number.parseInt(String(req.header("x-sample-rate-hz") ?? "16000"), 10),
            channels: Number.parseInt(String(req.header("x-audio-channels") ?? "1"), 10),
            chunkDurationMs: Number.parseInt(String(req.header("x-chunk-duration-ms") ?? "250"), 10)
          }
        };
        const parsedMetadata = z.object({
          sessionId: z.string().min(1),
          streamId: z.string().min(1),
          turnId: z.string().min(1),
          correlationId: z.string().min(1),
          sequence: z.number().int().nonnegative(),
          capturedAt: z.string().datetime(),
          durationMs: z.number().int().positive(),
          byteLength: z.number().int().nonnegative(),
          format: audioFormatSchema
        }).parse(metadata);
        res.json(ok(await receiveMediaChunk(parsedMetadata, req.body)));
      } catch (error) {
        if (error instanceof ZodError) {
          const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid media chunk metadata");
          return res.status(result.status).json(result.body);
        }
        const result = fail("MEDIA_CHUNK_FAILED", error instanceof Error ? error.message : "Media chunk failed");
        return res.status(result.status).json(result.body);
      }
    }
  );

  router.post("/media/:sessionId/streams/:streamId/finish", async (req, res) => {
    try {
      const payload = streamFinishSchema.parse(req.body);
      if (!routeMatchesBody(req.params.sessionId, req.params.streamId, payload)) {
        const result = fail("MEDIA_ROUTE_MISMATCH", "Route sessionId/streamId must match request body.");
        return res.status(result.status).json(result.body);
      }
      res.json(ok(await finishMediaStream(payload)));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid media stream finish request");
        return res.status(result.status).json(result.body);
      }
      const result = fail("MEDIA_STREAM_FINISH_FAILED", error instanceof Error ? error.message : "Media stream finish failed");
      return res.status(result.status).json(result.body);
    }
  });

  router.post("/media/:sessionId/streams/:streamId/transcribe", async (req, res) => {
    try {
      const payload = z.object({
        turnId: z.string().min(1),
        correlationId: z.string().min(1),
        languageHint: z.string().optional(),
        timeoutMs: z.number().int().positive().max(15000).optional()
      }).parse(req.body);
      const result = await transcribeMediaStream({
        sessionId: req.params.sessionId,
        streamId: req.params.streamId,
        turnId: payload.turnId,
        correlationId: payload.correlationId,
        languageHint: payload.languageHint,
        timeoutMs: payload.timeoutMs
      });
      if (!result.ok) {
        return res.json(ok(result));
      }
      return res.json(ok(result));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid media transcription request");
        return res.status(result.status).json(result.body);
      }
      const result = fail("MEDIA_TRANSCRIBE_FAILED", error instanceof Error ? error.message : "Media transcription failed");
      return res.status(result.status).json(result.body);
    }
  });

  router.get("/media/:sessionId/streams/:streamId", (req, res) => {
    const summary = getMediaStreamSummary(req.params.sessionId, req.params.streamId);
    if (!summary) {
      const result = fail("MEDIA_STREAM_NOT_FOUND", "Media stream not found.", 404);
      return res.status(result.status).json(result.body);
    }
    return res.json(ok(summary));
  });

  router.post("/media/:sessionId/video/:streamId/start", async (req, res) => {
    try {
      const payload = z
        .object({
          sessionId: z.string().min(1),
          streamId: z.string().min(1),
          correlationId: z.string().min(1),
          questionId: z.string().optional(),
          startedAt: z.string().datetime(),
          mimeType: z.string().min(1)
        })
        .parse(req.body);
      if (payload.sessionId !== req.params.sessionId || payload.streamId !== req.params.streamId) {
        const result = fail("MEDIA_ROUTE_MISMATCH", "Route sessionId/streamId must match request body.");
        return res.status(result.status).json(result.body);
      }
      res.json(ok(await startVideoStream(payload)));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid video stream start request");
        return res.status(result.status).json(result.body);
      }
      const result = fail("VIDEO_STREAM_START_FAILED", error instanceof Error ? error.message : "Video stream start failed");
      return res.status(result.status).json(result.body);
    }
  });

  router.post(
    "/media/:sessionId/video/:streamId/segments/:sequence",
    express.raw({ type: "application/octet-stream", limit: VIDEO_MAX_SEGMENT_BYTES }),
    async (req, res) => {
      try {
        const sequence = Number.parseInt(req.params.sequence, 10);
        if (!Number.isSafeInteger(sequence) || sequence < 0) {
          const result = fail("MEDIA_BAD_SEQUENCE", "Segment sequence must be a non-negative integer.");
          return res.status(result.status).json(result.body);
        }
        if (!Buffer.isBuffer(req.body)) {
          const result = fail("MEDIA_BAD_CONTENT_TYPE", "Video segments must use application/octet-stream.");
          return res.status(result.status).json(result.body);
        }
        const metadata = {
          sessionId: req.params.sessionId,
          streamId: req.params.streamId,
          correlationId: String(req.header("x-correlation-id") ?? ""),
          sequence,
          capturedAt: String(req.header("x-captured-at") ?? new Date().toISOString()),
          durationMs: Number.parseInt(String(req.header("x-duration-ms") ?? "0"), 10),
          byteLength: req.body.byteLength,
          mimeType: String(req.header("x-video-mime-type") ?? "video/webm")
        };
        const parsedMetadata = z
          .object({
            sessionId: z.string().min(1),
            streamId: z.string().min(1),
            correlationId: z.string().min(1),
            sequence: z.number().int().nonnegative(),
            capturedAt: z.string().datetime(),
            durationMs: z.number().int().nonnegative(),
            byteLength: z.number().int().nonnegative(),
            mimeType: z.string().min(1)
          })
          .parse(metadata);
        res.json(ok(await receiveVideoSegment(parsedMetadata, req.body)));
      } catch (error) {
        if (error instanceof ZodError) {
          const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid video segment metadata");
          return res.status(result.status).json(result.body);
        }
        const result = fail("VIDEO_SEGMENT_FAILED", error instanceof Error ? error.message : "Video segment failed");
        return res.status(result.status).json(result.body);
      }
    }
  );

  router.post(
    "/media/:sessionId/video/:streamId/thumbnail",
    express.raw({ type: "application/octet-stream", limit: 256 * 1024 }),
    async (req, res) => {
      try {
        if (!Buffer.isBuffer(req.body)) {
          const result = fail("MEDIA_BAD_CONTENT_TYPE", "Video thumbnail must use application/octet-stream.");
          return res.status(result.status).json(result.body);
        }
        const payload = z
          .object({
            correlationId: z.string().min(1),
            mimeType: z.string().min(1)
          })
          .parse({
            correlationId: String(req.header("x-correlation-id") ?? ""),
            mimeType: String(req.header("x-thumbnail-mime-type") ?? "image/jpeg")
          });
        const result = await uploadVideoThumbnail({
          sessionId: req.params.sessionId,
          streamId: req.params.streamId,
          correlationId: payload.correlationId,
          thumbnail: req.body,
          mimeType: payload.mimeType
        });
        res.json(ok(result));
      } catch (error) {
        if (error instanceof ZodError) {
          const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid video thumbnail request");
          return res.status(result.status).json(result.body);
        }
        const result = fail("VIDEO_THUMBNAIL_FAILED", error instanceof Error ? error.message : "Video thumbnail failed");
        return res.status(result.status).json(result.body);
      }
    }
  );

  router.post("/media/:sessionId/video/:streamId/finish", async (req, res) => {
    try {
      const payload = videoStreamFinishSchema.parse(req.body);
      if (payload.sessionId !== req.params.sessionId || payload.streamId !== req.params.streamId) {
        const result = fail("MEDIA_ROUTE_MISMATCH", "Route sessionId/streamId must match request body.");
        return res.status(result.status).json(result.body);
      }
      res.json(ok(await finishVideoStream(payload)));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid video stream finish request");
        return res.status(result.status).json(result.body);
      }
      const result = fail("VIDEO_STREAM_FINISH_FAILED", error instanceof Error ? error.message : "Video stream finish failed");
      return res.status(result.status).json(result.body);
    }
  });

  router.get("/media/:sessionId/video/:streamId", (req, res) => {
    const summary = getVideoStreamSummary(req.params.sessionId, req.params.streamId);
    if (!summary) {
      const result = fail("VIDEO_STREAM_NOT_FOUND", "Video stream not found.", 404);
      return res.status(result.status).json(result.body);
    }
    return res.json(ok(summary));
  });

  return router;
}
