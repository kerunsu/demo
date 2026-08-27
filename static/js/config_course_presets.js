/**
 * 配置中心 · 教师端课程预设
 * schema v3 按评估/干预分别保存有序大类及明确课点 ID。
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

  function modeLabel(mode) {
    return mode === 'intervention' ? '干预' : '评估';
  }

  function copyPreset(preset) {
    if (!preset) return null;
    const courseSelections = Array.isArray(preset.courseSelections)
      ? preset.courseSelections.map((selection) => ({
          courseType: selection.courseType,
          itemIds: [...(selection.itemIds || [])].map(Number),
        }))
      : [];
    return { ...preset, mode: preset.mode || 'assessment', courseSelections };
  }

  function courseByType(courseType) {
    return catalog.find((course) => course.type === courseType);
  }

  function selectedItemCount(preset) {
    return (preset?.courseSelections || []).reduce(
      (total, selection) => total + (selection.itemIds || []).length,
      0,
    );
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
          <span class="cc-badge ${preset.mode === 'intervention' ? 'warning' : 'primary'}">${modeLabel(preset.mode)}</span>
          ${preset.isDefault ? `<span class="cc-badge primary">${modeLabel(preset.mode)}默认</span>` : ''}
          <span>${(preset.courseSelections || []).length} 类 / ${selectedItemCount(preset)} 课点</span>
        </span>
      </button>`).join('');
    list.querySelectorAll('[data-preset-id]').forEach((button) => {
      button.addEventListener('click', () => selectPreset(button.dataset.presetId));
    });
  }

  function updateDefaultLabel() {
    const label = document.getElementById('course-preset-default-label');
    const input = document.getElementById('course-preset-default');
    if (label) label.textContent = `设为${modeLabel(current?.mode)}默认`;
    if (input) {
      input.title = current?.isDefault
        ? `当前是${modeLabel(current.mode)}默认；要切换默认，请在同用途的另一方案中勾选。`
        : '';
    }
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
    document.getElementById('course-preset-mode').value = current.mode || 'assessment';
    document.getElementById('course-preset-name').value = current.name || '';
    document.getElementById('course-preset-description').value = current.description || '';
    const defaultInput = document.getElementById('course-preset-default');
    defaultInput.checked = Boolean(current.isDefault);
    defaultInput.disabled = false;
    updateDefaultLabel();
    document.getElementById('btn-delete-course-preset').hidden = !current.id;
    renderSelectedCourses();
    renderCatalog();
    renderList();
  }

  function renderSelectedCourses() {
    const selected = document.getElementById('course-preset-selected');
    const count = document.getElementById('course-preset-selected-count');
    if (!selected || !current) return;
    const selections = current.courseSelections || [];
    if (count) count.textContent = `${selections.length} 类 / ${selectedItemCount(current)} 课点`;
    if (!selections.length) {
      selected.innerHTML = '<div class="cc-preset-list-empty">从右侧添加课程大类<br>再勾选要使用的具体课点</div>';
      return;
    }
    selected.innerHTML = selections.map((selection, index) => {
      const course = courseByType(selection.courseType);
      const items = course?.items || [];
      const selectedIds = new Set((selection.itemIds || []).map(Number));
      const missingIds = [...selectedIds].filter((itemId) => !items.some((item) => Number(item.id) === itemId));
      return `<div class="cc-preset-selection-block" data-selected-index="${index}">
        <div class="cc-preset-course-row">
          <span class="cc-preset-course-order">${index + 1}</span>
          <span class="cc-preset-course-copy">
            <strong>${esc(course?.typeName || selection.courseType)}</strong>
            <span>已选 ${selectedIds.size}/${items.length} 个课点</span>
          </span>
          <span class="cc-preset-course-actions">
            <button type="button" class="cc-preset-icon-btn" data-action="up" title="上移" ${index === 0 ? 'disabled' : ''}>↑</button>
            <button type="button" class="cc-preset-icon-btn" data-action="down" title="下移" ${index === selections.length - 1 ? 'disabled' : ''}>↓</button>
            <button type="button" class="cc-preset-icon-btn" data-action="remove" title="移除">×</button>
          </span>
        </div>
        <div class="cc-preset-item-tools">
          <span>选择具体课点</span>
          <button type="button" data-item-action="all">全选</button>
          <button type="button" data-item-action="none">清空</button>
        </div>
        <div class="cc-preset-item-picker">
          ${items.map((item) => `
            <label class="cc-preset-item-option">
              <input type="checkbox" data-item-id="${Number(item.id)}" ${selectedIds.has(Number(item.id)) ? 'checked' : ''} />
              <span>${esc(item.name || `课点 ${item.id}`)}</span>
            </label>`).join('') || '<span class="cc-preset-item-empty">该大类暂无课点</span>'}
        </div>
        ${missingIds.length ? `<div class="cc-preset-item-warning">以下已选课点已从课程库移除：${missingIds.join('、')}。请重新勾选后保存。</div>` : ''}
      </div>`;
    }).join('');
    selected.querySelectorAll('[data-selected-index]').forEach((block) => {
      const index = Number(block.dataset.selectedIndex);
      block.querySelectorAll('[data-action]').forEach((button) => {
        button.addEventListener('click', () => updateSelection(button.dataset.action, index));
      });
      block.querySelectorAll('[data-item-id]').forEach((input) => {
        input.addEventListener('change', () => toggleItem(index, Number(input.dataset.itemId), input.checked));
      });
      block.querySelectorAll('[data-item-action]').forEach((button) => {
        button.addEventListener('click', () => setAllItems(index, button.dataset.itemAction === 'all'));
      });
    });
  }

  function renderCatalog() {
    const container = document.getElementById('course-preset-catalog');
    if (!container || !current) return;
    const selectedTypes = new Set((current.courseSelections || []).map((selection) => selection.courseType));
    const available = catalog.filter((course) => !selectedTypes.has(course.type));
    if (!available.length) {
      container.innerHTML = '<div class="cc-preset-list-empty">课程库中的课程都已加入</div>';
      return;
    }
    container.innerHTML = available.map((course) => `
      <div class="cc-preset-course-row">
        <span class="cc-preset-course-copy">
          <strong>${esc(course.typeName || course.type || '未知课型')}</strong>
          <span>${course.itemCount || 0} 个课点</span>
        </span>
        <button type="button" class="cc-btn soft small cc-preset-add-btn" data-add-course-type="${esc(course.type)}" ${course.itemCount > 0 ? '' : 'disabled title="请先为课程大类添加课点"'}>+ 添加</button>
      </div>`).join('');
    container.querySelectorAll('[data-add-course-type]').forEach((button) => {
      button.addEventListener('click', () => {
        current.courseSelections.push({ courseType: button.dataset.addCourseType, itemIds: [] });
        renderSelectedCourses();
        renderCatalog();
      });
    });
  }

  function toggleItem(index, itemId, checked) {
    const selection = current?.courseSelections?.[index];
    if (!selection) return;
    const ids = new Set((selection.itemIds || []).map(Number));
    if (checked) ids.add(itemId);
    else ids.delete(itemId);
    selection.itemIds = [...ids];
    current.isDefault = Boolean(current.isDefault);
    renderSelectedCourses();
  }

  function setAllItems(index, shouldSelect) {
    const selection = current?.courseSelections?.[index];
    const course = selection ? courseByType(selection.courseType) : null;
    if (!selection || !course) return;
    selection.itemIds = shouldSelect ? (course.items || []).map((item) => Number(item.id)) : [];
    renderSelectedCourses();
  }

  function updateSelection(action, index) {
    if (!current) return;
    const selections = current.courseSelections;
    if (action === 'remove') selections.splice(index, 1);
    if (action === 'up' && index > 0) {
      [selections[index - 1], selections[index]] = [selections[index], selections[index - 1]];
    }
    if (action === 'down' && index < selections.length - 1) {
      [selections[index + 1], selections[index]] = [selections[index], selections[index + 1]];
    }
    renderSelectedCourses();
    renderCatalog();
  }

  function selectPreset(presetId) {
    current = copyPreset(presets.find((preset) => preset.id === presetId));
    renderEditor();
  }

  function newPreset() {
    const mode = current?.mode || 'assessment';
    current = {
      id: null,
      mode,
      name: '',
      description: '',
      courseSelections: [],
      isDefault: !presets.some((preset) => preset.mode === mode),
    };
    renderEditor();
    document.getElementById('course-preset-name')?.focus();
  }

  async function savePreset() {
    if (!current) return;
    const mode = document.getElementById('course-preset-mode').value;
    const name = document.getElementById('course-preset-name').value.trim();
    const description = document.getElementById('course-preset-description').value.trim();
    const isDefault = document.getElementById('course-preset-default').checked;
    if (!name) {
      toast('无法保存', '请填写预设名称', 'danger');
      return;
    }
    if (!current.courseSelections.length) {
      toast('无法保存', '请至少选择一个课程大类', 'danger');
      return;
    }
    const incomplete = current.courseSelections.find((selection) => !(selection.itemIds || []).length);
    if (incomplete) {
      const course = courseByType(incomplete.courseType);
      toast('无法保存', `请为“${course?.typeName || incomplete.courseType}”至少勾选一个具体课点`, 'danger');
      return;
    }
    let response;
    try {
      response = await fetch(current.id ? `/api/config/course-presets/${encodeURIComponent(current.id)}` : '/api/config/course-presets', {
        method: current.id ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, name, description, courseSelections: current.courseSelections, isDefault }),
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
    toast('预设已保存', `${modeLabel(mode)} · ${name}`, 'success');
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
    document.getElementById('course-preset-mode')?.addEventListener('change', (event) => {
      if (!current) return;
      current.mode = event.target.value;
      current.isDefault = !presets.some(
        (preset) => preset.mode === current.mode && preset.id !== current.id,
      );
      document.getElementById('course-preset-default').checked = current.isDefault;
      updateDefaultLabel();
      renderList();
    });
  });

  window.loadCoursePresetLibrary = loadCoursePresetLibrary;
})();
