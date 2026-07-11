import type { Express } from "express";
import type { Server } from "node:http";
import type { RealtimeHub } from "./services/realtimeHub.js";

export interface ServerOptions {
  port: number;
  host: string;
  realtimeHub?: RealtimeHub;
}

export function startServer(app: Express, options: ServerOptions) {
  const server = app.listen(options.port, options.host, () => {
    console.log(`Backend server running at http://${options.host}:${options.port}`);
  });

  server.on("error", (error: NodeJS.ErrnoException) => {
    if (error.code === "EADDRINUSE") {
      console.error(
        `\nPort ${options.port} is already in use. Another backend is still running.\n` +
          `- Stop the old terminal (Ctrl+C), or run: npm run dev:stop\n` +
          `- Do not run root "npm run dev" and "backend/npm run dev" at the same time.\n`
      );
      process.exit(1);
    }
    throw error;
  });

  options.realtimeHub?.attach(server as Server);
  registerGracefulShutdown(server, options);
  return server;
}

function registerGracefulShutdown(server: Server, options: ServerOptions) {
  let shuttingDown = false;

  const shutdown = (signal: string) => {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(`\n${signal} received, closing backend...`);
    options.realtimeHub?.closeAll();
    server.close((error) => {
      if (error) {
        console.error(error);
        process.exit(1);
      }
      process.exit(0);
    });
    setTimeout(() => {
      console.error("Forced shutdown after timeout.");
      process.exit(1);
    }, 5000).unref();
  };

  process.once("SIGINT", () => shutdown("SIGINT"));
  process.once("SIGTERM", () => shutdown("SIGTERM"));
}
