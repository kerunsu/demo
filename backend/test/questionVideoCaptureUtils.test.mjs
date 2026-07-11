import assert from "node:assert/strict";
import test from "node:test";
import "./testEnv.mjs";

import { buildPerQuestionVideoCaptureStatus } from "../dist/services/questionVideoCaptureUtils.js";
import { buildQuestionAttentionCurve } from "../dist/services/reportScoringService.js";

test("buildPerQuestionVideoCaptureStatus marks empty segment streams as not captured", () => {
  const statuses = buildPerQuestionVideoCaptureStatus(
    {
      schemaVersion: "raw-media-manifest-v1",
      sessionId: "sess_video_flags",
      createdAt: "2026-06-15T00:00:00.000Z",
      updatedAt: "2026-06-15T00:00:00.000Z",
      audio: {},
      video: {
        "camera-stream-a": {
          streamId: "camera-stream-a",
          correlationId: "camera:sess:matching_q_1",
          questionId: "matching_q_1",
          status: "finished",
          startedAt: "2026-06-15T00:00:00.000Z",
          segments: [{ sequence: 0, relativePath: "video/a/segment-0000.webm", byteLength: 100, capturedAt: "2026-06-15T00:00:01.000Z" }],
          missingSequences: [],
          receivedBytes: 100,
          mergedRelativePath: "video/a/merged.webm"
        },
        "camera-stream-b": {
          streamId: "camera-stream-b",
          correlationId: "camera:sess:matching_q_2",
          questionId: "matching_q_2",
          status: "finished",
          startedAt: "2026-06-15T00:00:02.000Z",
          segments: [],
          missingSequences: [],
          receivedBytes: 0,
          thumbnailRelativePath: "video/b/thumbnail.jpg"
        }
      }
    },
    ["matching_q_1", "matching_q_2", "matching_q_3"]
  );

  assert.equal(statuses.get("matching_q_1")?.captured, true);
  assert.equal(statuses.get("matching_q_2")?.captured, false);
  assert.equal(statuses.get("matching_q_3")?.captured, false);
});

test("buildQuestionAttentionCurve excludes questions without captured video", () => {
  const curve = buildQuestionAttentionCurve({
    courseType: "matching",
    totalQuestions: 3,
    accuracy: 1,
    averageResponseTimeMs: 1500,
    sessionId: "sess_curve",
    rawMediaManifestAvailable: true,
    questionVideoCapture: new Map([
      ["matching_q_1", { captured: true, segmentCount: 1, receivedBytes: 100 }],
      ["matching_q_2", { captured: false, segmentCount: 0, receivedBytes: 0 }],
      ["matching_q_3", { captured: true, segmentCount: 1, receivedBytes: 120 }]
    ]),
    questionAttention: [
      { questionId: "matching_q_1", score: 90, quality: "complete" },
      { questionId: "matching_q_2", score: 0, quality: "excluded_no_video" },
      { questionId: "matching_q_3", score: 88, quality: "complete" }
    ],
    assessment: {
      metricVersion: "deterministic-assessment-v1",
      scoringStatus: "OWNER_REQUIRED_BEFORE_SCORING",
      questionMetrics: [
        { questionId: "matching_q_1", dataQuality: { status: "complete" } },
        { questionId: "matching_q_2", dataQuality: { status: "complete" } },
        { questionId: "matching_q_3", dataQuality: { status: "complete" } }
      ]
    },
    expandedReport: {
      answerMetrics: {
        totalQuestions: 3,
        questionMetrics: [
          { questionId: "matching_q_1", dataQualityStatus: "complete" },
          { questionId: "matching_q_2", dataQualityStatus: "complete" },
          { questionId: "matching_q_3", dataQualityStatus: "complete" }
        ]
      },
      attentionMetrics: { status: "available", qualityStatus: "complete" },
      languageMetrics: { status: "available" },
      dataQuality: { limitations: [] }
    }
  });

  assert.deepEqual(
    curve.map((point) => point.questionId),
    ["matching_q_1", "matching_q_3"]
  );
});
