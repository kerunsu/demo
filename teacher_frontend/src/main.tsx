import React from "react";
import ReactDOM from "react-dom/client";
import App from "../App";
import "../styles/globals.css";
import { ErrorBoundary } from "./ErrorBoundary";

document.documentElement.dataset.frontendBuildVersion = __FRONTEND_BUILD_VERSION__;

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);

