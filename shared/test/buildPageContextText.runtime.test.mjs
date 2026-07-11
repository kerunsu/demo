import assert from "node:assert/strict";
import { test } from "node:test";

test("buildPageContextText includes narrative and interaction", async () => {
  const { buildPageContextText } = await import("child-education-training-demo/shared/voice-partner-contract");
  const text = buildPageContextText({
    courseType: "matching",
    questionIndex: 2,
    totalQuestions: 5,
    prompt: "请找出相同的水果",
    target: "苹果",
    targetImageUrl: "/matching/apple.png",
    options: [
      { id: "a", label: "苹果", imageUrl: "/matching/apple.png" },
      { id: "b", label: "香蕉", imageUrl: "/matching/banana.png" }
    ],
    wrongAttempts: 1,
    questionElapsedMs: 4200,
    selectedOptionIds: ["b"]
  });

  assert.equal(text.schemaVersion, "voice-page-context-v1");
  assert.equal(text.courseType, "matching");
  assert.match(text.narrative, /配对题/);
  assert.match(text.narrative, /香蕉/);
  assert.equal(text.interaction.wrongAttempts, 1);
  assert.deepEqual(text.interaction.selectedOptionIds, ["b"]);
});
