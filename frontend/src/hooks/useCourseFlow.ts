import { useCallback, useMemo, useRef, useState } from "react";
import type { AppPage, CourseOption, CourseQuestion, CourseType, SessionInfo, TrainingReport } from "../types";
import { generateReport, getCurrentQuestion, getReport, startSession, submitAnswer } from "../services/trainingService";
import { ensureRawMediaConsent } from "../services/rawMediaService";
import { mergeProfessionalReportV2 } from "../features/report/mergeProfessionalReport";
import { waitForQuestionTransition } from "../features/training/questionTransition";

export type OptionVisualState = "normal" | "wrong" | "correct" | "dimmed" | "hint";
export type CourseStarQuality = "off" | "perfect" | "retry";

type CourseReportMap = Record<CourseType, TrainingReport | null>;

type UseCourseFlowArgs = {
  childName: string;
  courseOptions: CourseOption[];
  onPageChange: (page: AppPage) => void;
  onCourseStarted?: () => void;
  onAnswerFeedback?: (input: {
    question: CourseQuestion;
    selectedOptionId: string;
    correct: boolean;
    courseCompleted: boolean;
    correctOptionId?: string;
    wrongAttemptsAfter: number;
  }) => void;
  onVoiceReset?: () => void;
};

function createEmptyCourseReports(): CourseReportMap {
  return { matching: null, ordering: null };
}

function createEmptyCourseStars(): Record<CourseType, CourseStarQuality[]> {
  return { matching: [], ordering: [] };
}

function createEmptyCourseTotals(): Record<CourseType, number> {
  return { matching: 0, ordering: 0 };
}

