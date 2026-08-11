(function () {
  async function refreshSyncStatus() {
    const summary = document.getElementById('cc-sync-summary');
    const preview = document.getElementById('cc-sync-preview');
    if (!summary) return;
    summary.textContent = '检查中…';
    try {
      const response = await fetch('/api/v2/config/sync/manifest', { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || `HTTP ${response.status}`);
      const manifest = data.manifest || {};
      const files = Array.isArray(manifest.files) ? manifest.files : [];
      summary.textContent = `${manifest.fileCount || files.length} 个文件 · ${manifest.courseCount || 0} 门课程 · ${manifest.totalBytes || 0} bytes`;
      if (preview) {
        preview.textContent = files.slice(0, 80).map((item) => `${item.kind}: ${item.path}`).join('\n')
          + (files.length > 80 ? `\n…还有 ${files.length - 80} 个文件` : '');
      }
    } catch (error) {
      summary.textContent = `同步清单读取失败：${error.message || error}`;
      if (preview) preview.textContent = '';
    }
  }

  window.refreshConfigSyncStatus = refreshSyncStatus;
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn-sync-refresh')?.addEventListener('click', refreshSyncStatus);
    refreshSyncStatus();
  });
})();
