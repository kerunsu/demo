const CLICK_EVENT = "child_screen_click";
const TRACKING_STARTED_EVENT = "child_screen_tracking_started";
const CLICK_SCHEMA_VERSION = "child-screen-click-v1";
const TRACKING_SCHEMA_VERSION = "child-screen-tracking-v1";
const ACTIONABLE_SELECTOR = [
  "button",
  "a[href]",
  "input",
  "select",
  "textarea",
  "[role='button']",
  "[role='option']",
  "[data-action]",
  "[data-click-target]",
  ".option",
  ".choice",
  ".item",
  ".card",
].join(",");

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

export function normalizedPoint(x, y, width, height) {
  const safeWidth = Math.max(1, finiteNumber(width, 1));
  const safeHeight = Math.max(1, finiteNumber(height, 1));
  const safeX = clamp(finiteNumber(x), 0, safeWidth);
  const safeY = clamp(finiteNumber(y), 0, safeHeight);
  return {
    x: Math.round(safeX * 1000) / 1000,
    y: Math.round(safeY * 1000) / 1000,
    width: Math.round(safeWidth * 1000) / 1000,
    height: Math.round(safeHeight * 1000) / 1000,
    xRatio: Math.round((safeX / safeWidth) * 1_000_000) / 1_000_000,
    yRatio: Math.round((safeY / safeHeight) * 1_000_000) / 1_000_000,
  };
}

function elementOrNull(value) {
  return value && value.nodeType === 1 ? value : null;
}

function closestSafe(element, selector) {
  try {
    return element && typeof element.closest === "function"
      ? element.closest(selector)
      : null;
  } catch (_error) {
    return null;
  }
}

function boundedAttribute(element, name, limit = 120) {
  if (!element || typeof element.getAttribute !== "function") return null;
  const value = String(element.getAttribute(name) || "").trim();
  return value ? value.slice(0, limit) : null;
}

export function classifyInteractionTarget(target, pageType) {
  const element = elementOrNull(target);
  const actionable = closestSafe(element, ACTIONABLE_SELECTOR);
  const dialogue = closestSafe(element, "#dialoguePanel");
  let interactionKind = "other";
  if (pageType === "interactive_iframe") interactionKind = "task";
  else if (dialogue) interactionKind = "dialogue";
  else if (actionable) interactionKind = "control";
  else if (!element || ["HTML", "BODY", "IMG", "VIDEO"].includes(element.tagName)) {
    interactionKind = "blank";
  }

  const semantic = actionable || element;
  const tag = String((semantic && semantic.tagName) || "unknown").toLowerCase();
  const id = semantic && semantic.id ? String(semantic.id).slice(0, 120) : null;
  const role = boundedAttribute(semantic, "role", 80);
  const dataAction = boundedAttribute(semantic, "data-action", 120);
  const targetType = (
    dataAction
    || role
    || (tag === "a" ? "link" : tag)
    || "other"
  ).slice(0, 80);
  return {
    tag,
    id,
    role,
    dataAction,
    targetType,
    targetKey: String(dataAction || id || role || tag || "other").slice(0, 160),
    interactionKind,
    interactive: Boolean(actionable),
  };
}

function makeClickId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  const random = Math.random().toString(36).slice(2, 12);
  return `click-${Date.now().toString(36)}-${random}`;
}

function activeFrame(frame, getInteractiveFrame) {
  if (!frame || getInteractiveFrame() !== frame || frame.id !== "interactive") {
    return false;
  }
  if (frame.dataset && frame.dataset.pageContextActive !== "true") return false;
  try {
    const style = window.getComputedStyle(frame);
    return style.display !== "none" && style.pointerEvents !== "none";
  } catch (_error) {
    return false;
  }
}

