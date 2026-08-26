(function () {
  const tid = window.__REPORT_EDIT_ID__;
  const DIM_KEYS = [
    ["attention", "注意力与模仿参与"],
    ["matching", "配对"],
    ["ordering", "排序"],
  ];
  const COURSE_KEYS = [
    ["mimic", "模仿"],
    ["pairing", "配对"],
    ["ordering", "排序"],
  ];

  const els = {
    status: document.getElementById("sre-status"),
    meta: document.getElementById("sre-meta"),
    overall: document.getElementById("sre-overall"),
    grade: document.getElementById("sre-grade"),
    dimensions: document.getElementById("sre-dimensions"),
    courses: document.getElementById("sre-courses"),
    analysis: document.getElementById("sre-analysis"),
    recs: document.getElementById("sre-recs"),
    addRec: document.getElementById("sre-add-rec"),
    save: document.getElementById("sre-save"),
    revert: document.getElementById("sre-revert"),
    publish: document.getElementById("sre-publish"),
  };

  let report = null;

  function setStatus(msg) {
    if (els.status) els.status.textContent = msg;
  }

  function numOrNull(v) {
    if (v === "" || v == null) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function parseRecommendationBody(body) {
    const text = String(body || "").trim();
    const match = text.match(
      /练什么[：:]\s*([\s\S]*?)\s*为什么[：:]\s*([\s\S]*?)\s*(?:进步判断|如何判断进步)[：:]\s*([\s\S]*)/
    );
    return match
      ? { practice: match[1].trim(), why: match[2].trim(), progressCheck: match[3].trim() }
      : null;
  }

  function renderDims() {
    const dims = (report && report.dimensions) || {};
    els.dimensions.innerHTML = "";
    DIM_KEYS.forEach(([key, label]) => {
      const meta = dims[key] || {};
      const row = document.createElement("div");
      row.className = "sre-dim-row";
      row.innerHTML =
        "<span>" +
        label +
        '</span><input type="number" min="0" max="100" step="0.1" data-dim="' +
        key +
        '" value="' +
        (meta.score != null ? meta.score : "") +
        '" />';
      els.dimensions.appendChild(row);
    });
  }

  function renderCourses() {
    const courses = (report && report.courseScores) || {};
    els.courses.innerHTML = "";
    COURSE_KEYS.forEach(([key, label]) => {
      const row = document.createElement("div");
      row.className = "sre-dim-row";
      row.innerHTML =
        "<span>" +
        label +
        '</span><input type="number" min="0" max="100" step="0.1" data-course="' +
        key +
        '" value="' +
        (courses[key] != null ? courses[key] : "") +
        '" />';
      els.courses.appendChild(row);
    });
  }

  function renderRecs() {
    const list = ((report && report.narrative) || {}).recommendations || [];
    els.recs.innerHTML = "";
    list.forEach((item, idx) => {
      const box = document.createElement("div");
      box.className = "sre-rec";
      box.innerHTML =
        '<input type="text" data-rec-title="' +
        idx +
        '" placeholder="标题" value="' +
        String(item.title || "").replace(/"/g, "&quot;") +
        '" />' +
        '<textarea rows="3" data-rec-body="' +
        idx +
        '" placeholder="内容">' +
        String(item.body || "") +
        "</textarea>" +
        '<div class="sre-rec-actions"><button type="button" class="cc-btn soft" data-rec-del="' +
        idx +
        '">删除</button></div>';
      els.recs.appendChild(box);
    });
    els.recs.querySelectorAll("[data-rec-del]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const i = Number(btn.getAttribute("data-rec-del"));
        const arr = ((report.narrative = report.narrative || {}).recommendations =
          report.narrative.recommendations || []);
        arr.splice(i, 1);
        renderRecs();
      });
    });
  }

  function fillForm() {
    if (!report) return;
    els.overall.value = report.overall != null ? report.overall : "";
    els.grade.value = report.grade || "";
    els.analysis.value = ((report.narrative || {}).analysis) || "";
    renderDims();
    renderCourses();
    renderRecs();
    if (els.meta) {
      els.meta.textContent =
        "会话：" +
        tid +
        " · 状态 " +
        (report.status || "—") +
        " · 推送 " +
        (report.publicationStatus || "—");
    }
  }

  function collectPatch() {
    const dimensions = Object.assign({}, report.dimensions || {});
    DIM_KEYS.forEach(([key]) => {
      const input = els.dimensions.querySelector('[data-dim="' + key + '"]');
      const score = numOrNull(input && input.value);
      dimensions[key] = Object.assign({}, dimensions[key] || {}, {
        score: score,
        available: score != null ? true : (dimensions[key] || {}).available,
      });
    });
    const courseScores = Object.assign({}, report.courseScores || {});
    COURSE_KEYS.forEach(([key]) => {
      const input = els.courses.querySelector('[data-course="' + key + '"]');
      courseScores[key] = numOrNull(input && input.value);
    });
    const recommendations = [];
    const originalRecommendations = ((report && report.narrative) || {}).recommendations || [];
    const count = els.recs.querySelectorAll("[data-rec-title]").length;
    for (let i = 0; i < count; i++) {
      const titleEl = els.recs.querySelector('[data-rec-title="' + i + '"]');
      const bodyEl = els.recs.querySelector('[data-rec-body="' + i + '"]');
      const original = originalRecommendations[i] || {};
      const body = (bodyEl && bodyEl.value) || "";
      const next = {
        ...original,
        title: (titleEl && titleEl.value) || "",
        body: body,
      };
      if (body !== String(original.body || "")) {
        delete next.evidence;
        delete next.practice;
        delete next.why;
        delete next.progressCheck;
        const parsed = parseRecommendationBody(body);
        if (parsed) Object.assign(next, parsed);
      }
      recommendations.push(next);
    }
    return {
      overall: numOrNull(els.overall.value),
      grade: els.grade.value || null,
      dimensions: dimensions,
      courseScores: courseScores,
      narrative: {
        ...(report.narrative || {}),
        analysis: els.analysis.value || "",
        recommendations: recommendations,
      },
    };
  }

  async function load() {
    setStatus("加载报告…");
    const res = await fetch(
      "/api/report/" + encodeURIComponent(tid) + "?role=server&view=auto",
      { cache: "no-store" }
    );
    const json = await res.json();
    if (!json.success) {
      setStatus("加载失败：" + (json.error || res.status));
      return;
    }
    report = json.data;
    fillForm();
    setStatus("已加载（可编辑后保存并推送）");
  }

  els.addRec.addEventListener("click", () => {
    report.narrative = report.narrative || {};
    report.narrative.recommendations = report.narrative.recommendations || [];
    report.narrative.recommendations.push({ title: "新建议", body: "" });
    renderRecs();
  });

  els.save.addEventListener("click", async () => {
    setStatus("保存中…");
    const patch = collectPatch();
    const res = await fetch("/api/report/" + encodeURIComponent(tid) + "/manual", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    const json = await res.json();
    if (!json.success) {
      setStatus("保存失败：" + (json.error || res.status));
      return;
    }
    report = json.data;
    fillForm();
    setStatus("已保存人工稿（尚未推送教师端）");
  });

  els.revert.addEventListener("click", async () => {
    if (!confirm("确认撤回人工修改，恢复算法初版？")) return;
    setStatus("撤回中…");
    const res = await fetch("/api/report/" + encodeURIComponent(tid) + "/revert", {
      method: "POST",
    });
    const json = await res.json();
    if (!json.success) {
      setStatus("撤回失败：" + (json.error || res.status));
      return;
    }
    report = json.data;
    fillForm();
    setStatus("已恢复算法初版");
  });

  els.publish.addEventListener("click", async () => {
    setStatus("推送中…");
    // 先保存当前表单
    const patch = collectPatch();
    await fetch("/api/report/" + encodeURIComponent(tid) + "/manual", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    const res = await fetch("/api/report/" + encodeURIComponent(tid) + "/publish", {
      method: "POST",
    });
    const json = await res.json();
    if (!json.success) {
      setStatus("推送失败：" + (json.error || res.status));
      return;
    }
    report = json.data;
    fillForm();
    setStatus("已推送教师端");
  });

  load().catch((err) => setStatus("加载异常：" + err));
})();
