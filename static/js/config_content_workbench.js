/**
 * 配置中心 · 工作台缺项体检（F-IC4）
 */
(function () {
  async function refreshWorkbenchSummary() {
    const issues = document.getElementById('workbench-issues');
    const elCourses = document.getElementById('stat-courses');
    const elEmo = document.getElementById('stat-emotions');
    const elMot = document.getElementById('stat-motions');
    try {
      const res = await fetch('/api/config/content/summary');
      const data = await res.json();
      if (!data.success) return;
      const s = data.summary || {};
      if (elCourses) elCourses.textContent = String(s.courseCount ?? '—');
      if (elEmo) elEmo.textContent = String(s.emotionCount ?? '—');
      if (elMot) elMot.textContent = String(s.motionCount ?? '—');
      if (!issues) return;
      issues.innerHTML = `
        <a class="cc-card cc-metric-link" href="?view=courses&filter=missingQuestion">
          <div class="cc-metric-label">缺提问音频</div>
          <div class="cc-metric-value">${s.missingQuestionAudio ?? 0}</div>
          <div class="cc-metric-note">课型数（manifest）</div>
        </a>
        <a class="cc-card cc-metric-link" href="?view=courses&filter=missingMedia">
          <div class="cc-metric-label">缺 Item 媒体</div>
          <div class="cc-metric-value">${s.missingItemMedia ?? 0}</div>
          <div class="cc-metric-note">课点数</div>
        </a>
        <a class="cc-card cc-metric-link" href="?view=binding">
          <div class="cc-metric-label">无行为映射课程</div>
          <div class="cc-metric-value">${s.unmappedCourses ?? 0}</div>
          <div class="cc-metric-note">去行为绑定</div>
        </a>
        <div class="cc-card">
          <div class="cc-metric-label">课点总数</div>
          <div class="cc-metric-value">${s.itemCount ?? 0}</div>
          <div class="cc-metric-note">课程 ${s.courseCount ?? 0}</div>
        </div>
      `;
    } catch (_) {
      /* ignore */
    }
  }

  window.refreshWorkbenchSummary = refreshWorkbenchSummary;
})();
