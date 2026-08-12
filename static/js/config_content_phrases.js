/** Server configuration for the browser-TTS phrase library. */
(function () {
  let courseTypes = [];
  let currentType = '';

  function toast(title, detail, kind) {
    window.ccToast?.(title, detail, kind);
  }

  function esc(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function intentLabel(intent) {
    return { question: '提问', hint: '提示', praise: '表扬' }[intent] || intent;
  }

  async function request(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || '操作失败');
    return data;
  }

  function currentCourse() {
    return courseTypes.find((item) => item.type === currentType) || courseTypes[0];
  }

  function renderTypeSelector() {
    const select = document.getElementById('phrase-course-type');
    if (!select) return;
    select.innerHTML = courseTypes
      .map((item) => `<option value="${esc(item.type)}">${esc(item.label)}</option>`)
      .join('');
    if (!currentType && courseTypes.length) currentType = courseTypes[0].type;
    select.value = currentType;
  }

  function renderSlots() {
    const root = document.getElementById('phrase-slots');
    const course = currentCourse();
    if (!root || !course) return;
    const selectedSets = (course.slots || []).map((slot) => new Set(slot.selected || []));
    const linkedCourses = course.courses || [];
    root.innerHTML = `<section class="cc-card">
      <div class="cc-toolbar" style="justify-content:space-between;">
        <h3 class="cc-card-title" style="margin:0;">联动课程</h3>
        <span class="cc-badge">${linkedCourses.length} 个课程</span>
      </div>
      <p class="cc-tiny" style="margin:8px 0 0;">新建或删除“${esc(course.label)}”课程后，刷新本页会自动更新。以下话术由这些课程共同使用。</p>
      <div class="cc-phrase-courses">${linkedCourses.length
        ? linkedCourses.map((item) => `<span class="cc-badge gray" title="课程 ID ${esc(item.id)}">${esc(item.title)}</span>`).join('')
        : '<span class="cc-tiny">当前还没有该大类课程；以后新建后会自动继承这里的话术。</span>'}</div>
    </section>` + (course.slots || [])
      .map((slot, index) => {
        const selected = selectedSets[index];
        const label = slot.label || intentLabel(slot.intent);
        return `<section class="cc-card" data-phrase-slot="${index}">
          <div class="cc-toolbar" style="justify-content:space-between;">
            <div><h3 class="cc-card-title" style="margin:0;">${esc(label)}</h3>
              <span class="cc-tiny">已选 ${selected.size} / 候选 ${(slot.library || []).length}</span></div>
            <button type="button" class="cc-btn primary small" data-save>保存选择</button>
          </div>
          <select class="cc-inp cc-phrase-select" multiple size="${Math.min(9, Math.max(3, (slot.library || []).length))}" aria-label="${esc(label)}候选语句">
            ${(slot.library || []).map((line) => `<option value="${esc(line)}" ${selected.has(line) ? 'selected' : ''}>${esc(line)}</option>`).join('')}
          </select>
          <p class="cc-tiny" style="margin:6px 0 0;">可多选；Windows 按 Ctrl、触屏可逐项选择。</p>
          <div class="cc-form-row" style="margin-top:12px;">
            <input class="cc-inp" data-new-text maxlength="200" placeholder="输入一条适合本课程的新语句" style="flex:1;min-width:260px;" />
            <button type="button" class="cc-btn soft" data-add>＋ 新增</button>
          </div>
        </section>`;
      })
      .join('');

    root.querySelectorAll('[data-phrase-slot]').forEach((card) => {
      const slotIndex = Number(card.dataset.phraseSlot);
      const slot = course.slots[slotIndex];
      card.querySelector('[data-save]')?.addEventListener('click', () => saveSlot(card, slot));
      card.querySelector('[data-add]')?.addEventListener('click', () => addPhrase(card, slot));
      card.querySelector('[data-new-text]')?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') addPhrase(card, slot);
      });
    });
  }

  async function saveSlot(card, slot) {
    const select = card.querySelector('.cc-phrase-select');
    const selected = Array.from(select?.selectedOptions || []).map((el) => el.value);
    if (!selected.length) {
      toast('不能保存', '每组至少选择一句话术', 'danger');
      return;
    }
    try {
      await request(`/api/config/phrases/${encodeURIComponent(slot.intent)}/${encodeURIComponent(slot.courseType)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected }),
      });
      toast('话术选择已保存', `${currentCourse().label} · ${slot.label || intentLabel(slot.intent)}`);
      await loadPhraseLibrary(true);
    } catch (error) {
      toast('保存失败', error.message, 'danger');
    }
  }

  async function addPhrase(card, slot) {
    const input = card.querySelector('[data-new-text]');
    const text = input?.value.trim();
    if (!text) {
      toast('请输入新话术', '', 'danger');
      return;
    }
    try {
      await request(`/api/config/phrases/${encodeURIComponent(slot.intent)}/${encodeURIComponent(slot.courseType)}/custom`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      toast('已加入本地语料库', text);
      await loadPhraseLibrary(true);
    } catch (error) {
      toast('新增失败', error.message, 'danger');
    }
  }

  async function loadPhraseLibrary(preserveType) {
    try {
      const data = await request('/api/config/phrases');
      courseTypes = data.courseTypes || [];
      if (!preserveType || !courseTypes.some((item) => item.type === currentType)) {
        currentType = courseTypes[0]?.type || '';
      }
      renderTypeSelector();
      renderSlots();
    } catch (error) {
      toast('话术库加载失败', error.message, 'danger');
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('phrase-course-type')?.addEventListener('change', (event) => {
      currentType = event.target.value;
      renderSlots();
    });
    document.getElementById('btn-refresh-phrases')?.addEventListener('click', () => loadPhraseLibrary(true));
  });

  window.loadPhraseLibrary = loadPhraseLibrary;
})();
