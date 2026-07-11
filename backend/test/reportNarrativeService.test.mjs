import assert from "node:assert/strict";
import test from "node:test";

import { MockReportNarrativeLlmProvider } from "../dist/services/reportNarrativeLlmProvider.js";
import { buildRuleFallbackNarrative, generateReportNarrative } from "../dist/services/reportNarrativeService.js";

const narrativeInput = {
  sessionId: "sess_narrative",
  totalQuestions: 5,
  accuracy: 0.6,
  averageResponseTimeMs: 1800,
  dimensions: {
    ordering: 0,
    matching: 72,
    receptiveLanguage: 68,
    attention: 55,
    expressiveLanguage: 61,
    overallScore: 63
  },
  emotionSummary: {
    status: "AVAILABLE",
    positiveRatio: 0.45,
    focusedRatio: 0.4,
    frustratedRatio: 0.15
  },
  attentionDipQuestions: ["matching_q_3"],
  wrongAttempts: 2,
  limitations: ["PARTIAL_INPUT"]
};

test("report narrative generator returns mock llm output with safety pass", async () => {
  const narrative = await generateReportNarrative(narrativeInput, {
    providerOverride: new MockReportNarrativeLlmProvider("success")
  });
  assert.equal(narrative.safetyReviewStatus, "PASS");
  assert.equal(narrative.status, "READY");
  assert.equal(narrative.generator, "mock_llm");
  assert.ok(narrative.analysis.length > 20);
  assert.equal(narrative.recommendations.length, 3);
  assert.equal(JSON.stringify(narrative).includes("percentile"), false);
  assert.ok(narrative.recommendations[0].includes("排序"));
  assert.ok(narrative.recommendations.some((item) => item.includes("错误尝试")));
});

test("report narrative uses llm recommendations instead of rule template strings", async () => {
  const narrative = await generateReportNarrative(narrativeInput, {
    providerOverride: new MockReportNarrativeLlmProvider("success")
  });
  const fallback = buildRuleFallbackNarrative(narrativeInput);
  assert.notDeepEqual(narrative.recommendations, fallback.recommendations);
});

test("unsafe llm narrative falls back to rule template", async () => {
  const narrative = await generateReportNarrative(narrativeInput, {
    providerOverride: new MockReportNarrativeLlmProvider("unsafe")
  });
  assert.equal(narrative.generator, "rule_fallback");
  assert.equal(narrative.status, "READY");
  assert.equal(narrative.provider, "rule-narrative");
  assert.equal(JSON.stringify(narrative).includes("diagnosis"), false);
});

test("rule provider override returns rule fallback narrative", async () => {
  const narrative = await generateReportNarrative(narrativeInput, {
    providerOverride: null
  });
  assert.equal(narrative.generator, "rule_fallback");
  assert.ok(narrative.analysis.includes("教育训练参考"));
});

test("rule fallback narrative avoids unsafe professional claims", () => {
  const narrative = buildRuleFallbackNarrative(narrativeInput);
  assert.equal(narrative.generator, "rule_fallback");
  assert.equal(JSON.stringify(narrative).includes("diagnosis"), false);
  assert.ok(narrative.analysis.includes("教育训练参考"));
});
