/**
 * 配置中心 · 课程库 / 课点编辑
 * 普通课：提问/表扬按课型写 audio_manifest；课点 hint 写 DB
 * 社交课：课程级无提问/表扬；课点配置四按钮语音写 manifest
 */
(function () {
  let types = [];
  let courses = [];
  let currentCourse = null;
  let filterType = '';
  let typeAudioDefaults = null; // { question, praise, hint, social? }

  function toast(t, d, k) {
    if (window.ccToast) window.ccToast(t, d, k);
  }

  function esc(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function isSocialCourse(c) {
    return c?.type === 'social' || c?.audioConfigMode === 'social';
  }

  function audioCell(val) {
    if (val === null || val === undefined) return '—';
    return val ? '✓' : '—';
  }

  async function loadCourseLibrary() {
    try {
      const [tRes, cRes] = await Promise.all([
        fetch('/api/config/course-types').then((r) => r.json()),
        fetch('/api/config/courses' + (filterType ? `?type=${encodeURIComponent(filterType)}` : '')).then((r) =>
          r.json()
        ),
      ]);
      if (tRes.success) types = tRes.types || [];
      if (cRes.success) courses = cRes.courses || [];
      renderTypeFilter();
      renderCourseList();
      const stat = document.getElementById('stat-courses');
      if (stat) stat.textContent = String(courses.length);
      if (currentCourse) {
        await openCourse(currentCourse.id);
      } else {
        showList();
      }
    } catch (e) {
      toast('课程加载失败', String(e.message || e), 'danger');
    }
  }

  function renderTypeFilter() {
    const sel = document.getElementById('course-type-filter');
    if (!sel) return;
    const cur = filterType;
    sel.innerHTML =
      '<option value="">全部课型</option>' +
      types.map((t) => `<option value="${esc(t.type)}">${esc(t.name)}</option>`).join('');
    sel.value = cur;
  }

  function renderCourseList() {
    const el = document.getElementById('course-list');
    if (!el) return;
    if (!courses.length) {
      el.innerHTML = '<p class="cc-tiny">暂无课程，点击「新建课程」。</p>';
      return;
    }
    el.innerHTML = `
      <table class="cc-table">
        <thead><tr>
          <th>标题</th><th>课型</th><th>课点</th><th>提问音</th><th>表扬音</th><th>映射</th><th></th>
        </tr></thead>
        <tbody>
          ${courses
            .map(
              (c) => `<tr>
            <td>${esc(c.title)}</td>
            <td>${esc(c.courseTypeName || c.type)}</td>
            <td>${c.itemCount ?? (c.items || []).length}</td>
            <td title="${isSocialCourse(c) ? '社交课不适用' : '课型共享（manifest）'}">${audioCell(c.hasQuestionAudio)}</td>
            <td title="${isSocialCourse(c) ? '社交课不适用' : '课型共享（manifest）'}">${audioCell(c.hasPraiseAudio)}</td>
            <td>${c.hasBehaviorMapping ? '✓' : '—'}</td>
            <td><button type="button" class="cc-btn soft small" data-id="${c.id}">编辑</button></td>
          </tr>`
            )
            .join('')}
        </tbody>
      </table>`;
    el.querySelectorAll('button[data-id]').forEach((btn) => {
      btn.addEventListener('click', () => openCourse(Number(btn.dataset.id)));
    });
  }

  function showList() {
    document.getElementById('course-list-panel')?.removeAttribute('hidden');
    document.getElementById('course-detail-panel')?.setAttribute('hidden', '');
    currentCourse = null;
    typeAudioDefaults = null;
    setOrderingQuestionUi(false);
  }

  function setQpRowVisible(visible) {
    document.querySelectorAll('[data-qp-row]').forEach((row) => {
      if (visible) row.removeAttribute('hidden');
      else row.setAttribute('hidden', '');
    });
  }

  function setOrderingQuestionUi(visible, slots) {
    const box = document.getElementById('cd-ordering-questions');
    const genericQ = document.querySelector('[data-generic-question]');
    if (!box) return;
    if (!visible) {
      box.setAttribute('hidden', '');
      box.innerHTML = '';
      if (genericQ) genericQ.removeAttribute('hidden');
      return;
    }
    if (genericQ) genericQ.setAttribute('hidden', '');
    box.removeAttribute('hidden');
    const list = Array.isArray(slots) ? slots : [];
    box.innerHTML = `
      <p class="cc-tiny" style="margin:0 0 6px;">排序提问按题型分别配置（大小/长短/高矮/多少 × 选大或选小等），切题时自动播放对应语音。</p>
      ${list
        .map(
          (s) => `<div class="cc-form-row" style="margin:4px 0;">
        <label style="flex:1;">${esc(s.label)}
          <input class="cc-inp" data-ordering-q="${esc(s.key)}" value="${esc(s.filePath || '')}" style="min-width:260px;" />
        </label>
        <button type="button" class="cc-btn soft small" data-pick-ordering="${esc(s.key)}">选择</button>
      </div>`
        )
        .join('')}`;
    box.querySelectorAll('[data-pick-ordering]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const key = btn.getAttribute('data-pick-ordering');
        window.openMediaPicker({ root: 'audios' }, (path) => {
          const inp = box.querySelector(`[data-ordering-q="${key}"]`);
          if (inp) inp.value = path;
        });
      });
    });
  }

  async function fetchTypeAudio(courseType) {
    const res = await fetch(`/api/config/audio/course-defaults/${encodeURIComponent(courseType)}`);
    const data = await res.json();
    if (!data.success) throw new Error(data.error || '加载课型语音失败');
    return data.defaults;
  }

  async function openCourse(id) {
    try {
      const res = await fetch(`/api/config/courses/${id}`);
      const data = await res.json();
      if (!data.success) throw new Error(data.error || '加载失败');
      currentCourse = data.course;
      document.getElementById('course-list-panel')?.setAttribute('hidden', '');
      document.getElementById('course-detail-panel')?.removeAttribute('hidden');
      document.getElementById('cd-title').value = currentCourse.title || '';
      document.getElementById('cd-type').textContent =
        currentCourse.courseTypeName || currentCourse.type || '';
      document.getElementById('cd-entry').value = currentCourse.file || '';

      const social = isSocialCourse(currentCourse);
      const isOrdering = currentCourse.type === 'ordering';
      setQpRowVisible(!social);

      if (!social) {
        typeAudioDefaults = await fetchTypeAudio(currentCourse.type);
        document.getElementById('cd-question').value =
          typeAudioDefaults?.question?.filePath || '';
        document.getElementById('cd-praise').value =
          typeAudioDefaults?.praise?.filePath || '';
        const hintHint = document.getElementById('cd-type-audio-hint');
        if (hintHint) {
          hintHint.textContent = isOrdering
            ? '排序课提问分八种题型配置；表扬为本课型共享。保存课程时写入 audio_manifest。'
            : '提问/表扬为本课型共享（写入 audio_manifest），保存课程时同步。';
        }
        setOrderingQuestionUi(isOrdering, typeAudioDefaults?.orderingQuestions);
      } else {
        typeAudioDefaults = await fetchTypeAudio('social').catch(() => null);
        document.getElementById('cd-question').value = '';
        document.getElementById('cd-praise').value = '';
        setOrderingQuestionUi(false);
      }

      renderItems(currentCourse.items || []);
    } catch (e) {
      toast('打开课程失败', String(e.message || e), 'danger');
    }
  }

  function renderItems(items) {
    const el = document.getElementById('cd-items');
    if (!el) return;
    if (!items.length) {
      el.innerHTML = '<p class="cc-tiny">暂无课点</p>';
      return;
    }

    const social = isSocialCourse(currentCourse);
    if (social) {
      el.innerHTML = `
        <table class="cc-table">
          <thead><tr>
            <th>#</th><th>显示名</th><th>按钮语音</th><th>媒体</th><th>操作</th>
          </tr></thead>
          <tbody>
            ${items
              .map((it, i) => {
                const media = it.file || it.mediaFile || '';
                const buttons = it.socialButtons || [];
                const btnHtml = buttons.length
                  ? buttons
                      .map(
                        (b) => `<div class="cc-form-row" style="margin:4px 0;gap:6px;flex-wrap:wrap;">
                      <span class="cc-tiny" style="min-width:5em;">${esc(b.label)}</span>
                      <span class="cc-tiny" data-social-path="${esc(b.entryId)}">${esc(b.filePath) || '—'}</span>
                      <button type="button" class="cc-btn soft small" data-act="pick-social" data-entry="${esc(b.entryId)}">选</button>
                    </div>`
                      )
                      .join('')
                  : '<span class="cc-tiny">无 socialRole</span>';
                return `<tr data-item-id="${it.id}">
              <td>${i + 1}</td>
              <td><input class="cc-inp" data-f="name" value="${esc(it.name)}" /></td>
              <td>${btnHtml}</td>
              <td>
                <span class="cc-tiny">${esc(media) || '—'}</span>
                <button type="button" class="cc-btn soft small" data-act="pick-media">选</button>
              </td>
              <td>
                <button type="button" class="cc-btn soft small" data-act="save">存</button>
                <button type="button" class="cc-btn soft small" data-act="bind" title="仅机器人动作/表情">配行为</button>
                <button type="button" class="cc-btn danger small" data-act="del">删</button>
              </td>
            </tr>`;
              })
              .join('')}
          </tbody>
        </table>
        <p class="cc-tiny" style="margin-top:8px;">按钮语音写入 audio_manifest；「配行为」只配机器人，不含语音。</p>`;
    } else {
      el.innerHTML = `
        <table class="cc-table">
          <thead><tr>
            <th>#</th><th>显示名</th><th>语音目标</th><th>媒体</th><th>hint</th><th>操作</th>
          </tr></thead>
          <tbody>
            ${items
              .map((it, i) => {
                const media = it.file || it.mediaFile || '';
                const folder = media.endsWith('/');
                return `<tr data-item-id="${it.id}">
              <td>${i + 1}</td>
              <td><input class="cc-inp" data-f="name" value="${esc(it.name)}" /></td>
              <td><input class="cc-inp" data-f="speechTarget" value="${esc(it.speechTarget || '')}" placeholder="空=用显示名" /></td>
              <td>
                <span class="cc-tiny">${folder ? '📁 ' : ''}${esc(media) || '—'}</span>
                <button type="button" class="cc-btn soft small" data-act="pick-media">选</button>
              </td>
              <td>
                <span class="cc-tiny">${esc(it.hint || it.hintAudio || '') || '—'}</span>
                <button type="button" class="cc-btn soft small" data-act="pick-hint">选</button>
              </td>
              <td>
                <button type="button" class="cc-btn soft small" data-act="save">存</button>
                <button type="button" class="cc-btn soft small" data-act="bind">配行为</button>
                <button type="button" class="cc-btn danger small" data-act="del">删</button>
              </td>
            </tr>`;
              })
              .join('')}
          </tbody>
        </table>`;
    }

    el.querySelectorAll('tr[data-item-id]').forEach((row) => {
      const id = Number(row.dataset.itemId);
      row.querySelector('[data-act="save"]')?.addEventListener('click', () => saveItemRow(row, id));
      row.querySelector('[data-act="del"]')?.addEventListener('click', () => deleteItem(id));
      row.querySelector('[data-act="bind"]')?.addEventListener('click', () => {
        const url = `/server/config/content?view=binding&courseId=${currentCourse.id}&itemId=${id}`;
        window.location.href = url;
      });
      row.querySelector('[data-act="pick-media"]')?.addEventListener('click', () => {
        window.openMediaPicker({ root: 'images' }, async (path) => {
          await patchItem(id, { mediaFile: path });
          await openCourse(currentCourse.id);
        });
      });
      row.querySelector('[data-act="pick-hint"]')?.addEventListener('click', () => {
        window.openMediaPicker({ root: 'audios' }, async (path) => {
          await patchItem(id, { hintAudio: path });
          await openCourse(currentCourse.id);
        });
      });
      row.querySelectorAll('[data-act="pick-social"]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const entryId = btn.dataset.entry;
          window.openMediaPicker({ root: 'audios' }, async (path) => {
            const res = await fetch(`/api/config/audio/entries/${encodeURIComponent(entryId)}`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ filePath: path }),
            });
            const data = await res.json();
            if (!data.success) {
              toast('保存语音失败', data.error || '', 'danger');
              return;
            }
            toast('已更新按钮语音', entryId);
            await openCourse(currentCourse.id);
          });
        });
      });
    });
  }

  async function saveItemRow(row, id) {
    const name = row.querySelector('[data-f="name"]')?.value;
    const speechTarget = row.querySelector('[data-f="speechTarget"]')?.value;
    const body = { name };
    if (speechTarget !== undefined) body.speechTarget = speechTarget || null;
    await patchItem(id, body);
    toast('课点已保存', String(id));
  }

  async function patchItem(id, body) {
    const res = await fetch(`/api/config/items/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || '保存失败');
    return data.item;
  }

  async function deleteItem(id) {
    if (!window.confirm('删除该课点？')) return;
    const res = await fetch(`/api/config/items/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (!data.success) {
      toast('删除失败', data.error || '', 'danger');
      return;
    }
    toast('已删除课点', String(id));
    await openCourse(currentCourse.id);
  }

  async function saveCourseMeta() {
    if (!currentCourse) return;
    const body = {
      title: document.getElementById('cd-title').value,
      entryFile: document.getElementById('cd-entry').value || null,
    };
    const res = await fetch(`/api/config/courses/${currentCourse.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!data.success) {
      toast('保存失败', data.error || '', 'danger');
      return;
    }

    // 非社交：提问/表扬写入课型 manifest
    if (!isSocialCourse(currentCourse)) {
      const p = document.getElementById('cd-praise').value || '';
      const payload = {};
      if (p) payload.praise = p;
      if (currentCourse.type === 'ordering') {
        document.querySelectorAll('[data-ordering-q]').forEach((inp) => {
          const key = inp.getAttribute('data-ordering-q');
          const v = (inp.value || '').trim();
          if (key && v) payload[key] = v;
        });
      } else {
        const q = document.getElementById('cd-question').value || '';
        if (q) payload.question = q;
      }
      if (Object.keys(payload).length) {
        const aRes = await fetch(
          `/api/config/audio/course-defaults/${encodeURIComponent(currentCourse.type)}`,
          {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          }
        );
        const aData = await aRes.json();
        if (!aData.success) {
          toast('课型语音保存失败', aData.error || '', 'danger');
          return;
        }
      }
    }

    toast('课程已保存', currentCourse.title);
    await loadCourseLibrary();
    await openCourse(currentCourse.id);
  }

  async function createCourse() {
    const title = window.prompt('课程标题');
    if (!title) return;
    const typeOpts = types.map((t) => t.type).join(', ');
    const type = window.prompt(`课型英文（只读选择现有）: ${typeOpts}`, types[0]?.type || 'naming');
    if (!type) return;
    const res = await fetch('/api/config/courses', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, type }),
    });
    const data = await res.json();
    if (!data.success) {
      toast('创建失败', data.error || '', 'danger');
      return;
    }
    toast('已创建', title);
    filterType = '';
    await loadCourseLibrary();
    await openCourse(data.course.id);
  }

  async function addItem() {
    if (!currentCourse) return;
    const name = window.prompt('课点显示名');
    if (!name) return;
    const res = await fetch(`/api/config/courses/${currentCourse.id}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, type: 'image' }),
    });
    const data = await res.json();
    if (!data.success) {
      toast('添加失败', data.error || '', 'danger');
      return;
    }
    await openCourse(currentCourse.id);
  }

  async function deleteCourse() {
    if (!currentCourse) return;
    if (!window.confirm(`硬删除课程「${currentCourse.title}」及其课点？`)) return;
    let res = await fetch(`/api/config/courses/${currentCourse.id}`, { method: 'DELETE' });
    let data = await res.json();
    if (res.status === 409) {
      if (!window.confirm((data.error || '仍被映射引用') + '\n强制删除？')) return;
      res = await fetch(`/api/config/courses/${currentCourse.id}?force=1`, { method: 'DELETE' });
      data = await res.json();
    }
    if (!data.success) {
      toast('删除失败', data.error || '', 'danger');
      return;
    }
    toast('已删除课程', '');
    currentCourse = null;
    await loadCourseLibrary();
    showList();
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('course-type-filter')?.addEventListener('change', (e) => {
      filterType = e.target.value;
      currentCourse = null;
      loadCourseLibrary();
    });
    document.getElementById('btn-new-course')?.addEventListener('click', () => createCourse());
    document.getElementById('btn-course-back')?.addEventListener('click', async () => {
      currentCourse = null;
      await loadCourseLibrary();
      showList();
    });
    document.getElementById('btn-course-save')?.addEventListener('click', () => saveCourseMeta());
    document.getElementById('btn-course-delete')?.addEventListener('click', () => deleteCourse());
    document.getElementById('btn-add-item')?.addEventListener('click', () => addItem());
    document.getElementById('btn-pick-question')?.addEventListener('click', () => {
      window.openMediaPicker({ root: 'audios' }, (path) => {
        document.getElementById('cd-question').value = path;
      });
    });
    document.getElementById('btn-pick-praise')?.addEventListener('click', () => {
      window.openMediaPicker({ root: 'audios' }, (path) => {
        document.getElementById('cd-praise').value = path;
      });
    });
    document.getElementById('btn-course-binding')?.addEventListener('click', () => {
      if (!currentCourse) return;
      window.location.href = `/server/config/content?view=binding&courseId=${currentCourse.id}`;
    });
  });

  window.loadCourseLibrary = loadCourseLibrary;
})();
