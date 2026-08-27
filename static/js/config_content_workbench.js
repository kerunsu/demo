/**
 * 配置中心 · 工作台缺项体检（F-IC4）
 */
(function () {
  async function refreshWorkbenchSummary() {
    const issues = document.getElementById('workbench-issues');
    const elCourses = document.getElementById('stat-courses');
    try {
      const res = await fetch('/api/config/content/summary');
      const data = await res.json();
      if (!data.success) return;
      const s = data.summary || {};
      if (elCourses) elCourses.textContent = String(s.courseCount ?? '—');
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
        <div class="cc-card">
          <div class="cc-metric-label">Demo 输出能力</div>
          <div class="cc-metric-value">纯屏幕</div>
          <div class="cc-metric-note">动作 / 完整版表情关闭</div>
        </div>
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
