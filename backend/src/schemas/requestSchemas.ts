import { z } from "zod";

export const startSessionSchema = z.object({
  childName: z.string().min(1).max(20).default("小朋友"),
  courseType: z.enum(["matching", "ordering"])
});

export const answerSchema = z.object({
  questionId: z.string().min(1),
  answer: z.object({
    selectedOptionId: z.string().min(1)
  }),
  responseTimeMs: z.number().nonnegative()
});

export const chatPageContextSchema = z.object({
  schemaVersion: z.literal("voice-page-context-v1"),
  courseType: z.enum(["matching", "ordering"]),
  questionIndex: z.number().int().positive(),
  totalQuestions: z.number().int().positive(),
  prompt: z.string().min(1).max(500),
  target: z.string().min(1).max(300),
  targetDescription: z.string().max(800).optional(),
  targetImageUrl: z.string().max(500).optional(),
  options: z
    .array(
      z.object({
        id: z.string().min(1).max(100),
        label: z.string().min(1).max(300),
        imageUrl: z.string().max(500).optional(),
        description: z.string().max(800).optional()
      })
    )
    .max(12),
  interaction: z.object({
    selectedOptionIds: z.array(z.string().min(1).max(100)).max(12),
    wrongAttempts: z.number().int().nonnegative().max(20),
    helpRequestCount: z.number().int().nonnegative().max(20).optional(),
    elapsedMs: z.number().nonnegative().max(60 * 60 * 1000)
  }),
  correctOption: z
    .object({
      id: z.string().min(1).max(100),
      label: z.string().min(1).max(300),
      position: z.number().int().positive().max(12),
      description: z.string().max(800).optional()
    })
    .optional(),
  narrative: z.string().min(1).max(1500)
});

export const chatMessageSchema = z.object({
  text: z.string().min(1).max(120),
  pageContext: chatPageContextSchema.optional()
});
