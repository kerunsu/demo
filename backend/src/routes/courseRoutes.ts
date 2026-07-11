import { Router } from "express";
import { ZodError } from "zod";
import { answerSchema } from "../schemas/requestSchemas.js";
import { getCurrentQuestion, submitAnswer } from "../services/sessionService.js";
import { fail, ok } from "./response.js";

export function createCourseRoutes() {
  const router = Router();

  router.get("/course/:sessionId/current", (req, res) => {
    try {
      const data = getCurrentQuestion(req.params.sessionId);
      res.json(ok(data));
    } catch (error) {
      const result = fail("QUESTION_NOT_FOUND", error instanceof Error ? error.message : "Question not found", 404);
      res.status(result.status).json(result.body);
    }
  });

  router.post("/course/:sessionId/answer", (req, res) => {
    try {
      const payload = answerSchema.parse(req.body);
      const data = submitAnswer(
        req.params.sessionId,
        payload.questionId,
        payload.answer.selectedOptionId,
        payload.responseTimeMs
      );
      res.json(ok(data));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid request");
        return res.status(result.status).json(result.body);
      }
      const result = fail("ANSWER_SUBMIT_FAILED", error instanceof Error ? error.message : "Submit failed");
      return res.status(result.status).json(result.body);
    }
  });

  return router;
}
