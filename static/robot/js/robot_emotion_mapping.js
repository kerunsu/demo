/**
 * Demo 配置中心 · 三级表情绑定。
 *
 * 与完整版本共享固定表情、表扬随机池、儿童屏动画和表情时间轴语义，
 * 但从页面、请求体到回读校验都不包含机械动作字段。
 */
(function () {
  const AUX_TYPES = ['attention', 'reward', 'praise', 'question', 'hint', 'silent'];
  const AUX_LABELS = {
    attention: '注意提醒',
    reward: '奖励反馈',
    praise: '表扬',
    question: '提问',
    hint: '提示',
    silent: '课点进入',
  };

  let mapping = { defaults: {}, courses: {} };
  let courses = [];
  let emotions = [];
  let animations = [];
  let defaultEmotion = '';

  const byId = (id) => document.getElementById(id);

  function toast(title, detail, kind = 'success') {
    if (typeof window.ccToast === 'function') window.ccToast(title, detail, kind);
    else console.log(title, detail);
  }

  async function jsonRequest(url, options = {}) {
    const response = await fetch(url, { cache: 'no-store', ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false) {
      throw new Error(data.message || data.error || `HTTP ${response.status}`);
    }
    return data;
  }

  function numberValue(input) {
    const value = Number.parseInt(input?.value || '0', 10);
    return Number.isFinite(value) && value >= 0 ? value : 0;
  }

  function currentScope() {
    const type = byId('expression-binding-scope')?.value || 'default';
    return {
      type,
      courseId: type === 'default' ? null : Number(byId('expression-binding-course')?.value || 0),
      itemId: type === 'item' ? Number(byId('expression-binding-item')?.value || 0) : null,
    };
  }

  function scopeConfig(scope) {
    if (scope.type === 'default') return mapping.defaults || {};
    const course = mapping.courses?.[String(scope.courseId)] || {};
    if (scope.type === 'course') return course;
    return course.items?.[String(scope.itemId)] || {};
  }

  function inheritedBinding(scope, auxType) {
    const explicit = scopeConfig(scope)?.[auxType];
    if (explicit) return { binding: explicit, explicit: true };
    if (scope.type === 'item') {
      const course = mapping.courses?.[String(scope.courseId)]?.[auxType];
      if (course) return { binding: course, explicit: false };
    }
    const fallback = mapping.defaults?.[auxType];
    if (fallback) return { binding: fallback, explicit: false };
    return { binding: {}, explicit: false };
  }

  function normalizeBinding(raw) {
    const value = raw && typeof raw === 'object' ? raw : {};
    const sequence = value.sequence && typeof value.sequence === 'object' ? value.sequence : {};
    const audio = sequence.audio && typeof sequence.audio === 'object' ? sequence.audio : {};
    const pool = Array.isArray(value.emotions)
      ? value.emotions.map(String).filter((item, index, all) => item && all.indexOf(item) === index)
      : [];
    return {
      emotion: String(value.emotion || defaultEmotion || emotions[0] || ''),
      emotions: pool,
      animation: String(value.animation || ''),
      sequence: {
        expressionMediaId: String(sequence.expressionMediaId || ''),
        expressionDurationMs: Math.max(0, Number(sequence.expressionDurationMs) || 0),
        audio: { offsetMs: Math.max(0, Number(audio.offsetMs) || 0) },
      },
    };
  }

  function optionMarkup(values, selected, emptyLabel = '') {
    const options = emptyLabel ? `<option value="">${emptyLabel}</option>` : '';
    return options + values.map((value) => (
      `<option value="${escapeHtml(value)}"${value === selected ? ' selected' : ''}>${escapeHtml(value)}</option>`
    )).join('');
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"]/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;',
    }[char]));
  }

  function renderCard(auxType, scope) {
    const resolved = inheritedBinding(scope, auxType);
    const binding = normalizeBinding(resolved.binding);
    const randomEnabled = auxType === 'praise' && binding.emotions.length > 0;
    const card = document.createElement('section');
    card.className = 'cc-card expression-binding-card';
    card.dataset.auxType = auxType;
    card.innerHTML = `
      <div class="expression-binding-card-head">
        <div><h2>${AUX_LABELS[auxType]}</h2><span class="cc-badge ${resolved.explicit ? 'primary' : 'gray'}">${resolved.explicit ? '本层已配置' : '继承上层'}</span></div>
        <div class="expression-binding-actions">
          <button type="button" class="cc-btn soft small" data-action="preview">试播表情</button>
          <button type="button" class="cc-btn danger small" data-action="delete"${resolved.explicit ? '' : ' disabled'}>删除本层</button>
          <button type="button" class="cc-btn primary small" data-action="save">保存本层</button>
        </div>
      </div>
      <div class="expression-binding-fields">
        <label>表情模式
          <select class="cc-inp" data-field="mode"${auxType === 'praise' ? '' : ' disabled'}>
            <option value="fixed"${randomEnabled ? '' : ' selected'}>固定表情</option>
            ${auxType === 'praise' ? `<option value="random"${randomEnabled ? ' selected' : ''}>随机表情池</option>` : ''}
          </select>
        </label>
        <label>固定表情
          <select class="cc-inp" data-field="emotion">${optionMarkup(emotions, binding.emotion)}</select>
        </label>
        <label>儿童屏动画
          <select class="cc-inp" data-field="animation">${optionMarkup(animations, binding.animation, '不播放儿童屏动画')}</select>
        </label>
        <label>时间轴表情覆盖
          <select class="cc-inp" data-field="expressionMediaId">${optionMarkup(emotions, binding.sequence.expressionMediaId, '使用固定/随机表情')}</select>
        </label>
        <label>表情总时长（毫秒）
          <input class="cc-inp" data-field="expressionDurationMs" type="number" min="0" step="10" value="${binding.sequence.expressionDurationMs}" />
        </label>
        <label>语音开始偏移（毫秒）
          <input class="cc-inp" data-field="audioOffsetMs" type="number" min="0" step="10" value="${binding.sequence.audio.offsetMs}" />
        </label>
      </div>
      ${auxType === 'praise' ? `
        <div class="expression-praise-pool" data-pool ${randomEnabled ? '' : ' hidden'}>
          <strong>表扬随机表情池（至少选 2 个）</strong>
          <div class="expression-praise-options">
            ${emotions.map((name) => `<label title="${escapeHtml(name)}"><input type="checkbox" value="${escapeHtml(name)}"${binding.emotions.includes(name) ? ' checked' : ''} /><span>${escapeHtml(name)}</span></label>`).join('')}
          </div>
        </div>` : ''}
      <p class="cc-tiny expression-binding-status" role="status"></p>
    `;
    card.querySelector('[data-field="mode"]')?.addEventListener('change', (event) => {
      const pool = card.querySelector('[data-pool]');
      if (pool) pool.hidden = event.target.value !== 'random';
    });
    card.querySelector('[data-action="save"]')?.addEventListener('click', () => saveCard(card, scope));
    card.querySelector('[data-action="delete"]')?.addEventListener('click', () => deleteCard(card, scope));
    card.querySelector('[data-action="preview"]')?.addEventListener('click', () => previewCard(card, scope));
    return card;
  }

  function readCard(card) {
    const auxType = card.dataset.auxType;
    const mode = card.querySelector('[data-field="mode"]')?.value || 'fixed';
    const checked = [...card.querySelectorAll('[data-pool] input:checked')].map((item) => item.value);
    const fixed = card.querySelector('[data-field="emotion"]')?.value || defaultEmotion;
    const pool = auxType === 'praise' && mode === 'random' ? checked : [];
    if (pool.length && pool.length < 2) throw new Error('随机表扬表情池至少需要选择 2 个表情');
    return {
      emotion: pool[0] || fixed,
      emotions: pool,
      animation: card.querySelector('[data-field="animation"]')?.value || '',
      sequence: {
        expressionMediaId: card.querySelector('[data-field="expressionMediaId"]')?.value || '',
        expressionDurationMs: numberValue(card.querySelector('[data-field="expressionDurationMs"]')),
        audio: { offsetMs: numberValue(card.querySelector('[data-field="audioOffsetMs"]')) },
      },
    };
  }

  function endpoint(scope, auxType) {
    if (scope.type === 'default') return `/api/robot/mapping/defaults/${auxType}`;
    if (scope.type === 'course') return `/api/robot/mapping/course/${scope.courseId}/${auxType}`;
    return `/api/robot/mapping/course/${scope.courseId}/item/${scope.itemId}/${auxType}`;
  }

  async function saveCard(card, scope) {
    const status = card.querySelector('.expression-binding-status');
    try {
      const binding = readCard(card);
      status.textContent = '正在保存…';
      await jsonRequest(endpoint(scope, card.dataset.auxType), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(binding),
      });
      await reloadMapping();
      toast('表情绑定已保存', `${AUX_LABELS[card.dataset.auxType]} · 不含机械动作`);
    } catch (error) {
      status.textContent = error.message;
      toast('保存失败', error.message, 'danger');
    }
  }

  async function deleteCard(card, scope) {
    const status = card.querySelector('.expression-binding-status');
    try {
      status.textContent = '正在删除本层覆盖…';
      await jsonRequest(endpoint(scope, card.dataset.auxType), { method: 'DELETE' });
      await reloadMapping();
      toast('本层表情绑定已删除', '现在继承上一级配置');
    } catch (error) {
      status.textContent = error.message;
      toast('删除失败', error.message, 'danger');
    }
  }

  async function previewCard(card, scope) {
    const status = card.querySelector('.expression-binding-status');
    try {
      const binding = readCard(card);
      status.textContent = '正在提交表情试播…';
      const result = await jsonRequest('/api/robot/sequence/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...binding,
          auxType: card.dataset.auxType,
          courseId: scope.courseId,
          itemId: scope.itemId,
        }),
      });
      status.textContent = `已排队：${result.emotion || binding.emotion}`;
      toast('表情试播已提交', result.emotion || binding.emotion, 'warning');
    } catch (error) {
      status.textContent = error.message;
      toast('试播失败', error.message, 'danger');
    }
  }

  function renderScopeSelectors() {
    const scope = currentScope();
    const courseWrap = byId('expression-binding-course-wrap');
    const itemWrap = byId('expression-binding-item-wrap');
    if (courseWrap) courseWrap.hidden = scope.type === 'default';
    if (itemWrap) itemWrap.hidden = scope.type !== 'item';

    const courseSelect = byId('expression-binding-course');
    if (courseSelect) {
      const previous = String(scope.courseId || courseSelect.value || courses[0]?.id || '');
      courseSelect.innerHTML = courses.map((course) => (
        `<option value="${course.id}">${escapeHtml(course.title || course.type || `课程 ${course.id}`)}</option>`
      )).join('');
      if (courses.some((course) => String(course.id) === previous)) courseSelect.value = previous;
    }
    renderItemSelector();
  }

  function renderItemSelector() {
    const courseId = Number(byId('expression-binding-course')?.value || courses[0]?.id || 0);
    const course = courses.find((item) => Number(item.id) === courseId);
    const itemSelect = byId('expression-binding-item');
    if (!itemSelect) return;
    const previous = itemSelect.value;
    const items = Array.isArray(course?.items) ? course.items : [];
    itemSelect.innerHTML = items.map((item) => (
      `<option value="${item.id}">${escapeHtml(item.name || `课点 ${item.id}`)}</option>`
    )).join('');
    if (items.some((item) => String(item.id) === previous)) itemSelect.value = previous;
  }

  function renderBindings() {
    renderScopeSelectors();
    const scope = currentScope();
    const root = byId('expression-binding-grid');
    if (!root) return;
    root.innerHTML = '';
    AUX_TYPES.forEach((auxType) => root.appendChild(renderCard(auxType, scope)));
    const note = byId('expression-binding-scope-note');
    if (note) {
      note.textContent = scope.type === 'default'
        ? '当前：全局通用表情'
        : scope.type === 'course'
          ? `当前：课程 ${scope.courseId}`
          : `当前：课程 ${scope.courseId} / 课点 ${scope.itemId || '无'}`;
    }
  }

  async function reloadMapping() {
    const result = await jsonRequest('/api/robot/mapping/full');
    mapping = result.mapping || { defaults: {}, courses: {} };
    renderBindings();
  }

  async function initialize() {
    if (!byId('expression-binding-grid')) return;
    try {
      const [mappingResult, coursesResult, emotionResult, animationResult] = await Promise.all([
        jsonRequest('/api/robot/mapping/full'),
        jsonRequest('/api/robot/courses'),
        jsonRequest('/api/robot/emotions'),
        jsonRequest('/api/robot/animations'),
      ]);
      mapping = mappingResult.mapping || { defaults: {}, courses: {} };
      courses = Array.isArray(coursesResult.courses) ? coursesResult.courses : [];
      emotions = Array.isArray(emotionResult.emotions) ? emotionResult.emotions : [];
      animations = Array.isArray(animationResult.animations) ? animationResult.animations : [];
      defaultEmotion = emotionResult.default || emotions[0] || '';
      renderBindings();
    } catch (error) {
      const note = byId('expression-binding-scope-note');
      if (note) note.textContent = `加载失败：${error.message}`;
      toast('表情绑定加载失败', error.message, 'danger');
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    byId('expression-binding-scope')?.addEventListener('change', renderBindings);
    byId('expression-binding-course')?.addEventListener('change', () => {
      renderItemSelector();
      renderBindings();
    });
    byId('expression-binding-item')?.addEventListener('change', renderBindings);
    byId('btn-refresh-expression-bindings')?.addEventListener('click', initialize);
    initialize();
  });
})();
