import {
  type BuildPageContextInput,
  buildPageContextText,
  VOICE_PARTNER_MAX_SCREENSHOT_BYTES,
  type VoiceTurnPageContextPayload,
  type VoiceTurnScreenshot
} from "child-education-training-demo/shared/voice-partner-contract";
import type { CourseQuestion } from "../../types";

export type { BuildPageContextInput };
export { buildPageContextText };

export type PageContextBuildInput = {
  question: CourseQuestion;
  wrongAttempts: number;
  helpRequestCount?: number;
  questionElapsedMs: number;
  selectedOptionIds: string[];
};

export function toBuildPageContextInput(input: PageContextBuildInput): BuildPageContextInput {
  return {
    courseType: input.question.courseType,
    questionIndex: input.question.index,
    totalQuestions: input.question.total,
    prompt: input.question.prompt,
    target: input.question.payload.target,
    targetDescription: input.question.payload.targetDescription,
    targetImageUrl: input.question.payload.targetImageUrl,
    options: input.question.payload.options.map((option) => ({
      id: option.id,
      label: option.label,
      imageUrl: option.imageUrl,
      description: option.description
    })),
    correctOptionId: input.question.payload.correctOptionId,
    wrongAttempts: input.wrongAttempts,
    helpRequestCount: input.helpRequestCount,
    questionElapsedMs: input.questionElapsedMs,
    selectedOptionIds: input.selectedOptionIds
  };
}

export async function captureTrainingScreenshot(
  root: HTMLElement | null,
  maxBytes = VOICE_PARTNER_MAX_SCREENSHOT_BYTES
): Promise<Pick<VoiceTurnPageContextPayload, "screenshot" | "screenshotUnavailableReason">> {
  if (!root) {
    return { screenshot: null, screenshotUnavailableReason: "ROOT_NOT_FOUND" };
  }
  const rect = root.getBoundingClientRect();
  const width = Math.min(Math.max(1, Math.round(rect.width)), 800);
  const height = Math.min(Math.max(1, Math.round(rect.height)), 600);
  if (width < 10 || height < 10) {
    return { screenshot: null, screenshotUnavailableReason: "ROOT_TOO_SMALL" };
  }

  try {
    const scale = Math.min(1, 800 / width, 600 / height);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return { screenshot: null, screenshotUnavailableReason: "CANVAS_UNAVAILABLE" };
    }

    const serialized = root.innerHTML.replace(/`/g, "\\`");
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${canvas.width}" height="${canvas.height}">
      <foreignObject width="100%" height="100%">
        <div xmlns="http://www.w3.org/1999/xhtml" style="transform:scale(${scale});transform-origin:top left;width:${width}px;height:${height}px">
          ${serialized}
        </div>
      </foreignObject>
    </svg>`;
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
    const img = new Image();
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("svg render failed"));
      img.src = url;
    });
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(url);

    const dataUrl = canvas.toDataURL("image/jpeg", 0.72);
    const base64 = dataUrl.split(",")[1] ?? "";
    if (!base64) {
      return { screenshot: null, screenshotUnavailableReason: "ENCODE_FAILED" };
    }
    if (Math.ceil(base64.length * 0.75) > maxBytes) {
      return { screenshot: null, screenshotUnavailableReason: "SCREENSHOT_TOO_LARGE" };
    }

    const screenshot: VoiceTurnScreenshot = {
      mimeType: "image/jpeg",
      base64,
      width: canvas.width,
      height: canvas.height
    };
    return { screenshot, screenshotUnavailableReason: undefined };
  } catch {
    return { screenshot: null, screenshotUnavailableReason: "CAPTURE_FAILED" };
  }
}

export async function buildPageContextPayload(input: PageContextBuildInput, root: HTMLElement | null) {
  const text = buildPageContextText(toBuildPageContextInput(input));
  const capture = await captureTrainingScreenshot(root);
  return {
    text,
    screenshot: capture.screenshot,
    screenshotUnavailableReason: capture.screenshotUnavailableReason
  } satisfies VoiceTurnPageContextPayload;
}
