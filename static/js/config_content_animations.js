/** Configuration center: encouragement animation library and praise binding picker. */
(function () {
  let items = [];
  let selected = '';

  function toast(title, detail, kind) {
    if (typeof window.ccToast === 'function') window.ccToast(title, detail, kind);
  }

  function selectAnimation(name) {
    selected = name;
    const item = items.find((entry) => entry.name === name);
    document.querySelectorAll('#animation-grid .cc-expr-card').forEach((card) => {
      card.classList.toggle('selected', card.dataset.name === name);
    });
    const video = document.getElementById('animation-preview-video');
    const label = document.querySelector('#animation-preview .cc-preview-label');
    const meta = document.getElementById('animation-preview-meta');
    if (video) {
      video.pause();
      video.hidden = !item;
      if (item) {
        video.src = item.url;
        video.currentTime = 0;
        video.play().catch(() => {});
      } else {
        video.removeAttribute('src');
      }
    }
    if (label) label.textContent = item ? item.name : '未选择';
    if (meta) meta.textContent = item ? `行为绑定引用 ${item.refCount || 0} 处` : '点击素材预览';
    const button = document.getElementById('btn-delete-animation');
    if (button) button.disabled = !item;
    const renameButton = document.getElementById('btn-rename-animation');
    if (renameButton) renameButton.disabled = !item;
  }

  function renderLibrary() {
    const grid = document.getElementById('animation-grid');
    const empty = document.getElementById('animation-empty');
    if (!grid) return;
    grid.innerHTML = '';
    if (empty) empty.hidden = items.length > 0;
    items.forEach((item) => {
      const card = document.createElement('div');
      card.className = 'cc-expr-card';
      card.dataset.name = item.name;
      card.innerHTML = `
        <div class="cc-expr-thumb"><video src="${item.url}" muted playsinline preload="metadata"></video></div>
        <div class="cc-expr-name"></div>
        <div class="cc-expr-meta"><span class="cc-badge primary">MP4</span><span class="cc-badge gray">引用 ${item.refCount || 0}</span></div>`;
      card.querySelector('.cc-expr-name').textContent = item.name;
      card.addEventListener('click', () => selectAnimation(item.name));
      grid.appendChild(card);
    });
  }

  function renderAnimationBinding(value) {
    const select = document.getElementById('animation-praise');
    if (!select) return;
    select.innerHTML = '<option value="">默认库随机</option>';
    items.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.name;
      option.textContent = item.name;
      select.appendChild(option);
    });
    select.value = items.some((item) => item.name === value) ? value : '';
  }

  async function loadAnimationLibrary() {
    try {
      const response = await fetch('/api/robot/animations', { cache: 'no-store' });
      const payload = await response.json();
      if (!payload.success) throw new Error(payload.error || '加载失败');
      items = payload.items || [];
      renderLibrary();
      const current = typeof window.getConfigForScope === 'function' && window.currentScope
        ? window.getConfigForScope(window.currentScope).__animation?.praise || '' : '';
      renderAnimationBinding(current);
      if (selected && items.some((item) => item.name === selected)) selectAnimation(selected);
      else selectAnimation('');
      const stat = document.getElementById('stat-animations');
      if (stat) stat.textContent = String(items.length);
    } catch (error) {
      toast('加载鼓励动画失败', String(error.message || error), 'danger');
    }
  }

  async function uploadAnimation(file) {
    const body = new FormData();
    body.append('file', file);
    const response = await fetch('/api/robot/animations/upload', { method: 'POST', body });
    const payload = await response.json();
    if (!payload.success) throw new Error(payload.error || '上传失败');
    const optimization = payload.optimization || {};
    const detail = optimization.optimized
      ? `${payload.animation}（${Math.ceil(optimization.originalSizeBytes / 1024)} KB → ${Math.ceil(optimization.sizeBytes / 1024)} KB）`
      : `${payload.animation}（无需压缩）`;
    toast('上传成功', detail);
    await loadAnimationLibrary();
    selectAnimation(payload.animation);
  }

  async function deleteAnimation() {
    if (!selected) return;
    const item = items.find((entry) => entry.name === selected);
    const referenced = item && item.refCount > 0;
    const confirmed = referenced
      ? window.confirm(`${selected} 仍被 ${item.refCount} 处行为绑定引用，确认强制删除？`)
      : window.confirm(`确认删除 ${selected}？`);
    if (!confirmed) return;
    const suffix = referenced ? '?force=1' : '';
    const response = await fetch(`/api/robot/animations/${encodeURIComponent(selected)}${suffix}`, { method: 'DELETE' });
    const payload = await response.json();
    if (!payload.success) throw new Error(payload.error || '删除失败');
    selected = '';
    await loadAnimationLibrary();
  }

  async function renameAnimation() {
    if (!selected) return;
    const current = items.find((entry) => entry.name === selected);
    const proposed = window.prompt('请输入新的 MP4 文件名', current?.name || selected);
    if (proposed === null) return;
    const newName = proposed.trim();
    if (!newName) return;
    const response = await fetch(`/api/robot/animations/${encodeURIComponent(selected)}/rename`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ newName }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.success) throw new Error(payload.error || '改名失败');
    selected = payload.newName;
    toast('动画文件名已修改', `${payload.oldName} → ${payload.newName}`);
    await loadAnimationLibrary();
    selectAnimation(selected);
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn-refresh-animations')?.addEventListener('click', loadAnimationLibrary);
    document.getElementById('animation-upload-input')?.addEventListener('change', async (event) => {
      const file = event.target.files && event.target.files[0];
      event.target.value = '';
      if (!file) return;
      try { await uploadAnimation(file); }
      catch (error) { toast('上传鼓励动画失败', String(error.message || error), 'danger'); }
    });
    document.getElementById('btn-delete-animation')?.addEventListener('click', async () => {
      try { await deleteAnimation(); }
      catch (error) { toast('删除鼓励动画失败', String(error.message || error), 'danger'); }
    });
    document.getElementById('btn-rename-animation')?.addEventListener('click', async () => {
      try { await renameAnimation(); }
      catch (error) { toast('修改动画文件名失败', String(error.message || error), 'danger'); }
    });
    loadAnimationLibrary();
  });

  window.loadAnimationLibrary = loadAnimationLibrary;
  window.renderAnimationBinding = renderAnimationBinding;
})();
