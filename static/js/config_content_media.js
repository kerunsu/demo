/**
 * 配置中心 · 媒资库
 */
(function () {
  let currentRoot = 'images';
  let pickCallback = null;
  let pickerRoot = 'images';

  function toast(t, d, k) {
    if (window.ccToast) window.ccToast(t, d, k);
  }

  function pathForApi(root) {
    return (root || '').replace(/^resources\//, '').replace(/\/$/, '');
  }

  function renderEntries(listEl, crumbsEl, root, entries, onNavigate) {
    if (crumbsEl) {
      const parts = root ? root.split('/').filter(Boolean) : [];
      let acc = '';
      crumbsEl.innerHTML =
        `<button type="button" class="cc-link" data-nav="">resources</button>` +
        parts
          .map((p) => {
            acc = acc ? acc + '/' + p : p;
            return ` / <button type="button" class="cc-link" data-nav="${acc}">${p}</button>`;
          })
          .join('');
      crumbsEl.querySelectorAll('[data-nav]').forEach((btn) => {
        btn.addEventListener('click', () => onNavigate(btn.dataset.nav));
      });
    }
    if (!listEl) return;
    if (!entries.length) {
      listEl.innerHTML = '<p class="cc-tiny">空目录</p>';
      return;
    }
    listEl.innerHTML = entries
      .map((e) => {
        const isDir = e.kind === 'dir';
        const preview =
          !isDir && /\.(png|jpe?g|gif|webp)$/i.test(e.name)
            ? `<img class="cc-media-thumb" src="${e.url}" alt="" />`
            : isDir
              ? `<div class="cc-media-folder">📁 ${e.sampleCount || 0}</div>`
              : `<div class="cc-media-file">${(e.ext || '').toUpperCase()}</div>`;
        return `
        <div class="cc-media-card" data-path="${e.path}" data-kind="${e.kind}">
          ${preview}
          <div class="cc-media-name" title="${e.name}">${e.name}${isDir ? '/' : ''}</div>
          <div class="cc-media-actions">
            ${isDir ? `<button type="button" class="cc-btn soft small" data-act="open">打开</button>` : ''}
            ${
              isDir
                ? `<button type="button" class="cc-btn soft small" data-act="pick-folder">选用文件夹</button>`
                : `<button type="button" class="cc-btn soft small" data-act="pick">选用</button>`
            }
            ${pickCallback ? '' : `<button type="button" class="cc-btn danger small" data-act="del">删</button>`}
          </div>
        </div>`;
      })
      .join('');
    listEl.querySelectorAll('.cc-media-card').forEach((card) => {
      const path = card.dataset.path;
      const kind = card.dataset.kind;
      card.querySelector('[data-act="open"]')?.addEventListener('click', () => {
        const r = path.replace(/^resources\//, '').replace(/\/$/, '');
        onNavigate(r);
      });
      card.querySelector('[data-act="pick"]')?.addEventListener('click', () => finishPick(path));
      card.querySelector('[data-act="pick-folder"]')?.addEventListener('click', () => finishPick(path));
      card.querySelector('[data-act="del"]')?.addEventListener('click', () => deleteMedia(path));
    });
  }

  async function fetchEntries(root) {
    const q = root ? `?root=${encodeURIComponent(pathForApi(root))}` : '';
    const res = await fetch('/api/config/media' + q);
    const data = await res.json();
    if (!data.success) throw new Error(data.error || '加载失败');
    return data.entries || [];
  }

  async function loadMediaLibrary(root) {
    if (root != null) currentRoot = root;
    const uploadDir = document.getElementById('media-upload-dir');
    if (uploadDir) uploadDir.textContent = currentRoot || '(顶层)';
    try {
      const entries = await fetchEntries(currentRoot);
      renderEntries(
        document.getElementById('media-list'),
        document.getElementById('media-crumbs'),
        currentRoot,
        entries,
        (r) => loadMediaLibrary(r)
      );
    } catch (e) {
      toast('媒资加载失败', String(e.message || e), 'danger');
    }
  }

  async function loadPicker(root) {
    if (root != null) pickerRoot = root;
    try {
      const entries = await fetchEntries(pickerRoot);
      renderEntries(
        document.getElementById('picker-media-list'),
        document.getElementById('picker-crumbs'),
        pickerRoot,
        entries,
        (r) => loadPicker(r)
      );
    } catch (e) {
      toast('媒资加载失败', String(e.message || e), 'danger');
    }
  }

  function finishPick(path) {
    if (typeof pickCallback === 'function') {
      const cb = pickCallback;
      pickCallback = null;
      const modal = document.getElementById('media-picker-modal');
      if (modal) modal.style.display = 'none';
      cb(path);
      return;
    }
    navigator.clipboard?.writeText(path).then(
      () => toast('已复制路径', path),
      () => toast('路径', path)
    );
  }

  async function deleteMedia(path) {
    if (!window.confirm(`删除 ${path}？`)) return;
    try {
      let res = await fetch('/api/config/media', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      let data = await res.json();
      if (res.status === 409) {
        if (!window.confirm((data.error || '仍被引用') + '\n强制删除？')) return;
        res = await fetch('/api/config/media', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path, force: true }),
        });
        data = await res.json();
      }
      if (!data.success) throw new Error(data.error || '删除失败');
      toast('已删除', path);
      await loadMediaLibrary(currentRoot);
    } catch (e) {
      toast('删除失败', String(e.message || e), 'danger');
    }
  }

  async function uploadMedia(file) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('dir', pathForApi(currentRoot) || 'images');
    const res = await fetch('/api/config/media/upload', { method: 'POST', body: fd });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || '上传失败');
    toast('上传成功', data.path);
    await loadMediaLibrary(currentRoot);
  }

  function openMediaPicker(opts, callback) {
    pickCallback = callback;
    const start = (opts && opts.root) || currentRoot || 'images';
    const modal = document.getElementById('media-picker-modal');
    if (modal) modal.style.display = 'flex';
    loadPicker(start);
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-media-root]').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('[data-media-root]').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        loadMediaLibrary(btn.dataset.mediaRoot);
      });
    });
    document.querySelectorAll('[data-picker-root]').forEach((btn) => {
      btn.addEventListener('click', () => loadPicker(btn.dataset.pickerRoot));
    });
    const input = document.getElementById('media-upload-input');
    const btnUp = document.getElementById('btn-media-upload');
    if (btnUp && input) {
      btnUp.addEventListener('click', () => input.click());
      input.addEventListener('change', async (e) => {
        const file = e.target.files && e.target.files[0];
        e.target.value = '';
        if (!file) return;
        try {
          await uploadMedia(file);
        } catch (err) {
          toast('上传失败', String(err.message || err), 'danger');
        }
      });
    }
    document.getElementById('btn-media-refresh')?.addEventListener('click', () =>
      loadMediaLibrary(currentRoot)
    );
    document.getElementById('media-picker-close')?.addEventListener('click', () => {
      pickCallback = null;
      const modal = document.getElementById('media-picker-modal');
      if (modal) modal.style.display = 'none';
    });
  });

  window.loadMediaLibrary = loadMediaLibrary;
  window.openMediaPicker = openMediaPicker;
})();
