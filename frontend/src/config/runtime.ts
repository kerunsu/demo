export type ScreenRole = "child" | "robot" | "server";

type ViteImportMeta = ImportMeta & {
  env?: Record<string, string | undefined>;
};

export const SCREEN_ROUTES: Record<ScreenRole, string> = {
  child: "/child",
  robot: "/robot",
  server: "/server"
};

export const FRONTEND_RUNTIME_CONFIG = {
  defaultScreenRole: "child" as ScreenRole,
  screenRoutes: SCREEN_ROUTES,
  apiBaseUrl: normalizeApiBaseUrl(getEnv("VITE_API_BASE_URL", "http://127.0.0.1:3001/api")),
  wsUrl: normalizeWsUrl(getEnv("VITE_WS_URL", "ws://127.0.0.1:3001/ws"))
};

export function getScreenRoleFromPathname(pathname: string): ScreenRole {
  if (pathname === SCREEN_ROUTES.robot || pathname.startsWith(`${SCREEN_ROUTES.robot}/`)) {
    return "robot";
  }
  if (pathname === SCREEN_ROUTES.server || pathname.startsWith(`${SCREEN_ROUTES.server}/`)) {
    return "server";
  }
  return "child";
}

export function getApiOrigin() {
  return FRONTEND_RUNTIME_CONFIG.apiBaseUrl.replace(/\/api\/?$/, "");
}

export function resolveBackendAssetUrl(resourceRef: string) {
  if (resourceRef.startsWith("http://") || resourceRef.startsWith("https://")) return resourceRef;
  return `${getApiOrigin()}${resourceRef.startsWith("/") ? resourceRef : `/${resourceRef}`}`;
}

function getEnv(name: string, fallback: string) {
  const value = (import.meta as ViteImportMeta).env?.[name];
  return value && value.trim() ? value.trim() : fallback;
}

function normalizeApiBaseUrl(value: string) {
  try {
    const parsed = new URL(value);
    return parsed.toString().replace(/\/+$/, "");
  } catch {
    throw new Error(`Invalid VITE_API_BASE_URL: ${value}`);
  }
}

function normalizeWsUrl(value: string) {
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "ws:" && parsed.protocol !== "wss:") {
      throw new Error("WebSocket URL must use ws:// or wss://");
    }
    return parsed.toString().replace(/\/+$/, "");
  } catch {
    throw new Error(`Invalid VITE_WS_URL: ${value}`);
  }
}
