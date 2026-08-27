(function () {
  "use strict";

  const STYLE_ID = "child-kiosk-input-style";
  const ALLOWED_SCROLL_SELECTOR = ".options-zone,[data-child-touch-scroll='true']";
  const guardedDocuments = new WeakSet();
  const guardedFrames = new WeakSet();

  function elementFromTarget(target) {
    if (target && target.nodeType === 1) return target;
    return target && target.parentElement ? target.parentElement : null;
  }

  function isAllowedCourseScroll(target) {
    const element = elementFromTarget(target);
    try {
      return Boolean(element && element.closest(ALLOWED_SCROLL_SELECTOR));
    } catch (_error) {
      return false;
    }
  }

  function stopNativeOperation(event) {
    if (event.cancelable) event.preventDefault();
    event.stopImmediatePropagation();
  }

  function installDocumentStyle(doc) {
    if (!doc.head || doc.getElementById(STYLE_ID)) return;
    const style = doc.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      html, body {
        overscroll-behavior: none !important;
        touch-action: none !important;
        -webkit-user-select: none !important;
        user-select: none !important;
        -webkit-touch-callout: none !important;
        -webkit-tap-highlight-color: transparent !important;
      }
      body { overflow: hidden !important; }
      *, *::before, *::after {
        -webkit-user-select: none !important;
        user-select: none !important;
        -webkit-touch-callout: none !important;
        -webkit-user-drag: none !important;
      }
      img, video, a { -webkit-user-drag: none !important; }
      ${ALLOWED_SCROLL_SELECTOR} {
        overscroll-behavior-x: contain !important;
        overscroll-behavior-y: none !important;
        touch-action: pan-x !important;
      }
    `;
    doc.head.appendChild(style);
  }

  function guardDocument(doc) {
    if (!doc || guardedDocuments.has(doc)) return;
    guardedDocuments.add(doc);
    installDocumentStyle(doc);
    if (doc.documentElement) doc.documentElement.dataset.childInputGuard = "active";

    [
      "contextmenu",
      "auxclick",
      "dragstart",
      "dragover",
      "drop",
      "selectstart",
      "gesturestart",
      "gesturechange",
      "gestureend",
      "dblclick",
    ].forEach((eventName) => {
      doc.addEventListener(eventName, stopNativeOperation, { capture: true, passive: false });
    });

    doc.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse" && Number(event.button) !== 0) {
        stopNativeOperation(event);
      }
    }, { capture: true, passive: false });

    doc.addEventListener("touchstart", (event) => {
      if (event.touches && event.touches.length > 1) stopNativeOperation(event);
    }, { capture: true, passive: false });

    doc.addEventListener("touchmove", (event) => {
      const isMultiTouch = Boolean(event.touches && event.touches.length > 1);
      if (isMultiTouch || !isAllowedCourseScroll(event.target)) stopNativeOperation(event);
    }, { capture: true, passive: false });

    doc.addEventListener("wheel", (event) => {
      if (!isAllowedCourseScroll(event.target)) stopNativeOperation(event);
    }, { capture: true, passive: false });

    doc.addEventListener("click", (event) => {
      const element = elementFromTarget(event.target);
      const navigation = element && element.closest
        ? element.closest("a[href],area[href]")
        : null;
      if (navigation && navigation.dataset.childNavigationAllowed !== "true") {
        stopNativeOperation(event);
      }
    }, { capture: true, passive: false });

    doc.addEventListener("submit", stopNativeOperation, { capture: true, passive: false });
    doc.addEventListener("keydown", stopNativeOperation, { capture: true, passive: false });
  }

  function guardFrame(frame) {
    if (!frame) return;
    if (!guardedFrames.has(frame)) {
      guardedFrames.add(frame);
      frame.addEventListener("load", () => guardFrame(frame));
    }
    try {
      if (frame.contentDocument) guardDocument(frame.contentDocument);
    } catch (_error) {
      // 课程互动页应为同源；跨域页保持浏览器隔离，不尝试绕过。
    }
  }

  function guardAllFrames() {
    document.querySelectorAll("iframe").forEach(guardFrame);
  }

  function trapTopLevelNavigation() {
    try {
      history.replaceState({ childKiosk: true }, "", location.href);
      history.pushState({ childKiosk: true }, "", location.href);
      window.addEventListener("popstate", () => history.go(1));
    } catch (_error) {}
    try {
      window.open = () => null;
    } catch (_error) {}
  }

  function start() {
    guardDocument(document);
    trapTopLevelNavigation();
    guardAllFrames();
    const observer = new MutationObserver(guardAllFrames);
    observer.observe(document.documentElement, { childList: true, subtree: true });
    window.addEventListener("pagehide", () => observer.disconnect(), { once: true });
  }

  window.ChildKioskGuard = Object.freeze({
    guardDocument,
    guardFrame,
    allowedScrollSelector: ALLOWED_SCROLL_SELECTOR,
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
