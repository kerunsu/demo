import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // 后端切到 HTTPS 时设 VITE_BACKEND_URL=https://127.0.0.1:8080
  const backend = (env.VITE_BACKEND_URL || "http://127.0.0.1:8080").replace(/\/$/, "");
  const frontendBuildVersion =
    env.VITE_FRONTEND_BUILD_VERSION || process.env.npm_package_version || "development";

  const proxyTarget = {
    target: backend,
    changeOrigin: true,
    // 自签名证书：代理到 https://127.0.0.1:8080 时必须关掉校验
    secure: false,
    ws: true,
  };

  return {
    base: "/teacher/",
    plugins: [react()],
    define: {
      __FRONTEND_BUILD_VERSION__: JSON.stringify(frontendBuildVersion),
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
    build: {
      outDir: "dist",
    },
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        "/courses": { ...proxyTarget, ws: false },
        "/api": { ...proxyTarget, ws: false },
        // 静态资源代理（图片、音频等）
        "/static": { ...proxyTarget, ws: false },
        // Socket.IO 代理（HTTPS 后端 → wss 经 Vite 转发）
        "/socket.io": proxyTarget,
      },
    },
  };
});
