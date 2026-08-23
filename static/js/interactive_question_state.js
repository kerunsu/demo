(function (global) {
  "use strict";

  const MODE_ASSESSMENT = "assessment";
  const MODE_INTERVENTION = "training";

  function normalizeMode(value) {
    return String(value || "").trim().toLowerCase() === MODE_ASSESSMENT
      ? MODE_ASSESSMENT
      : MODE_INTERVENTION;
  }

  class QuestionInputGate {
    constructor({ sessionId, timeoutMs = 15000, onUnlock, focusElement } = {}) {
      this.sessionId = String(sessionId || "");
      this.timeoutMs = Math.max(3000, Number(timeoutMs) || 15000);
      this.onUnlock = typeof onUnlock === "function" ? onUnlock : null;
      this.locked = false;
      this.questionKey = "";
      this.generation = 0;
      this.timer = null;
      this.focusElement = focusElement || null;
    }

    positionFocus() {
      const element = typeof this.focusElement === "string"
        ? document.querySelector(this.focusElement)
        : this.focusElement;
      if (!element || typeof element.getBoundingClientRect !== "function") return;
      const rect = element.getBoundingClientRect();
      const x = global.innerWidth / 2 - (rect.left + rect.width / 2);
      const y = global.innerHeight / 2 - (rect.top + rect.height / 2);
      element.style.setProperty("--question-focus-x", `${Math.round(x)}px`);
      element.style.setProperty("--question-focus-y", `${Math.round(y)}px`);
    }

    lock(questionKey) {
      this.generation += 1;
      const generation = this.generation;
      this.questionKey = String(questionKey || "");
      this.locked = true;
      if (this.timer != null) global.clearTimeout(this.timer);
      // Measure the element in its normal layout before the locked transform
      // is applied, then move it into the true viewport centre.
      this.positionFocus();
      document.body.classList.remove("question-input-ready");
      document.body.classList.add("question-input-locked");
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
      this.timer = null;
      document.body.classList.remove("question-input-locked");
      document.body.classList.add("question-input-ready");
      if (this.onUnlock) this.onUnlock(reason, this.questionKey);
      return true;
    }

    cancel() {
      this.generation += 1;
      this.locked = false;
      if (this.timer != null) global.clearTimeout(this.timer);
      this.timer = null;
      document.body.classList.remove("question-input-locked", "question-input-ready");
    }
  }

  global.InteractiveQuestionState = Object.freeze({
    MODE_ASSESSMENT,
    MODE_INTERVENTION,
    normalizeMode,
    QuestionInputGate,
  });
})(window);
