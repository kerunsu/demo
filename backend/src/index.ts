import { createApp } from "./app.js";
import { runtimeConfig, validateRuntimeConfig } from "./config/runtime.js";
import { handleClientDomainEvent } from "./services/domainEventService.js";
import { realtimeHub } from "./services/realtimeHub.js";
import { startServer } from "./server.js";

const configIssues = validateRuntimeConfig();
if (configIssues.length > 0) {
  throw new Error(`Invalid runtime config: ${configIssues.join("; ")}`);
}

realtimeHub.onClientEvent((event) => handleClientDomainEvent(event));

startServer(createApp(), {
  port: runtimeConfig.backendPort,
  host: runtimeConfig.backendHost,
  realtimeHub
});