function mergeTrainingReports(reports: TrainingReport[]): TrainingReport {
  if (reports.length === 0) {
    throw new Error("没有可合并的报告数据");
  }
  if (reports.length === 1) return reports[0];

  const totalQuestions = reports.reduce((sum, item) => sum + item.summary.totalQuestions, 0);
  const correctAnswers = reports.reduce((sum, item) => sum + item.summary.correctAnswers, 0);
  const totalWrongAttempts = reports.reduce((sum, item) => sum + item.errorStats.totalWrongAttempts, 0);
  const responseTimeSum = reports.reduce((sum, item) => sum + item.summary.averageResponseTimeMs * item.summary.totalQuestions, 0);
  const avgResponse = totalQuestions > 0 ? responseTimeSum / totalQuestions : 0;
  const byTypeMap = new Map<string, number>();

  for (const item of reports) {
    for (const entry of item.errorStats.byType) {
      byTypeMap.set(entry.errorType, (byTypeMap.get(entry.errorType) ?? 0) + entry.count);
    }
  }

  const startedAt = reports
    .map((item) => item.startedAt)
    .sort((a, b) => new Date(a).getTime() - new Date(b).getTime())[0];
  const completedAt = reports
    .map((item) => item.completedAt)
    .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0];
  const generatedAt = new Date().toISOString();
  const allExpanded = reports.flatMap((item) => item.expandedReport ? [item.expandedReport] : []);
  const qualityLimitations = Array.from(
    new Set(allExpanded.flatMap((item) => item.dataQuality.limitations))
  );

  return {
    reportId: `mixed-${reports.map((item) => item.reportId.slice(0, 8)).join("-")}`,
    sessionId: reports[reports.length - 1].sessionId,
    courseType: "mixed",
    startedAt,
    completedAt,
    durationSec: reports.reduce((sum, item) => sum + item.durationSec, 0),
    summary: {
      totalQuestions,
      correctAnswers,
      accuracy: totalQuestions > 0 ? correctAnswers / totalQuestions : 0,
      averageResponseTimeMs: avgResponse
    },
    errorStats: {
      totalWrongAttempts,
      byType: Array.from(byTypeMap.entries()).map(([errorType, count]) => ({ errorType, count }))
    },
    questionResults: reports.flatMap((item) => item.questionResults),
    chatSummary: {
      totalMessages: reports.reduce((sum, item) => sum + item.chatSummary.totalMessages, 0),
      childMessageCount: reports.reduce((sum, item) => sum + item.chatSummary.childMessageCount, 0),
      botMessageCount: reports.reduce((sum, item) => sum + item.chatSummary.botMessageCount, 0),
      keywords: Array.from(new Set(reports.flatMap((item) => item.chatSummary.keywords))),
      highlights: Array.from(new Set(reports.flatMap((item) => item.chatSummary.highlights)))
    },
    expandedReport: {
      schemaVersion: "m6-expanded-report-v1",
      metricVersion: "m6-expanded-report-metrics-v1",
      answerMetrics: {
        totalQuestions,
        firstTryCorrect: correctAnswers,
        firstTryAccuracy: totalQuestions > 0 ? correctAnswers / totalQuestions : 0,
        eventualCorrect: reports.reduce((sum, item) => sum + (item.expandedReport?.answerMetrics.eventualCorrect ?? item.summary.correctAnswers), 0),
        eventualAccuracy: totalQuestions > 0
          ? reports.reduce((sum, item) => sum + (item.expandedReport?.answerMetrics.eventualCorrect ?? item.summary.correctAnswers), 0) / totalQuestions
          : 0,
        averageResponseTimeMs: avgResponse,
        medianResponseTimeMs: undefined,
        totalWrongAttempts,
        wrongAttemptsByType: Object.fromEntries(byTypeMap.entries()),
        questionMetrics: allExpanded.flatMap((item) => item.answerMetrics.questionMetrics)
      },
      attentionMetrics: {
        status: allExpanded.some((item) => item.attentionMetrics.status === "available") ? "available" : "unavailable",
        observedMs: allExpanded.reduce((sum, item) => sum + item.attentionMetrics.observedMs, 0),
        screenOrientedRatio: undefined,
        unavailableMs: allExpanded.reduce((sum, item) => sum + item.attentionMetrics.unavailableMs, 0),
        qualityStatus: allExpanded.some((item) => item.attentionMetrics.qualityStatus !== "complete") ? "partial" : "complete"
      },
      languageMetrics: {
        status: allExpanded.some((item) => item.languageMetrics.status === "available") ? "available" : "unavailable",
        responseCount: allExpanded.reduce((sum, item) => sum + item.languageMetrics.responseCount, 0),
        emptyResponseCount: allExpanded.reduce((sum, item) => sum + item.languageMetrics.emptyResponseCount, 0),
        repeatedResponseCount: allExpanded.reduce((sum, item) => sum + item.languageMetrics.repeatedResponseCount, 0),
        averageTranscriptLength: undefined,
        qualityStatus: allExpanded.some((item) => item.languageMetrics.qualityStatus !== "complete") ? "partial" : "complete"
      },
      dataQuality: {
        status: qualityLimitations.length > 0 ? "partial" : "complete",
        limitations: qualityLimitations,
        environmentPending: Array.from(new Set(allExpanded.flatMap((item) => item.dataQuality.environmentPending)))
      },
      evidence: {
        totalReferences: allExpanded.reduce((sum, item) => sum + item.evidence.totalReferences, 0),
        byType: allExpanded.reduce<Record<string, number>>((acc, item) => {
          for (const [type, count] of Object.entries(item.evidence.byType)) {
            acc[type] = (acc[type] ?? 0) + count;
          }
          return acc;
        }, {}),
        providerSummary: allExpanded.reduce<Record<string, number>>((acc, item) => {
          for (const [provider, count] of Object.entries(item.evidence.providerSummary ?? {})) {
            acc[provider] = (acc[provider] ?? 0) + count;
          }
          return acc;
        }, {}),
        sample: allExpanded.flatMap((item) => item.evidence.sample).slice(0, 8)
      },
      versions: {
        reportVersion: "v1",
        assessmentSchemaVersion: "mixed",
        assessmentMetricVersion: "deterministic-assessment-v1",
        assessmentAlgorithmVersion: "mixed-course-merge-v1",
        reportExplanationPolicyVersion: "m6-report-explanation-rule-v1"
      },
      history: {
        generatedAt,
        assessmentCreatedAt: generatedAt,
        trendBaseline: "single_session_only",
        previousReportCount: 0
      },
      trends: {
        status: "baseline_only",
        reasonCode: "NO_PRIOR_REPORT_HISTORY",
        items: []
      },
      safeExplanations: [
        {
          section: "answers",
          text: `First-try accuracy is ${(totalQuestions > 0 ? (correctAnswers / totalQuestions) * 100 : 0).toFixed(0)}%. This is a training-performance metric, not a professional score.`,
          reviewStatus: "PASS",
          policyVersion: "m6-report-explanation-rule-v1"
        },
        {
          section: "attention",
          text: "Mixed-course attention metrics preserve source data-quality flags and avoid unsupported interpretation.",
          reviewStatus: "PASS",
          policyVersion: "m6-report-explanation-rule-v1"
        },
        {
          section: "language",
          text: "Mixed-course language metrics use derived features only and do not include raw child text.",
          reviewStatus: "PASS",
          policyVersion: "m6-report-explanation-rule-v1"
        },
        {
          section: "data_quality",
          text: "Mixed-course report data is merged for display; per-course reports remain the source for individual assessment metadata.",
          reviewStatus: "PASS",
          policyVersion: "m6-report-explanation-rule-v1"
        }
      ],
      exportBoundary: {
        jsonReady: true,
        printReady: true,
        containsRawAudio: false,
        containsRawVideo: false,
        containsRawChatText: false,
        allowedFormats: ["json", "browser_print"]
      },
      degradation: {
        fallbackUsed: true,
        reasonCodes: ["MIXED_REPORT_HAS_NO_SINGLE_ASSESSMENT_ID", ...qualityLimitations]
      }
    },
    professionalReportV2: mergeProfessionalReportV2(reports),
    generatedAt,
    version: "v1"
  };
}

