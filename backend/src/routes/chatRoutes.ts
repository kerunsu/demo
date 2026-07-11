import { Router } from "express";
import { ZodError } from "zod";
import { chatMessageSchema } from "../schemas/requestSchemas.js";
import { sendChatMessage } from "../services/sessionService.js";
import { getLlmGatewayAuditRecords } from "../services/llmSafetyGatewayService.js";
import { fail, ok } from "./response.js";

export function createChatRoutes() {
  const router = Router();

  router.post("/chat/:sessionId/message", async (req, res) => {
    try {
      const payload = chatMessageSchema.parse(req.body);
      const data = await sendChatMessage(req.params.sessionId, payload.text, { pageContext: payload.pageContext });
      res.json(ok(data));
    } catch (error) {
      if (error instanceof ZodError) {
        const result = fail("VALIDATION_ERROR", error.issues[0]?.message ?? "Invalid request");
        return res.status(result.status).json(result.body);
      }
      const result = fail("CHAT_FAILED", error instanceof Error ? error.message : "Chat failed");
      return res.status(result.status).json(result.body);
    }
  });

  router.get("/chat/:sessionId/audit", (req, res) => {
    res.json(ok(getLlmGatewayAuditRecords(req.params.sessionId)));
  });

  return router;
}
