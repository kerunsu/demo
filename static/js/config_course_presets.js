/**
 * 配置中心 · 教师端课程预设
 * 预设只持久化有序 courseIds，课点始终来自当前课程库。
 */
(function () {
  let presets = [];
  let catalog = [];
  let current = null;

  function toast(title, detail, kind) {
    if (window.ccToast) window.ccToast(title, detail, kind);
  }

  function esc(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function copyPreset(preset) {
    return preset ? { ...preset, courseIds: [...(preset.courseIds || [])] } : null;
  }

  function courseById(courseId) {
    return catalog.find((course) => Number(course.id) === Number(courseId));
  }

  function renderList() {
    const list = document.getElementById('course-preset-list');
    const count = document.getElementById('course-preset-count');
    if (!list) return;
    if (count) count.textContent = `${presets.length} 个`;
    if (!presets.length) {
      list.innerHTML = '<div class="cc-preset-list-empty">尚未配置预设<br>点击右上角新增</div>';
      return;
    }
    list.innerHTML = presets.map((preset) => `
      <button type="button" class="cc-preset-list-item${current?.id === preset.id ? ' active' : ''}" data-preset-id="${esc(preset.id)}">
        <strong>${esc(preset.name)}</strong>
        <span class="cc-preset-list-meta">
          ${preset.isDefault ? '<span class="cc-badge primary">评估默认</span>' : ''}
          <span>${(preset.courseIds || []).length} 门课程</span>
        </span>
      </button>`).join('');
    list.querySelectorAll('[data-preset-id]').forEach((button) => {
      button.addEventListener('click', () => selectPreset(button.dataset.presetId));
    });
  }

  function renderEditor() {
    const empty = document.getElementById('course-preset-empty');
    const form = document.getElementById('course-preset-form');
    if (!empty || !form) return;
    if (!current) {
      empty.hidden = false;
      form.hidden = true;
      renderList();
      return;
    }
    empty.hidden = true;
    form.hidden = false;
    document.getElementById('course-preset-editor-title').textContent = current.id ? '编辑预设' : '新增预设';
    document.getElementById('course-preset-name').value = current.name || '';
    document.getElementById('course-preset-description').value = current.description || '';
    const defaultInput = document.getElementById('course-preset-default');
    defaultInput.checked = Boolean(current.isDefault);
    defaultInput.disabled = Boolean(current.id && current.isDefault);
    defaultInput.title = current.isDefault ? '评估默认必须始终保留；可在其他预设中切换默认。' : '';
    document.getElementById('btn-delete-course-preset').hidden = !current.id;
    renderSelectedCourses();
    renderCatalog();
    renderList();
  }

  function renderSelectedCourses() {
    const selected = document.getElementById('course-preset-selected');
    const count = document.getElementById('course-preset-selected-count');
    if (!selected || !current) return;
    if (count) count.textContent = `${current.courseIds.length} 门`;
    if (!current.courseIds.length) {
      selected.innerHTML = '<div class="cc-preset-list-empty">从右侧添加课程<br>添加顺序就是教师端使用顺序</div>';
      return;
    }
    selected.innerHTML = current.courseIds.map((courseId, index) => {
      const course = courseById(courseId);
      return `<div class="cc-preset-course-row" data-selected-index="${index}">
        <span class="cc-preset-course-order">${index + 1}</span>
        <span class="cc-preset-course-copy">
          <strong>${esc(course?.title || `已删除课程 #${courseId}`)}</strong>
          <span>${esc(course?.typeName || course?.type || '未知课型')} · ${course?.itemCount ?? 0} 个课点</span>
        </span>
        <span class="cc-preset-course-actions">
          <button type="button" class="cc-preset-icon-btn" data-action="up" title="上移" ${index === 0 ? 'disabled' : ''}>↑</button>
          <button type="button" class="cc-preset-icon-btn" data-action="down" title="下移" ${index === current.courseIds.length - 1 ? 'disabled' : ''}>↓</button>
          <button type="button" class="cc-preset-icon-btn" data-action="remove" title="移除">×</button>
        </span>
      </div>`;
    }).join('');
    selected.querySelectorAll('[data-selected-index]').forEach((row) => {
      const index = Number(row.dataset.selectedIndex);
      row.querySelectorAll('[data-action]').forEach((button) => {
        button.addEventListener('click', () => updateSelection(button.dataset.action, index));
      });
    });
  }

  function renderCatalog() {
    const container = document.getElementById('course-preset-catalog');
    if (!container || !current) return;
    const available = catalog.filter((course) => !current.courseIds.includes(Number(course.id)));
    if (!available.length) {
      container.innerHTML = '<div class="cc-preset-list-empty">课程库中的课程都已加入</div>';
      return;
    }
    container.innerHTML = available.map((course) => `
      <div class="cc-preset-course-row">
        <span class="cc-preset-course-copy">
          <strong>${esc(course.title)}</strong>
          <span>${esc(course.typeName || course.type || '未知课型')} · ${course.itemCount || 0} 个课点</span>
        </span>
        <button type="button" class="cc-btn soft small cc-preset-add-btn" data-add-course="${course.id}" ${course.itemCount > 0 ? '' : 'disabled title="请先为课程添加课点"'}>+ 添加</button>
      </div>`).join('');
    container.querySelectorAll('[data-add-course]').forEach((button) => {
      button.addEventListener('click', () => {
        current.courseIds.push(Number(button.dataset.addCourse));
        renderSelectedCourses();
        renderCatalog();
      });
    });
  }

  function updateSelection(action, index) {
    if (!current) return;
    if (action === 'remove') current.courseIds.splice(index, 1);
    if (action === 'up' && index > 0) {
      [current.courseIds[index - 1], current.courseIds[index]] = [current.courseIds[index], current.courseIds[index - 1]];
    }
    if (action === 'down' && index < current.courseIds.length - 1) {
      [current.courseIds[index + 1], current.courseIds[index]] = [current.courseIds[index], current.courseIds[index + 1]];
    }
    renderSelectedCourses();
    renderCatalog();
  }

  function selectPreset(presetId) {
    current = copyPreset(presets.find((preset) => preset.id === presetId));
    renderEditor();
  }

  function newPreset() {
    current = { id: null, name: '', description: '', courseIds: [], isDefault: presets.length === 0 };
    renderEditor();
    document.getElementById('course-preset-name')?.focus();
  }

  async function savePreset() {
    if (!current) return;
    const name = document.getElementById('course-preset-name').value.trim();
    const description = document.getElementById('course-preset-description').value.trim();
    const isDefault = document.getElementById('course-preset-default').checked;
    if (!name) {
      toast('无法保存', '请填写预设名称', 'danger');
      return;
    }
    if (!current.courseIds.length) {
      toast('无法保存', '请至少选择一门课程', 'danger');
      return;
    }
    let response;
    try {
      response = await fetch(current.id ? `/api/config/course-presets/${encodeURIComponent(current.id)}` : '/api/config/course-presets', {
        method: current.id ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description, courseIds: current.courseIds, isDefault }),
      });
    } catch (error) {
      toast('预设保存失败', String(error.message || error), 'danger');
      return;
    }
    const data = await response.json();
    if (!response.ok || !data.success) {
      toast('预设保存失败', data.error || `HTTP ${response.status}`, 'danger');
      return;
    }
    presets = data.presets || [];
    catalog = data.courseCatalog || catalog;
    current = copyPreset(data.preset);
    toast('预设已保存', name, 'success');
    renderEditor();
  }

  async function deletePreset() {
    if (!current?.id || !window.confirm(`删除课程预设“${current.name}”？`)) return;
    let response;
    try {
      response = await fetch(`/api/config/course-presets/${encodeURIComponent(current.id)}`, { method: 'DELETE' });
    } catch (error) {
      toast('预设删除失败', String(error.message || error), 'danger');
      return;
    }
    const data = await response.json();
    if (!response.ok || !data.success) {
      toast('预设删除失败', data.error || `HTTP ${response.status}`, 'danger');
      return;
    }
    presets = data.presets || [];
    catalog = data.courseCatalog || catalog;
    current = copyPreset(presets[0]);
    toast('预设已删除', '', 'success');
    renderEditor();
  }

  async function loadCoursePresetLibrary() {
    try {
      const response = await fetch('/api/config/course-presets');
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || `HTTP ${response.status}`);
      const selectedId = current?.id;
      presets = data.presets || [];
      catalog = data.courseCatalog || [];
      current = copyPreset(presets.find((preset) => preset.id === selectedId) || presets[0]);
      renderEditor();
    } catch (error) {
      toast('课程预设加载失败', String(error.message || error), 'danger');
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn-new-course-preset')?.addEventListener('click', newPreset);
    document.getElementById('btn-save-course-preset')?.addEventListener('click', savePreset);
    document.getElementById('btn-delete-course-preset')?.addEventListener('click', deletePreset);
  });

  window.loadCoursePresetLibrary = loadCoursePresetLibrary;
})();
