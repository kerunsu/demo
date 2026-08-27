/**
 * 配置中心壳：子视图切换 + toast
 */
(function () {
  const READY_VIEWS = new Set([
    'workbench',
    'animations',
    'media',
    'courses',
    'presets',
    'phrases',
  ]);
  const PLACEHOLDER = {};


  function toast(title, detail, kind) {
    const stack = document.getElementById('cc-toast-stack');
    if (!stack) return;
    const el = document.createElement('div');
    el.className = 'cc-toast' + (kind ? ' ' + kind : '');
    el.innerHTML = '<b></b><p></p>';
    el.querySelector('b').textContent = title;
    el.querySelector('p').textContent = detail || '';
    stack.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }
  window.ccToast = toast;

  function currentView() {
    const params = new URLSearchParams(window.location.search);
    return params.get('view') || 'workbench';
  }

  function setView(view, push) {
    const v = view || 'workbench';
    document.querySelectorAll('#cc-subnav button[data-view]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.view === v);
    });

    document.querySelectorAll('.cc-page[data-page]').forEach((page) => {
      page.hidden = true;
    });

    if (READY_VIEWS.has(v)) {
      const page = document.getElementById('page-' + v);
      if (page) page.hidden = false;
      if (v === 'animations' && typeof window.loadAnimationLibrary === 'function') {
        window.loadAnimationLibrary();
      }
      if (v === 'media' && typeof window.loadMediaLibrary === 'function') {
        window.loadMediaLibrary();
      }
      if (v === 'courses' && typeof window.loadCourseLibrary === 'function') {
        window.loadCourseLibrary();
      }
      if (v === 'presets' && typeof window.loadCoursePresetLibrary === 'function') {
        window.loadCoursePresetLibrary();
      }
      if (v === 'phrases' && typeof window.loadPhraseLibrary === 'function') {
        window.loadPhraseLibrary();
      }
    } else {
      const page = document.getElementById('page-placeholder');
      if (page) {
        page.hidden = false;
        const meta = PLACEHOLDER[v] || { title: '规划中', desc: '后续子阶段接通。' };
        const t = document.getElementById('placeholder-title');
        const d = document.getElementById('placeholder-desc');
        if (t) t.textContent = meta.title;
        if (d) d.textContent = meta.desc;
      }
    }

    if (push !== false) {
      const url = new URL(window.location.href);
      url.searchParams.set('view', v);
      window.history.replaceState({}, '', url);
    }
  }

  function bindSubnav() {
    document.querySelectorAll('#cc-subnav button[data-view]').forEach((btn) => {
      btn.addEventListener('click', () => setView(btn.dataset.view));
    });
  }

  async function refreshWorkbenchStats() {
    if (typeof window.refreshWorkbenchSummary === 'function') {
      window.refreshWorkbenchSummary();
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    const module = document.body.dataset.module || 'content';
    if (module === 'content' && currentView() === 'phase5') {
      window.location.replace('/server/config/devices');
      return;
    }
    if (module !== 'content') return;
    bindSubnav();
    setView(currentView(), false);
    refreshWorkbenchStats();
  });

  window.ccSetView = setView;
})();