export function useCourseFlow({
  childName,
  courseOptions,
  onPageChange,
  onCourseStarted,
  onAnswerFeedback,
  onVoiceReset
}: UseCourseFlowArgs) {
  const [selectedCourses, setSelectedCourses] = useState<CourseType[]>(["matching"]);
  const [courseQueue, setCourseQueue] = useState<CourseType[]>([]);
  const [activeCourseIndex, setActiveCourseIndex] = useState(0);
  const [courseStars, setCourseStars] = useState<Record<CourseType, CourseStarQuality[]>>(createEmptyCourseStars);
  const [courseQuestionTotals, setCourseQuestionTotals] = useState<Record<CourseType, number>>(createEmptyCourseTotals);
  const [currentQuestionWrongAttempts, setCurrentQuestionWrongAttempts] = useState(0);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [question, setQuestion] = useState<CourseQuestion | null>(null);
  const [questionStartAt, setQuestionStartAt] = useState<number>(0);
  const [feedback, setFeedback] = useState<string>("");
  const [hint, setHint] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");
  const [report, setReport] = useState<TrainingReport | null>(null);
  const [optionStates, setOptionStates] = useState<Record<string, OptionVisualState>>({});
  const [flashBg, setFlashBg] = useState(false);
  const courseReportsRef = useRef<CourseReportMap>(createEmptyCourseReports());

  const queuedCourses = useMemo(() => {
    if (courseQueue.length > 0) return courseQueue;
    if (session?.courseType) return [session.courseType];
    return [];
  }, [courseQueue, session]);

  async function startCourseTraining(courseType: CourseType, moveToTrainingPage: boolean) {
    const created = await startSession({
      childName,
      courseType
    });
    window.localStorage.setItem("m3.activeSessionId", created.sessionId);
    await ensureRawMediaConsent(created.sessionId).catch(() => undefined);
    setSession(created);
    const firstQuestion = await getCurrentQuestion(created.sessionId);
    const total = Math.max(0, firstQuestion.total);
    setCourseQuestionTotals((prev) => ({ ...prev, [courseType]: total }));
    setCourseStars((prev) => ({ ...prev, [courseType]: Array.from({ length: total }, () => "off" as CourseStarQuality) }));
    setCurrentQuestionWrongAttempts(0);
    setQuestion(firstQuestion);
    setOptionStates({});
    setQuestionStartAt(Date.now());
    setFeedback("");
    setHint("");
    onCourseStarted?.();
    if (moveToTrainingPage) {
      onPageChange("training");
    }
  }

  function updateCourseReport(courseType: CourseType, nextReport: TrainingReport) {
    const nextMap: CourseReportMap = { ...courseReportsRef.current, [courseType]: nextReport };
    courseReportsRef.current = nextMap;
  }

  async function handleStartTraining() {
    if (selectedCourses.length === 0) return;

    setError("");
    setLoading(true);
    try {
      const orderedQueue = courseOptions.map((course) => course.type).filter((type) => selectedCourses.includes(type));
      if (orderedQueue.length === 0) {
        throw new Error("请至少选择一门课程");
      }
      courseReportsRef.current = createEmptyCourseReports();
      setCourseQueue(orderedQueue);
      setActiveCourseIndex(0);
      await startCourseTraining(orderedQueue[0], true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "启动失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectAnswer(selectedOptionId: string) {
    if (!session || !question) return;
    setLoading(true);
    setError("");
    try {
      const result = await submitAnswer(
        session.sessionId,
        question.questionId,
        selectedOptionId,
        Date.now() - questionStartAt
      );
      setFeedback(result.feedback);
      setHint(result.hint ?? "");
      onAnswerFeedback?.({
        question,
        selectedOptionId,
        correct: result.correct,
        courseCompleted: result.courseCompleted,
        correctOptionId: result.correctOptionId,
        wrongAttemptsAfter: result.correct ? currentQuestionWrongAttempts : currentQuestionWrongAttempts + 1
      });

      if (result.courseCompleted) {
        if (result.correct) {
          const courseType = question.courseType;
          const starIndex = Math.max(0, question.index - 1);
          const quality: CourseStarQuality = currentQuestionWrongAttempts === 0 ? "perfect" : "retry";
          setCourseStars((prev) => {
            const current = [...(prev[courseType] ?? [])];
            if (current.length > starIndex) current[starIndex] = quality;
            return { ...prev, [courseType]: current };
          });
        }
        setOptionStates((prev) => ({ ...prev, [selectedOptionId]: result.correct ? "correct" : "wrong" }));
        await generateReport(session.sessionId);
        const generated = await getReport(session.sessionId);
        updateCourseReport(question.courseType, generated);

        const nextCourseIndex = activeCourseIndex + 1;
        const hasNextCourse = nextCourseIndex < courseQueue.length;

        if (hasNextCourse) {
          await waitForQuestionTransition();
          setActiveCourseIndex(nextCourseIndex);
          setCurrentQuestionWrongAttempts(0);
          await startCourseTraining(courseQueue[nextCourseIndex], false);
          return;
        }

        const orderedReports = courseQueue
          .map((courseType) => courseReportsRef.current[courseType])
          .filter((item): item is TrainingReport => item !== null);
        const finalReport = mergeTrainingReports(orderedReports);
        setReport(finalReport);
        onPageChange("report");
        return;
      }

      if (result.correct) {
        const courseType = question.courseType;
        const starIndex = Math.max(0, question.index - 1);
        const quality: CourseStarQuality = currentQuestionWrongAttempts === 0 ? "perfect" : "retry";
        setCourseStars((prev) => {
          const current = [...(prev[courseType] ?? [])];
          if (current.length > starIndex) current[starIndex] = quality;
          return { ...prev, [courseType]: current };
        });
        setOptionStates((prev) => ({ ...prev, [selectedOptionId]: "correct" }));
        setFlashBg(true);
        setTimeout(() => setFlashBg(false), 900);
        await waitForQuestionTransition();
        const nextQuestion = await getCurrentQuestion(session.sessionId);
        setQuestion(nextQuestion);
        setCurrentQuestionWrongAttempts(0);
        setOptionStates({});
        setQuestionStartAt(Date.now());
        setFeedback("");
        setHint("");
        return;
      } else {
        setCurrentQuestionWrongAttempts((prev) => prev + 1);
        setOptionStates((prev) => {
          const next: Record<string, OptionVisualState> = { ...prev, [selectedOptionId]: "wrong" };
          if (result.hint && result.correctOptionId) {
            for (const option of question.payload.options) {
              if (next[option.id] === "wrong") continue;
              next[option.id] = option.id === result.correctOptionId ? "hint" : "dimmed";
            }
          }
          return next;
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "答题失败");
    } finally {
      setLoading(false);
    }
  }

  function resetCourseFlow(targetPage: AppPage) {
    setSession(null);
    setQuestion(null);
    setReport(null);
    setFeedback("");
    setHint("");
    setOptionStates({});
    setFlashBg(false);
    setCourseQueue([]);
    setActiveCourseIndex(0);
    courseReportsRef.current = createEmptyCourseReports();
    setCourseQuestionTotals(createEmptyCourseTotals());
    setCourseStars(createEmptyCourseStars());
    setCurrentQuestionWrongAttempts(0);
    onVoiceReset?.();
    setError("");
    onPageChange(targetPage);
  }

  function handleToggleCourse(courseType: CourseType) {
    setSelectedCourses((prev) =>
      prev.includes(courseType) ? prev.filter((type) => type !== courseType) : [...prev, courseType]
    );
  }

  const refreshMergedReport = useCallback(async () => {
    const orderedCourseTypes =
      courseQueue.length > 0 ? courseQueue : session?.courseType ? [session.courseType] : [];
    const orderedReports = orderedCourseTypes
      .map((courseType) => courseReportsRef.current[courseType])
      .filter((item): item is TrainingReport => item !== null);
    if (orderedReports.length === 0) return report;

    const freshReports = await Promise.all(orderedReports.map((item) => getReport(item.sessionId)));
    freshReports.forEach((item, index) => {
      updateCourseReport(orderedCourseTypes[index], item);
    });
    const mergedReports = orderedCourseTypes
      .map((courseType) => courseReportsRef.current[courseType])
      .filter((item): item is TrainingReport => item !== null);
    const merged = mergedReports.length === 1 ? mergedReports[0] : mergeTrainingReports(mergedReports);
    setReport(merged);
    return merged;
  }, [courseQueue, report, session?.courseType]);

  return {
    activeCourseIndex,
    courseQuestionTotals,
    courseQueue,
    courseStars,
    error,
    feedback,
    flashBg,
    handleSelectAnswer,
    handleStartTraining,
    handleToggleCourse,
    hint,
    loading,
    optionStates,
    currentQuestionWrongAttempts,
    questionStartAt,
    question,
    queuedCourses,
    report,
    refreshMergedReport,
    resetToSelect: () => resetCourseFlow("select"),
    resetToWelcome: () => resetCourseFlow("welcome"),
    selectedCourses,
    session,
    setError
  };
}