function contentPointForMain(event, getActiveContentElement) {
  const content = getActiveContentElement();
  if (!content || typeof content.getBoundingClientRect !== "function") return null;
  const rect = content.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  if (
    event.clientX < rect.left || event.clientX > rect.right
    || event.clientY < rect.top || event.clientY > rect.bottom
  ) return null;
  return normalizedPoint(
    event.clientX - rect.left,
    event.clientY - rect.top,
    rect.width,
    rect.height,
  );
}

function buildClickDetails(event, pageType, frame, getActiveContentElement, context, sequence) {
  const viewportWidth = Math.max(1, finiteNumber(window.innerWidth, 1));
  const viewportHeight = Math.max(1, finiteNumber(window.innerHeight, 1));
  let viewportX = finiteNumber(event.clientX);
  let viewportY = finiteNumber(event.clientY);
  let contentPoint = null;
  if (pageType === "interactive_iframe" && frame) {
    const rect = frame.getBoundingClientRect();
    viewportX = rect.left + finiteNumber(event.clientX);
    viewportY = rect.top + finiteNumber(event.clientY);
    const documentWidth = Math.max(
      1,
      finiteNumber(frame.contentDocument?.documentElement?.clientWidth, rect.width || 1),
    );
    const documentHeight = Math.max(
      1,
      finiteNumber(frame.contentDocument?.documentElement?.clientHeight, rect.height || 1),
    );
    contentPoint = normalizedPoint(event.clientX, event.clientY, documentWidth, documentHeight);
  } else {
    contentPoint = contentPointForMain(event, getActiveContentElement);
  }
  const viewportPoint = normalizedPoint(
    viewportX,
    viewportY,
    viewportWidth,
    viewportHeight,
  );
  return {
    schemaVersion: CLICK_SCHEMA_VERSION,
    clickId: makeClickId(),
    clientSequence: sequence,
    captureEvent: "pointerdown",
    pointerType: String(event.pointerType || "mouse").toLowerCase(),
    button: Number.isFinite(Number(event.button)) ? Number(event.button) : 0,
    isPrimary: event.isPrimary !== false,
    clientMonotonicMs: Math.round(performance.now() * 1000) / 1000,
    pageType,
    frameId: frame ? String(frame.id || "interactive").slice(0, 120) : null,
    coordinateSpace: frame ? "top_viewport+iframe_content" : "top_viewport",
    viewportX: viewportPoint.x,
    viewportY: viewportPoint.y,
    viewportWidth: viewportPoint.width,
    viewportHeight: viewportPoint.height,
    viewportXRatio: viewportPoint.xRatio,
    viewportYRatio: viewportPoint.yRatio,
    contentX: contentPoint ? contentPoint.x : null,
    contentY: contentPoint ? contentPoint.y : null,
    contentWidth: contentPoint ? contentPoint.width : null,
    contentHeight: contentPoint ? contentPoint.height : null,
    contentXRatio: contentPoint ? contentPoint.xRatio : null,
    contentYRatio: contentPoint ? contentPoint.yRatio : null,
    devicePixelRatio: Math.max(0.1, finiteNumber(window.devicePixelRatio, 1)),
    orientation: viewportWidth >= viewportHeight ? "landscape" : "portrait",
    courseType: context.courseType || null,
    courseId: context.courseId ?? null,
    courseItemId: context.courseItemId ?? null,
    questionId: context.questionId || null,
    target: classifyInteractionTarget(event.target, pageType),
  };
}

function postTimelineEvent(event, context, details) {
  if (!context || !context.trainingSessionId) return Promise.resolve(false);
  return fetch("/api/v2/timeline/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    keepalive: true,
    body: JSON.stringify({
      event,
      actor: "child",
      source: "child_ui",
      category: "child_interaction",
      phase: event === CLICK_EVENT ? "observed" : "ready",
      status: event === CLICK_EVENT ? "accepted" : "ready",
      modality: "screen",
      clientTimestamp: Date.now(),
      trainingSessionId: context.trainingSessionId,
      sessionId: context.sessionId || null,
      questionId: context.questionId || null,
      details,
    }),
  }).then((response) => response.ok).catch(() => false);
}

