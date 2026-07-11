import express from "express";
import cors from "cors";
import path from "node:path";
import { runtimeConfig } from "./config/runtime.js";
import { createBehaviorRoutes } from "./routes/behaviorRoutes.js";
import { createChatRoutes } from "./routes/chatRoutes.js";
import { createCourseRoutes } from "./routes/courseRoutes.js";
import { createEventRoutes } from "./routes/eventRoutes.js";
import { createHealthRoutes } from "./routes/healthRoutes.js";
import { createMediaRoutes } from "./routes/mediaRoutes.js";
import { createMonitorRoutes } from "./routes/monitorRoutes.js";
import { createReportRoutes } from "./routes/reportRoutes.js";
import { createSessionRoutes } from "./routes/sessionRoutes.js";
import { createVoiceMetricsRoutes } from "./routes/voiceMetricsRoutes.js";
import { createVoiceTurnRoutes } from "./routes/voiceTurnRoutes.js";
import { createVoicePartnerRoutes } from "./routes/voicePartnerRoutes.js";

export function resolveProjectRoot(cwd = process.cwd()) {
  return path.basename(cwd).toLowerCase() === "backend" ? path.resolve(cwd, "..") : cwd;
}

export function createApp(options: { projectRoot?: string; enableRequestLogging?: boolean } = {}) {
  const app = express();
  const projectRoot = options.projectRoot ?? resolveProjectRoot();
  const enableRequestLogging = options.enableRequestLogging ?? true;

  app.use(
    cors({
      origin: runtimeConfig.corsOrigins
    })
  );
  app.use(express.json({ limit: "8mb" }));
  app.use("/matching", express.static(path.join(projectRoot, "matching")));
  app.use("/paixu", express.static(path.join(projectRoot, "paixu")));
  app.use("/Emotions", express.static(path.join(projectRoot, "Emotions")));
  if (enableRequestLogging) {
    app.use((req, _res, next) => {
      console.log(`[${new Date().toISOString()}] ${req.method} ${req.path}`);
      next();
    });
  }

  app.use("/api", createHealthRoutes());
  app.use("/api", createSessionRoutes());
  app.use("/api", createCourseRoutes());
  app.use("/api", createReportRoutes());
  app.use("/api", createChatRoutes());
  app.use("/api", createBehaviorRoutes());
  app.use("/api", createEventRoutes());
  app.use("/api", createMediaRoutes());
  app.use("/api", createMonitorRoutes());
  app.use("/api", createVoiceMetricsRoutes());
  app.use("/api", createVoiceTurnRoutes());
  app.use("/api", createVoicePartnerRoutes());

  return app;
}
