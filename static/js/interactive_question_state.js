(function (global) {
  "use strict";

  const MODE_ASSESSMENT = "assessment";
  const MODE_INTERVENTION = "training";

  function normalizeMode(value) {
    return String(value || "").trim().toLowerCase() === MODE_ASSESSMENT
      ? MODE_ASSESSMENT
      : MODE_INTERVENTION;
  }

  function normalizePresentationDirection(value) {
    const direction = String(value || "").trim().toLowerCase();
    return direction === "left" || direction === "right" ? direction : "";
  }

  function presentationDirectionForQuestion(questionIndex) {
    const index = Math.max(1, Math.trunc(Number(questionIndex) || 1));
    return index % 2 === 1 ? "left" : "right";
  }

  class QuestionInputGate {
    constructor({
      sessionId,
      timeoutMs = 15000,
      onUnlock,
      focusElement,
      focusScale = 1,
    } = {}) {
      this.sessionId = String(sessionId || "");
      this.timeoutMs = Math.max(3000, Number(timeoutMs) || 15000);
      this.onUnlock = typeof onUnlock === "function" ? onUnlock : null;
      this.locked = false;
      this.questionKey = "";
      this.generation = 0;
      this.timer = null;
      this.entryTimer = null;
      this.focusElement = focusElement || null;
      this.focusScale = Math.max(1, Number(focusScale) || 1);
    }

    positionFocus(presentationDirection) {
      const element = typeof this.focusElement === "string"
        ? document.querySelector(this.focusElement)
        : this.focusElement;
      if (!element || typeof element.getBoundingClientRect !== "function") return;
      const rect = element.getBoundingClientRect();
      const viewportWidth = Math.max(
        1,
        Number(document.documentElement && document.documentElement.clientWidth)
          || Number(global.innerWidth)
          || 1
      );
      const viewportHeight = Math.max(
        1,
        Number(document.documentElement && document.documentElement.clientHeight)
          || Number(global.innerHeight)
          || 1
      );
      const direction = normalizePresentationDirection(presentationDirection);
      const normalCenterX = rect.left + rect.width / 2;
      const sideMargin = Math.max(20, Math.min(64, viewportWidth * 0.04));
      const scaledHalfWidth = Math.min(
        Math.max(0, viewportWidth / 2 - sideMargin),
        rect.width * this.focusScale / 2
      );
      const sideCenterX = direction === "left"
        ? sideMargin + scaledHalfWidth
        : viewportWidth - sideMargin - scaledHalfWidth;
      const destinationCenterX = direction ? sideCenterX : viewportWidth / 2;
      const x = destinationCenterX - normalCenterX;
      const y = viewportHeight / 2 - (rect.top + rect.height / 2);
      const entryX = direction === "left"
        ? -(normalCenterX + scaledHalfWidth + sideMargin)
        : viewportWidth - normalCenterX + scaledHalfWidth + sideMargin;
      element.style.setProperty("--question-focus-x", `${Math.round(x)}px`);
      element.style.setProperty("--question-focus-y", `${Math.round(y)}px`);
      element.style.setProperty("--question-entry-x", `${Math.round(entryX)}px`);
      element.dataset.questionFocusDirection = direction;
      document.body.dataset.questionFocusDirection = direction;
    }

    lock(questionKey, { presentationDirection } = {}) {
      this.generation += 1;
      const generation = this.generation;
      this.questionKey = String(questionKey || "");
      this.locked = true;
      if (this.timer != null) global.clearTimeout(this.timer);
      if (this.entryTimer != null) global.clearTimeout(this.entryTimer);
      // Measure the element in its normal layout before applying the transform.
      // Pairing/ordering provide a deterministic side; other callers keep the
      // historical centred fallback.
      this.positionFocus(presentationDirection);
      document.body.classList.remove("question-input-ready");
      document.body.classList.remove("question-focus-entering");
      // Restart the side-entry animation even when a previous prompt ended on
      // the same side.
      void document.body.offsetWidth;
      document.body.classList.add("question-input-locked");
      if (normalizePresentationDirection(presentationDirection)) {
        document.body.classList.add("question-focus-entering");
        this.entryTimer = global.setTimeout(() => {
          if (generation !== this.generation) return;
          document.body.classList.remove("question-focus-entering");
          this.entryTimer = null;
        }, 520);
      }
      this.timer = global.setTimeout(() => {
        if (generation !== this.generation) return;
        this.unlock("speech_timeout");
      }, this.timeoutMs);
    }

    handleSpeakEnded(payload) {
      const data = payload || {};
      if (String(data.intent || "").trim().toLowerCase() !== "question") return false;
      const eventSessionId = String(data.sessionId || data.session_id || "");
      if (this.sessionId && eventSessionId && this.sessionId !== eventSessionId) return false;
      const eventQuestionKey = String(data.questionId || data.question_id || "");
      if (this.questionKey && eventQuestionKey && this.questionKey !== eventQuestionKey) {
        return false;
      }
      const reason = String(data.reason || "").trim().toLowerCase();
      if (reason === "interrupted" || reason === "canceled" || reason === "cancelled") {
        return false;
      }
      return this.unlock("speech_ended");
    }

    unlock(reason = "manual") {
      if (!this.locked) return false;
      this.locked = false;
      if (this.timer != null) global.clearTimeout(this.timer);
      if (this.entryTimer != null) global.clearTimeout(this.entryTimer);
      this.timer = null;
      this.entryTimer = null;
      document.body.classList.remove("question-input-locked", "question-focus-entering");
      document.body.classList.add("question-input-ready");
      if (this.onUnlock) this.onUnlock(reason, this.questionKey);
      return true;
    }

    cancel() {
      this.generation += 1;
      this.locked = false;
      if (this.timer != null) global.clearTimeout(this.timer);
      if (this.entryTimer != null) global.clearTimeout(this.entryTimer);
      this.timer = null;
      this.entryTimer = null;
      document.body.classList.remove(
        "question-input-locked",
        "question-input-ready",
        "question-focus-entering"
      );
      delete document.body.dataset.questionFocusDirection;
    }
  }

  global.InteractiveQuestionState = Object.freeze({
    MODE_ASSESSMENT,
    MODE_INTERVENTION,
    normalizeMode,
    normalizePresentationDirection,
    presentationDirectionForQuestion,
    QuestionInputGate,
  });
})(window);