export function startChildScreenClickTracking(options = {}) {
  const getContext = typeof options.getContext === "function"
    ? options.getContext
    : () => ({});
  const getInteractiveFrame = typeof options.getInteractiveFrame === "function"
    ? options.getInteractiveFrame
    : () => document.getElementById("interactive");
  const getActiveContentElement = typeof options.getActiveContentElement === "function"
    ? options.getActiveContentElement
    : () => null;
  const boundDocuments = new WeakMap();
  const boundFrameLoads = new WeakSet();
  const announcedContexts = new Set();
  let clientSequence = 0;
  let stopped = false;

  const handlePointerDown = (event, pageType, frame = null) => {
    if (stopped || event.isTrusted !== true || event.isPrimary === false) return;
    const pointerType = String(event.pointerType || "mouse").toLowerCase();
    if (!["mouse", "touch", "pen"].includes(pointerType)) return;
    if (pointerType === "mouse" && Number(event.button) !== 0) return;
    if (pageType === "interactive_iframe" && !activeFrame(frame, getInteractiveFrame)) return;
    const context = getContext() || {};
    if (!context.trainingSessionId) return;
    clientSequence += 1;
    const details = buildClickDetails(
      event,
      pageType,
      frame,
      getActiveContentElement,
      context,
      clientSequence,
    );
    void postTimelineEvent(CLICK_EVENT, context, details);
  };

  const bindDocument = (doc, pageType, frame = null) => {
    if (!doc || boundDocuments.has(doc)) return;
    const listener = (event) => handlePointerDown(event, pageType, frame);
    doc.addEventListener("pointerdown", listener, { capture: true, passive: true });
    boundDocuments.set(doc, listener);
  };

  const bindInteractiveFrame = () => {
    const frame = getInteractiveFrame();
    if (!frame) return;
    if (!boundFrameLoads.has(frame)) {
      frame.addEventListener("load", () => bindInteractiveFrame(), { passive: true });
      boundFrameLoads.add(frame);
    }
    try {
      if (frame.contentDocument) {
        bindDocument(frame.contentDocument, "interactive_iframe", frame);
      }
    } catch (_error) {
      // Current course resources are same-origin. A cross-origin frame is
      // intentionally not inspected rather than weakening browser isolation.
    }
  };

  const announceTracking = () => {
    if (stopped) return;
    const context = getContext() || {};
    if (!context.trainingSessionId) return;
    const key = `${context.trainingSessionId}:${context.sessionId || ""}`;
    if (announcedContexts.has(key)) return;
    announcedContexts.add(key);
    void postTimelineEvent(TRACKING_STARTED_EVENT, context, {
      schemaVersion: TRACKING_SCHEMA_VERSION,
      clientMonotonicMs: Math.round(performance.now() * 1000) / 1000,
      viewportWidth: Math.max(1, finiteNumber(window.innerWidth, 1)),
      viewportHeight: Math.max(1, finiteNumber(window.innerHeight, 1)),
      devicePixelRatio: Math.max(0.1, finiteNumber(window.devicePixelRatio, 1)),
    });
  };

  bindDocument(document, "child_main");
  bindInteractiveFrame();
  announceTracking();
  const timer = window.setInterval(() => {
    bindInteractiveFrame();
    announceTracking();
  }, 500);

  const stop = () => {
    if (stopped) return;
    stopped = true;
    window.clearInterval(timer);
    const mainListener = boundDocuments.get(document);
    if (mainListener) {
      document.removeEventListener("pointerdown", mainListener, { capture: true });
    }
  };
  window.addEventListener("pagehide", stop, { once: true });
  return { stop };
}

export const CHILD_SCREEN_CLICK_CONTRACT = Object.freeze({
  clickEvent: CLICK_EVENT,
  trackingStartedEvent: TRACKING_STARTED_EVENT,
  clickSchemaVersion: CLICK_SCHEMA_VERSION,
  trackingSchemaVersion: TRACKING_SCHEMA_VERSION,
});
