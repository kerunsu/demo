import type { SessionMediaManifest } from "child-education-training-demo/shared/raw-media";

export type QuestionVideoCaptureStatus = {
  captured: boolean;
  segmentCount: number;
  receivedBytes: number;
};

export function buildPerQuestionVideoCaptureStatus(
  manifest: SessionMediaManifest | null,
  questionIds: string[]
): Map<string, QuestionVideoCaptureStatus> {
  const bestByQuestion = new Map<string, QuestionVideoCaptureStatus>();

  for (const stream of Object.values(manifest?.video ?? {})) {
    if (!stream.questionId) continue;
    const segmentCount = stream.segments?.length ?? 0;
    const receivedBytes = stream.receivedBytes ?? 0;
    const captured = segmentCount > 0 || Boolean(stream.mergedRelativePath);
    const next: QuestionVideoCaptureStatus = { captured, segmentCount, receivedBytes };
    const existing = bestByQuestion.get(stream.questionId);
    if (!existing || next.receivedBytes > existing.receivedBytes) {
      bestByQuestion.set(stream.questionId, next);
    }
  }

  return new Map(
    questionIds.map((questionId) => {
      const status = bestByQuestion.get(questionId);
      return [
        questionId,
        status ?? {
          captured: manifest ? false : true,
          segmentCount: 0,
          receivedBytes: 0
        }
      ] as const;
    })
  );
}

export function isQuestionVideoCaptured(status: QuestionVideoCaptureStatus | undefined, manifestAvailable: boolean) {
  if (!manifestAvailable) return true;
  return status?.captured ?? false;
}
