import { Router } from "express";
import { generateReport, getAssessment, getReport } from "../services/sessionService.js";
import { fail, ok } from "./response.js";

export function createReportRoutes() {
  const router = Router();

  router.post("/report/:sessionId/generate", async (req, res) => {
    try {
      const data = await generateReport(req.params.sessionId);
      res.json(ok(data));
    } catch (error) {
      const result = fail("REPORT_GENERATE_FAILED", error instanceof Error ? error.message : "Generate failed");
      res.status(result.status).json(result.body);
    }
  });

  router.get("/report/:sessionId", (req, res) => {
    try {
      const data = getReport(req.params.sessionId);
      res.json(ok(data));
    } catch (error) {
      const result = fail("REPORT_NOT_FOUND", error instanceof Error ? error.message : "Report not found", 404);
      res.status(result.status).json(result.body);
    }
  });

  router.get("/assessment/:sessionId", (req, res) => {
    try {
      const data = getAssessment(req.params.sessionId);
      res.json(ok(data));
    } catch (error) {
      const result = fail("ASSESSMENT_NOT_FOUND", error instanceof Error ? error.message : "Assessment not found", 404);
      res.status(result.status).json(result.body);
    }
  });

  return router;
}
