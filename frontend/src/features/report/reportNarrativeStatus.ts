import type { TrainingReport } from "../../types";

export function isNarrativePending(report: TrainingReport | null | undefined) {
  return report?.professionalReportV2?.narrative?.status === "PENDING";
}
