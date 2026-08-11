/**
 * 配置中心 · 表情库
 */
(function () {
  let items = [];
  let selected = null;
  let defaultEmotion = '';
  let globalFilter = {
    enabled: false, hueDeg: 0, brightness: 1, saturation: 1, contrast: 1, opacity: 1,
  };
  const defaultStyle = {
    speedMultiplier: 1, scale: 1, hueDeg: 0, brightness: 1, saturation: 1, opacity: 1,
  };

  const grid = () => document.getElementById('emotion-grid');
  const empty = () => document.getElementById('emotion-empty');
  const previewImg = () => document.getElementById('emotion-preview-img');
  const previewVideo = () => document.getElementById('emotion-preview-video');
  const previewLabel = () => document.querySelector('#emotion-preview .cc-preview-label');
  const previewMeta = () => document.getElementById('emotion-preview-meta');
  const byId = (id) => document.getElementById(id);

  const styleFields = {
    speedMultiplier: 'emotion-style-speed',
    scale: 'emotion-style-scale',
    hueDeg: 'emotion-style-hue',
    brightness: 'emotion-style-brightness',
    saturation: 'emotion-style-saturation',
    opacity: 'emotion-style-opacity',
  };
  const globalFields = {
    hueDeg: 'emotion-global-hue',
    brightness: 'emotion-global-brightness',
    saturation: 'emotion-global-saturation',
    contrast: 'emotion-global-contrast',
    opacity: 'emotion-global-opacity',
  };

  function toast(title, detail, kind) {
    if (typeof window.ccToast === 'function') window.ccToast(title, detail, kind);
    else console.log(title, detail);
  }

  function setActionEnabled(on) {
    [
      'btn-set-default', 'btn-trigger-emotion', 'btn-delete-emotion',
      'btn-save-emotion-style', 'btn-reset-emotion-style',
    ].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = !on;
    });
  }

  function writeFields(mapping, value) {
    Object.entries(mapping).forEach(([key, id]) => {
      const input = byId(id);
      if (input) input.value = value[key];
    });
  }

  function readFields(mapping) {
    return Object.fromEntries(Object.entries(mapping).map(([key, id]) => [key, Number(byId(id)?.value)]));
  }

  function applyPreviewTuning() {
    const style = readFields(styleFields);
    const enabled = byId('emotion-global-enabled')?.checked === true;
    const filter = readFields(globalFields);
    const media = previewVideo()?.hidden ? previewImg() : previewVideo();
    if (media) {
      media.style.transform = `scale(${style.scale})`;
      media.style.filter = `hue-rotate(${style.hueDeg}deg) brightness(${style.brightness}) saturate(${style.saturation})`;
      media.style.opacity = String(style.opacity);
      if ('playbackRate' in media && Number.isFinite(style.speedMultiplier)) {
        media.playbackRate = style.speedMultiplier;
      }
    }
    const layer = byId('emotion-preview-filter-layer');
    if (layer) {
      layer.style.filter = enabled
        ? `hue-rotate(${filter.hueDeg}deg) brightness(${filter.brightness}) saturate(${filter.saturation}) contrast(${filter.contrast})`
        : 'none';
      layer.style.opacity = enabled ? String(filter.opacity) : '1';
    }
  }

  function populateTuning(item) {
    writeFields(styleFields, { ...defaultStyle, ...(item?.style || {}) });
    writeFields(globalFields, globalFilter);
    const enabled = byId('emotion-global-enabled');
    if (enabled) enabled.checked = globalFilter.enabled === true;
    const speed = byId(styleFields.speedMultiplier);
    if (speed) {
      speed.disabled = !!item && item.speedSupported === false;
      speed.title = speed.disabled ? '历史 GIF 不支持可靠变速；请转换为 MP4' : '';
    }
    applyPreviewTuning();
  }

  function render() {
    const g = grid();
    if (!g) return;
    g.innerHTML = '';
    const emptyEl = empty();
    if (emptyEl) emptyEl.hidden = items.length > 0;

    items.forEach((item) => {
      const card = document.createElement('div');
      card.className = 'cc-expr-card' + (selected === item.name ? ' selected' : '');
      card.dataset.name = item.name;
      const badges = [];
      if (item.isDefault) badges.push('<span class="cc-badge primary">默认</span>');
      if (item.deprecated) badges.push('<span class="cc-badge gray">历史 GIF</span>');
      else badges.push('<span class="cc-badge primary">MP4 · 单次</span>');
      badges.push(`<span class="cc-badge gray">引用 ${item.refCount || 0}</span>`);
      const media = item.format === 'mp4' || /\.mp4$/i.test(item.name)
        ? `<video src="${item.url}" muted playsinline preload="metadata"></video>`
        : `<img src="${item.url}?t=${Date.now()}" alt="" />`;
      card.innerHTML = `
        <div class="cc-expr-thumb">${media}</div>
        <div class="cc-expr-name">${item.name}</div>
        <div class="cc-expr-meta">${badges.join('')}</div>
      `;
      card.addEventListener('click', () => selectEmotion(item.name));
      g.appendChild(card);
    });
  }

  function selectEmotion(name) {
    selected = name;
    const item = items.find((x) => x.name === name);
    render();
    const img = previewImg();
    const video = previewVideo();
    const label = previewLabel();
    const meta = previewMeta();
    if (img && video && item) {
      const mp4 = item.format === 'mp4' || /\.mp4$/i.test(item.name);
      img.hidden = mp4;
      video.hidden = !mp4;
      video.pause();
      if (mp4) {
        video.src = item.url;
        video.currentTime = 0;
        video.loop = false;
        video.playbackRate = Number(item.style?.speedMultiplier || 1);
        video.play().catch(() => {});
      } else {
        video.removeAttribute('src');
        img.src = item.url + '?t=' + Date.now();
      }
    }
    populateTuning(item);
    if (label) label.textContent = name;
    if (meta && item) {
      meta.textContent = item.isDefault
        ? `默认待机 · ${item.format || 'gif'} · 被映射引用 ${item.refCount} 处`
        : `${item.deprecated ? '历史 GIF 兼容' : 'MP4 单次播放'} · 被映射引用 ${item.refCount} 处`;
    }
    setActionEnabled(!!item);
  }

  async function loadEmotionLibrary() {
    try {
      const res = await fetch('/api/robot/emotions');
      const data = await res.json();
      if (!data.success) throw new Error(data.error || '加载失败');
      items = data.items || (data.emotions || []).map((name) => ({
        name,
        refCount: 0,
        isDefault: name === data.default,
        url: `/static/resources/Emotions/${name}`,
      }));
      defaultEmotion = data.default || (data.emotions && data.emotions[0]) || '';
      globalFilter = { ...globalFilter, ...(data.globalFilter || {}) };
      render();
      if (selected && items.some((x) => x.name === selected)) {
        selectEmotion(selected);
      } else if (items.length) {
        selectEmotion(items.find((x) => x.isDefault)?.name || items[0].name);
      } else {
        selected = null;
        setActionEnabled(false);
        const img = previewImg();
        if (img) img.hidden = true;
        const video = previewVideo();
        if (video) { video.pause(); video.hidden = true; }
      }
      const stat = document.getElementById('stat-emotions');
      if (stat) stat.textContent = String(items.length);
    } catch (e) {
      toast('加载表情失败', String(e.message || e), 'danger');
    }
  }

  async function uploadEmotion(file) {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch('/api/robot/emotions/upload', { method: 'POST', body: fd });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || '上传失败');
    const optimization = data.optimization || {};
    const detail = optimization.optimized
      ? `${data.emotion}（${Math.ceil(optimization.originalSizeBytes / 1024)} KB → ${Math.ceil(optimization.sizeBytes / 1024)} KB）`
      : `${data.emotion}（无需压缩）`;
    toast('上传成功', detail);
    await loadEmotionLibrary();
    selectEmotion(data.emotion);
  }

  async function setDefault() {
    if (!selected) return;
    const res = await fetch('/api/robot/emotions/default', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ emotion: selected }),
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || '设置失败');
    toast('已设为默认', selected);
    await loadEmotionLibrary();
  }

  async function saveEmotionStyle(style) {
    if (!selected) return;
    const res = await fetch(`/api/robot/emotions/${encodeURIComponent(selected)}/style`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(style),
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || '保存失败');
    toast('表情参数已保存', selected);
    await loadEmotionLibrary();
  }

  async function saveGlobalFilter(value) {
    const res = await fetch('/api/robot/emotions/global-filter', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(value),
    });
    const data = await res.json();
    if (!res.ok || !data.success) throw new Error(data.error || '保存失败');
    globalFilter = data.globalFilter;
    toast('全局表情滤镜已保存', value.enabled ? '已启用' : '未启用');
    await loadEmotionLibrary();
  }

  async function triggerEmotion() {
    if (!selected) return;
    const res = await fetch('/api/robot/emotions/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ emotion: selected }),
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || '触发失败');
    toast('已试触发', selected + '（本机 Socket）', 'warning');
  }

  async function deleteEmotion() {
    if (!selected) return;
    const item = items.find((x) => x.name === selected);
    let force = false;
    if (item && item.refCount > 0) {
      force = window.confirm(
        `「${selected}」仍被映射引用 ${item.refCount} 处。仍要强制删除吗？`
      );
      if (!force) return;
    } else if (!window.confirm(`确认删除 ${selected}？`)) {
      return;
    }
    const url = `/api/robot/emotions/${encodeURIComponent(selected)}${force ? '?force=1' : ''}`;
    const res = await fetch(url, { method: 'DELETE' });
    const data = await res.json();
    if (!data.success) {
      if (res.status === 409 && !force) {
        const ok = window.confirm((data.error || '仍被引用') + '\n强制删除？');
        if (ok) {
          const res2 = await fetch(
            `/api/robot/emotions/${encodeURIComponent(selected)}?force=1`,
            { method: 'DELETE' }
          );
          const data2 = await res2.json();
          if (!data2.success) throw new Error(data2.error || '删除失败');
        } else {
          return;
        }
      } else {
        throw new Error(data.error || '删除失败');
      }
    }
    toast('已删除', selected);
    selected = null;
    await loadEmotionLibrary();
  }

  document.addEventListener('DOMContentLoaded', () => {
    [...Object.values(styleFields), ...Object.values(globalFields)].forEach((id) => {
      byId(id)?.addEventListener('input', applyPreviewTuning);
    });
    byId('emotion-global-enabled')?.addEventListener('change', applyPreviewTuning);

    byId('btn-save-emotion-style')?.addEventListener('click', async () => {
      try {
        await saveEmotionStyle(readFields(styleFields));
      } catch (err) {
        toast('保存表情参数失败', String(err.message || err), 'danger');
      }
    });
    byId('btn-reset-emotion-style')?.addEventListener('click', async () => {
      try {
        await saveEmotionStyle(defaultStyle);
      } catch (err) {
        toast('恢复表情参数失败', String(err.message || err), 'danger');
      }
    });
    byId('btn-save-global-filter')?.addEventListener('click', async () => {
      try {
        await saveGlobalFilter({
          enabled: byId('emotion-global-enabled')?.checked === true,
          ...readFields(globalFields),
        });
      } catch (err) {
        toast('保存全局滤镜失败', String(err.message || err), 'danger');
      }
    });
    byId('btn-reset-global-filter')?.addEventListener('click', async () => {
      try {
        await saveGlobalFilter({
          enabled: false, hueDeg: 0, brightness: 1, saturation: 1, contrast: 1, opacity: 1,
        });
      } catch (err) {
        toast('恢复全局滤镜失败', String(err.message || err), 'danger');
      }
    });

    const input = document.getElementById('emotion-upload-input');
    if (input) {
      input.addEventListener('change', async (e) => {
        const file = e.target.files && e.target.files[0];
        e.target.value = '';
        if (!file) return;
        try {
          await uploadEmotion(file);
        } catch (err) {
          toast('上传失败', String(err.message || err), 'danger');
        }
      });
    }
    const refresh = document.getElementById('btn-refresh-emotions');
    if (refresh) refresh.addEventListener('click', () => loadEmotionLibrary());
    const setDef = document.getElementById('btn-set-default');
    if (setDef) {
      setDef.addEventListener('click', async () => {
        try {
          await setDefault();
        } catch (err) {
          toast('设置失败', String(err.message || err), 'danger');
        }
      });
    }
    const trigger = document.getElementById('btn-trigger-emotion');
    if (trigger) {
      trigger.addEventListener('click', async () => {
        try {
          await triggerEmotion();
        } catch (err) {
          toast('触发失败', String(err.message || err), 'danger');
        }
      });
    }
    const del = document.getElementById('btn-delete-emotion');
    if (del) {
      del.addEventListener('click', async () => {
        try {
          await deleteEmotion();
        } catch (err) {
          toast('删除失败', String(err.message || err), 'danger');
        }
      });
    }
  });

  window.loadEmotionLibrary = loadEmotionLibrary;
})();
