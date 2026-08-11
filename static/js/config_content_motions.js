/**
 * 配置中心 · 动作库（复用 /api/robot/motions*）
 */
(function () {
  function toast(title, detail, kind) {
    if (typeof window.ccToast === 'function') window.ccToast(title, detail, kind);
    else console.log(title, detail);
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function loadMotionLibrary() {
    const container = document.getElementById('cc-motion-library');
    const empty = document.getElementById('cc-motion-empty');
    const countEl = document.getElementById('stat-motions');
    if (!container) return;
    try {
      const res = await fetch('/api/robot/motions');
      const data = await res.json();
      if (!data.success) throw new Error(data.error || '加载失败');
      const motions = data.motions || [];
      if (countEl) countEl.textContent = String(motions.length);
      if (empty) empty.hidden = motions.length > 0;
      if (!motions.length) {
        container.innerHTML = '';
        return;
      }
      container.innerHTML = motions
        .map((m) => {
          const name = escapeHtml(m.name);
          const frames = m.frameCount != null ? m.frameCount : '—';
          const dur =
            m.duration != null ? (Number(m.duration) / 1000).toFixed(1) + 's' : '—';
          const speed = Number(m.metadata?.speedMultiplier || 1);
          return `
          <div class="cc-motion-card" data-name="${name}">
            <div class="cc-motion-name">${name}</div>
            <div class="cc-motion-meta">${frames} 帧 · ${dur} · ${speed.toFixed(2)}x</div>
            <label class="cc-tuning-field">速度倍率
              <input class="cc-inp" data-speed type="number" min="0.25" max="4" step="0.05" value="${speed}" />
            </label>
            <div class="cc-motion-actions">
              <button type="button" class="cc-btn soft small" data-act="play">试播</button>
              <button type="button" class="cc-btn primary small" data-act="save-speed">保存倍率</button>
              <button type="button" class="cc-btn soft small" data-act="reset-speed">恢复 1x</button>
              <button type="button" class="cc-btn danger small" data-act="delete">删除</button>
            </div>
          </div>`;
        })
        .join('');
      container.querySelectorAll('.cc-motion-card').forEach((card) => {
        const name = card.dataset.name;
        card.querySelector('[data-act="play"]')?.addEventListener('click', () => playMotion(name));
        card.querySelector('[data-act="save-speed"]')?.addEventListener('click', () => {
          saveMotionSpeed(name, card.querySelector('[data-speed]')?.value);
        });
        card.querySelector('[data-act="reset-speed"]')?.addEventListener('click', () => {
          saveMotionSpeed(name, 1);
        });
        card.querySelector('[data-act="delete"]')?.addEventListener('click', () => deleteMotion(name));
      });
    } catch (e) {
      toast('加载动作失败', String(e.message || e), 'danger');
    }
  }

  async function playMotion(name) {
    try {
      const res = await fetch(`/api/robot/play/${encodeURIComponent(name)}`, { method: 'POST' });
      const data = await res.json();
      if (!data.success) throw new Error(data.error || '播放失败');
      toast('试播已开始', name);
    } catch (e) {
      toast('试播失败', String(e.message || e), 'danger');
    }
  }

  async function stopMotion() {
    try {
      const res = await fetch('/api/robot/stop', { method: 'POST' });
      const data = await res.json();
      if (!data.success) throw new Error(data.error || '停止失败');
      toast('已停止', '');
    } catch (e) {
      toast('停止失败', String(e.message || e), 'danger');
    }
  }

  async function saveMotionSpeed(name, value) {
    try {
      const res = await fetch(`/api/robot/motions/${encodeURIComponent(name)}/playback`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ speedMultiplier: Number(value) }),
      });
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(data.error || '保存失败');
      toast('动作倍率已保存', `${name} · ${Number(data.playback.speedMultiplier).toFixed(2)}x`);
      await loadMotionLibrary();
    } catch (e) {
      toast('保存动作倍率失败', String(e.message || e), 'danger');
    }
  }

  async function deleteMotion(name) {
    if (!window.confirm(`确定删除动作「${name}」？`)) return;
    try {
      const res = await fetch(`/api/robot/motions/${encodeURIComponent(name)}`, {
        method: 'DELETE',
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.error || '删除失败');
      toast('已删除', name);
      await loadMotionLibrary();
    } catch (e) {
      toast('删除失败', String(e.message || e), 'danger');
    }
  }

  async function importMotion(file) {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch('/api/robot/motions/import', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || '导入失败');
    toast('导入成功', data.motionName || '');
    await loadMotionLibrary();
  }

  document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('cc-motion-import-input');
    const btnImport = document.getElementById('btn-cc-import-motion');
    const btnStop = document.getElementById('btn-cc-stop-motion');
    const btnRefresh = document.getElementById('btn-cc-refresh-motions');
    if (btnImport && input) {
      btnImport.addEventListener('click', () => input.click());
      input.addEventListener('change', async (e) => {
        const file = e.target.files && e.target.files[0];
        e.target.value = '';
        if (!file) return;
        try {
          await importMotion(file);
        } catch (err) {
          toast('导入失败', String(err.message || err), 'danger');
        }
      });
    }
    if (btnStop) btnStop.addEventListener('click', () => stopMotion());
    if (btnRefresh) btnRefresh.addEventListener('click', () => loadMotionLibrary());
  });

  window.loadMotionLibrary = loadMotionLibrary;
})();
