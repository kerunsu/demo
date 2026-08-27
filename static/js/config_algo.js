/**
 * 配置中心 · 算法/评分/运行时环境（原 F-Algo + YAML 迁移）
 */
(function () {
  const SCOPE_KEY = 'cc_apply_scope';

  function toast(t, d, k) {
    if (window.ccToast) window.ccToast(t, d, k);
    else console.log(t, d);
  }

  function moduleName() {
    return document.body.dataset.module || 'content';
  }

  let analyzersConfig = null;
  let cameraConfig = null;
  let reportConfig = null;
  let dirty = { cam: false, attn: false, speech: false, report: false };

  function setDirty(key, on) {
    dirty[key] = !!on;
    const map = {
      cam: 'cam-dirty',
      attn: 'attn-dirty',
      speech: 'speech-dirty',
      report: 'report-dirty',
    };
    const el = document.getElementById(map[key]);
    if (el) el.textContent = on ? '有未保存修改' : '';
  }

  function field(label, html, help) {
    return `<div class="cc-field"><label class="cc-field-label">${label}</label>${html}${
      help ? `<div class="cc-tiny">${help}</div>` : ''
    }</div>`;
  }

  function boolSelect(id, val) {
    return `<select class="cc-inp" id="${id}">
      <option value="true"${val ? ' selected' : ''}>是</option>
      <option value="false"${!val ? ' selected' : ''}>否</option>
    </select>`;
  }

  function modeSelect(id, val) {
    const v = val == null || val === '' ? '' : String(val);
    return `<select class="cc-inp" id="${id}">
      <option value=""${v === '' ? ' selected' : ''}>继承 global</option>
      <option value="real"${v === 'real' ? ' selected' : ''}>real</option>
      <option value="mock"${v === 'mock' ? ' selected' : ''}>mock</option>
    </select>`;
  }

  function esc(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/"/g, '&quot;');
  }

  async function fetchJson(url, opts) {
    const res = await fetch(url, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.success === false) {
      throw new Error(data.error || data.errors?.join?.(';') || `HTTP ${res.status}`);
    }
    return data;
  }

  function getApplyScope() {
    const el = document.getElementById('ov-apply-scope');
    if (el && el.value) return el.value;
    try {
      return localStorage.getItem(SCOPE_KEY) || 'new_sessions_only';
    } catch (_) {
      return 'new_sessions_only';
    }
  }

  function persistApplyScope(v) {
    try {
      localStorage.setItem(SCOPE_KEY, v);
    } catch (_) {}
  }

  // ---------- Overview ----------
  let runtimeBaseline = { child: 'browser', robot: 'disabled', wakeWord: 'false', speechRate: '0.88' };

  function fillRuntimeSelects(mediaMode, robotMode, wakeWordEnabled, speechRate) {
    const m = document.getElementById('ov-child-media');
    const r = document.getElementById('ov-robot-mode');
    const w = document.getElementById('ov-wake-word');
    const s = document.getElementById('ov-speech-rate');
    const sv = document.getElementById('ov-speech-rate-value');
    if (m) m.value = 'browser';
    if (r) r.value = 'disabled';
    if (w) w.value = wakeWordEnabled === true ? 'true' : 'false';
    if (s) s.value = String(Number(speechRate) || 0.88);
    if (sv) sv.textContent = `${Number(s?.value || 0.88).toFixed(2)}×`;
    runtimeBaseline = {
      child: 'browser',
      robot: 'disabled',
      wakeWord: w ? w.value : 'false',
      speechRate: s ? s.value : '0.88',
    };
    updateRuntimeDirty();
  }

  function updateRuntimeDirty() {
    const m = document.getElementById('ov-child-media');
    const r = document.getElementById('ov-robot-mode');
    const w = document.getElementById('ov-wake-word');
    const s = document.getElementById('ov-speech-rate');
    const sv = document.getElementById('ov-speech-rate-value');
    const btn = document.getElementById('btn-ov-apply-runtime');
    const hint = document.getElementById('ov-runtime-dirty');
    if (!m || !w || !s || !btn) return;
    if (sv) sv.textContent = `${Number(s.value).toFixed(2)}×`;
    const dirty = m.value !== runtimeBaseline.child || w.value !== runtimeBaseline.wakeWord || s.value !== runtimeBaseline.speechRate;
    btn.disabled = !dirty;
    if (hint) hint.textContent = dirty ? '有未应用的修改' : '';
  }

  function bindRuntimeDirty() {
    ['ov-child-media', 'ov-robot-mode', 'ov-wake-word', 'ov-speech-rate'].forEach((id) => {
      const el = document.getElementById(id);
      if (!el || el.dataset.boundRuntime) return;
      el.dataset.boundRuntime = '1';
      el.addEventListener('change', updateRuntimeDirty);
      if (id === 'ov-speech-rate') el.addEventListener('input', updateRuntimeDirty);
    });
  }

  async function loadPresets() {
    const sel = document.getElementById('ov-preset');
    if (!sel) return;
    try {
      const data = await fetchJson('/api/server/presets');
      const names = data.presetNames || [];
      sel.innerHTML = names.length
        ? names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join('')
        : '<option value="">无预设</option>';
    } catch (_) {
      sel.innerHTML = '<option value="">加载失败</option>';
    }
  }

  async function loadOverview() {
    const metrics = document.getElementById('algo-overview-metrics');
    const analyzersEl = document.getElementById('algo-overview-analyzers');
    const historyEl = document.getElementById('algo-overview-history');
    const modelsEl = document.getElementById('algo-overview-models');
    if (!metrics) return;

    const scopeEl = document.getElementById('ov-apply-scope');
    if (scopeEl) {
      try {
        scopeEl.value = localStorage.getItem(SCOPE_KEY) || 'new_sessions_only';
      } catch (_) {}
      scopeEl.addEventListener('change', () => persistApplyScope(scopeEl.value));
    }

    try {
      const [cfgRes, camRes, repRes, mediaRes, histRes, robotRes, statusRes, runtimeRes] = await Promise.all([
        fetchJson('/api/server/config'),
        fetchJson('/api/server/config/camera-analysis'),
        fetchJson('/api/server/config/report-scoring'),
        fetch('/api/server/child-media-mode').then((r) => r.json()),
        fetch('/api/server/config/history?limit=30').then((r) => r.json()),
        fetch('/api/server/robot/control-mode').then((r) => r.json()).catch(() => ({})),
        fetch('/api/server/status').then((r) => r.json()).catch(() => ({})),
        fetch('/api/server/runtime-modes').then((r) => r.json()).catch(() => ({})),
      ]);
      await loadPresets();

      const cfg = cfgRes.config || {};
      const globalMode = cfg.global?.mode || '—';
      const cam = camRes.config || {};
      const rep = repRes.config || {};
      const mediaMode = mediaRes.mode || mediaRes.data?.mode || mediaRes.childMediaMode || '—';
      const robotMode = 'disabled';
      fillRuntimeSelects(mediaMode, robotMode, runtimeRes.dialogueWakeWordEnabled === true, runtimeRes.browserSpeechRate);
      bindRuntimeDirty();

      metrics.innerHTML = `
        <div class="cc-card"><div class="cc-metric-label">全局分析器</div><div class="cc-metric-value" style="font-size:22px;">${esc(globalMode)}</div></div>
        <div class="cc-card"><div class="cc-metric-label">儿童 mediaMode</div><div class="cc-metric-value" style="font-size:22px;">${esc(mediaMode)}</div><div class="cc-metric-note">Demo 机械输出固定关闭</div></div>
        <div class="cc-card"><div class="cc-metric-label">摄像头采样</div><div class="cc-metric-value" style="font-size:22px;">${cam.enabled ? '开' : '关'}</div><div class="cc-metric-note">${cam.fps || '—'} fps · ${cam.width || '—'}×${cam.height || '—'}</div></div>
        <div class="cc-card"><div class="cc-metric-label">报告 schema</div><div class="cc-metric-value" style="font-size:14px;line-height:1.3;">${esc(rep.schema_version || '—')}</div></div>
      `;

      const az = cfg.analyzers || {};
      const mt = cfg.matchers || {};
      const rows = [];
      Object.keys(az).forEach((k) => {
        rows.push(`${k}: mode=${az[k]?.mode ?? '继承'} enabled=${az[k]?.enabled}`);
      });
      Object.keys(mt).forEach((k) => {
        rows.push(`matcher.${k}: mode=${mt[k]?.mode ?? '继承'} thr=${mt[k]?.threshold ?? '—'}`);
      });
      if (analyzersEl) analyzersEl.innerHTML = rows.map((r) => `<div>${esc(r)}</div>`).join('') || '无';

      const modelStatus = statusRes.modelStatus || [];
      if (modelsEl) {
        if (!modelStatus.length) {
          modelsEl.textContent = '未配置 model_path 或 status 未返回';
        } else {
          modelsEl.innerHTML = modelStatus
            .map((item) => {
              const ok = item.exists ? '存在' : '缺失';
              const cls = item.exists ? '' : ' style="color:var(--cc-danger)"';
              return `<div${cls}><b>${esc(item.analyzer || item.component || '—')}</b> · ${ok}<br/><span class="cc-tiny">${esc(item.model_path || '')}</span></div>`;
            })
            .join('');
        }
      }

      const hist = histRes.history || histRes.items || histRes.data || [];
      if (historyEl) {
        if (!Array.isArray(hist) || !hist.length) {
          historyEl.textContent = '暂无 analyzers 变更记录（进程内审计；重启后清空）';
        } else {
          const recent = hist.slice(-20).reverse();
          historyEl.innerHTML = recent
            .map((last) => {
              const paths = (last.changedPaths || []).slice(0, 6).join(', ') || '—';
              return `<div style="margin-bottom:6px;">${esc(last.timestamp || '')} · ${esc(last.action || '')} · ${esc(last.actor || '')} · 变更 ${last.changedCount ?? 0}（${esc(paths)}）</div>`;
            })
            .join('');
        }
      }
    } catch (e) {
      toast('概览加载失败', String(e.message || e), 'danger');
      if (analyzersEl) analyzersEl.textContent = String(e.message || e);
    }
  }

  async function applyRuntimeModes() {
    const child = document.getElementById('ov-child-media')?.value;
    const robot = 'disabled';
    const wakeWord = document.getElementById('ov-wake-word')?.value;
    const speechRate = document.getElementById('ov-speech-rate')?.value;
    if (!child || !wakeWord || !speechRate) return;
    if (
      child === runtimeBaseline.child &&
      robot === runtimeBaseline.robot &&
      wakeWord === runtimeBaseline.wakeWord &&
      speechRate === runtimeBaseline.speechRate
    ) {
      toast('无更改', '请先修改下拉选项');
      return;
    }
    const data = await fetchJson('/api/server/runtime-modes', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        childMediaMode: child,
        robotControlMode: robot,
        dialogueWakeWordEnabled: wakeWord === 'true',
        browserSpeechRate: Number(speechRate),
      }),
    });
    toast('已应用并保存', `机器人语速 ${Number(data.browserSpeechRate || speechRate).toFixed(2)}×，下一句话起生效`);
    await loadOverview();
  }

  async function applyPreset() {
    const presetName = document.getElementById('ov-preset')?.value;
    if (!presetName) {
      toast('请选择预设', '', 'danger');
      return;
    }
    if (!window.confirm(`应用预设 ${presetName} 到内存草稿？仍需保存 YAML 并发布。`)) return;
    const data = await fetchJson('/api/server/presets/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ presetName, actor: 'config_center' }),
    });
    toast('预设已应用', data.message || presetName);
    await loadOverview();
  }

  async function rollbackConfig() {
    if (!window.confirm('回滚到上一版 analyzers 内存快照？')) return;
    const data = await fetchJson('/api/server/config/rollback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actor: 'config_center' }),
    });
    toast('已回滚', `剩余快照 ${data.remainingSnapshots ?? 0}`);
    await loadOverview();
  }

  async function resetDefaults() {
    if (!window.confirm('恢复默认 analyzers 配置到内存？未保存修改将丢失。')) return;
    await fetchJson('/api/server/config/reset-defaults', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ applyEnvOverrides: false, actor: 'config_center' }),
    });
    toast('已恢复默认（内存）', '请保存 YAML 并发布');
    await loadOverview();
  }

  // ---------- Camera ----------
  function renderCameraForm(cfg) {
    const el = document.getElementById('cam-form');
    if (!el) return;
    el.innerHTML = [
      field('启用', boolSelect('cam-enabled', !!cfg.enabled)),
      field('fps', `<input class="cc-inp" type="number" id="cam-fps" value="${cfg.fps}" min="1" step="1" />`),
      field('width', `<input class="cc-inp" type="number" id="cam-width" value="${cfg.width}" min="1" />`),
      field('height', `<input class="cc-inp" type="number" id="cam-height" value="${cfg.height}" min="1" />`),
      field('prefer_browser_for_report', boolSelect('cam-pbr', !!cfg.prefer_browser_for_report), '生产勿开'),
      field(
        'prefer_browser_when_media_mode_browser',
        boolSelect('cam-pbr-browser', !!cfg.prefer_browser_when_media_mode_browser)
      ),
      field(
        'attention_incomplete_factor',
        `<input class="cc-inp" type="number" id="cam-aif" value="${cfg.attention_incomplete_factor}" min="0" max="1" step="0.05" />`
      ),
      field(
        'emotion_min_samples',
        `<input class="cc-inp" type="number" id="cam-ems" value="${cfg.emotion_min_samples}" min="1" />`
      ),
    ].join('');
    el.querySelectorAll('input,select').forEach((n) =>
      n.addEventListener('change', () => setDirty('cam', true))
    );
  }

  function readCameraForm() {
    return {
      enabled: document.getElementById('cam-enabled').value === 'true',
      fps: Number(document.getElementById('cam-fps').value),
      width: Number(document.getElementById('cam-width').value),
      height: Number(document.getElementById('cam-height').value),
      prefer_browser_for_report: document.getElementById('cam-pbr').value === 'true',
      prefer_browser_when_media_mode_browser:
        document.getElementById('cam-pbr-browser').value === 'true',
      attention_incomplete_factor: Number(document.getElementById('cam-aif').value),
      emotion_min_samples: Number(document.getElementById('cam-ems').value),
    };
  }

  function renderAttnForm(cfg) {
    const el = document.getElementById('attn-form');
    if (!el) return;
    const a = cfg.analyzers?.attention || {};
    const f = cfg.analyzers?.face || {};
    const p = cfg.analyzers?.pose || {};
    const mp = cfg.matchers?.pose || {};
    el.innerHTML = [
      field('global.mode', modeSelect('g-mode', cfg.global?.mode)),
      field('attention.enabled', boolSelect('a-en', a.enabled !== false)),
      field('attention.mode', modeSelect('a-mode', a.mode)),
      field(
        'attention.window_size',
        `<input class="cc-inp" type="number" id="a-ws" value="${a.window_size ?? 10}" />`
      ),
      field(
        'attention.pose_threshold',
        `<input class="cc-inp" type="number" id="a-pt" value="${a.pose_threshold ?? 20}" />`
      ),
      field('face.enabled', boolSelect('f-en', f.enabled !== false)),
      field('face.mode', modeSelect('f-mode', f.mode)),
      field(
        'face.confidence_threshold',
        `<input class="cc-inp" type="number" id="f-ct" value="${f.confidence_threshold ?? 0.6}" step="0.05" />`
      ),
      field('pose.enabled', boolSelect('p-en', p.enabled !== false)),
      field('pose.mode', modeSelect('p-mode', p.mode)),
      field('matchers.pose.enabled', boolSelect('mp-en', mp.enabled !== false)),
      field('matchers.pose.mode', modeSelect('mp-mode', mp.mode)),
      field(
        'matchers.pose.threshold',
        `<input class="cc-inp" type="number" id="mp-th" value="${mp.threshold ?? 0.70}" step="0.01" />`
      ),
    ].join('');
    el.querySelectorAll('input,select').forEach((n) =>
      n.addEventListener('change', () => setDirty('attn', true))
    );

    const adv = document.getElementById('attn-advanced-form');
    if (adv) {
      adv.innerHTML = [
        field(
          'attention.min_detection_confidence',
          `<input class="cc-inp" type="number" id="a-mdc" value="${a.min_detection_confidence ?? 0.5}" step="0.05" />`
        ),
        field(
          'attention.min_tracking_confidence',
          `<input class="cc-inp" type="number" id="a-mtc" value="${a.min_tracking_confidence ?? 0.5}" step="0.05" />`
        ),
        field(
          'face.model_path',
          `<input class="cc-inp" id="f-mp" value="${esc(f.model_path || '')}" />`
        ),
        field(
          'face.sample_rate',
          `<input class="cc-inp" type="number" id="f-sr" value="${f.sample_rate ?? 1}" step="1" />`
        ),
        field(
          'pose.model_path',
          `<input class="cc-inp" id="p-mp" value="${esc(p.model_path || '')}" />`
        ),
        field(
          'pose.sample_rate',
          `<input class="cc-inp" type="number" id="p-sr" value="${p.sample_rate ?? 1}" step="1" />`
        ),
        field(
          'pose.num_poses',
          `<input class="cc-inp" type="number" id="p-np" value="${p.num_poses ?? 1}" min="1" />`
        ),
        field(
          'pose.min_detection_confidence',
          `<input class="cc-inp" type="number" id="p-mdc" value="${p.min_detection_confidence ?? 0.5}" step="0.05" />`
        ),
      ].join('');
      adv.querySelectorAll('input,select').forEach((n) =>
        n.addEventListener('change', () => setDirty('attn', true))
      );
    }
  }

  function modeVal(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    const v = el.value;
    return v === '' ? null : v;
  }

  function numOr(id, fallback) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    const n = Number(el.value);
    return Number.isNaN(n) ? fallback : n;
  }

  function readAttnPatch() {
    return {
      global: { mode: modeVal('g-mode') || 'real' },
      analyzers: {
        attention: {
          enabled: document.getElementById('a-en').value === 'true',
          mode: modeVal('a-mode'),
          window_size: Number(document.getElementById('a-ws').value),
          pose_threshold: Number(document.getElementById('a-pt').value),
          min_detection_confidence: numOr('a-mdc', 0.5),
          min_tracking_confidence: numOr('a-mtc', 0.5),
        },
        face: {
          enabled: document.getElementById('f-en').value === 'true',
          mode: modeVal('f-mode'),
          confidence_threshold: Number(document.getElementById('f-ct').value),
          model_path: document.getElementById('f-mp')?.value,
          sample_rate: numOr('f-sr', 1),
        },
        pose: {
          enabled: document.getElementById('p-en').value === 'true',
          mode: modeVal('p-mode'),
          model_path: document.getElementById('p-mp')?.value,
          sample_rate: numOr('p-sr', 1),
          num_poses: numOr('p-np', 1),
          min_detection_confidence: numOr('p-mdc', 0.5),
        },
      },
      matchers: {
        pose: {
          enabled: document.getElementById('mp-en').value === 'true',
          mode: modeVal('mp-mode'),
          threshold: Number(document.getElementById('mp-th').value),
        },
      },
    };
  }

  async function updateCamMediaHint() {
    const el = document.getElementById('cam-media-hint');
    if (!el) return;
    try {
      const mediaRes = await fetch('/api/server/child-media-mode').then((r) => r.json());
      const mode = mediaRes.mode || '—';
      el.innerHTML = `当前儿童 mediaMode：<b>${esc(mode)}</b> · <a href="/server/config/overview">去概览修改</a>（不写盘）`;
    } catch (_) {
      el.textContent = '无法读取 mediaMode';
    }
  }

  async function loadCameraModule() {
    const [cam, cfg] = await Promise.all([
      fetchJson('/api/server/config/camera-analysis'),
      fetchJson('/api/server/config'),
    ]);
    cameraConfig = cam.config;
    analyzersConfig = cfg.config;
    renderCameraForm(cameraConfig);
    renderAttnForm(analyzersConfig);
    await updateCamMediaHint();
    setDirty('cam', false);
    setDirty('attn', false);
  }

  async function saveCameraDisk() {
    if (!window.confirm('将写入 camera_analysis.yaml（下次加载生效）。继续？')) return;
    const body = { config: readCameraForm() };
    const data = await fetchJson('/api/server/config/camera-analysis', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    cameraConfig = data.config;
    renderCameraForm(cameraConfig);
    setDirty('cam', false);
    toast('已写盘', data.message || 'camera_analysis');
  }

  async function analyzersUpdateMem(patch) {
    const data = await fetchJson('/api/server/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: patch, replace: false, actor: 'config_center' }),
    });
    analyzersConfig = data.config;
    return data;
  }

  async function analyzersSaveYaml() {
    return fetchJson('/api/server/config/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
  }

  async function analyzersApply() {
    const scope = getApplyScope();
    let force = false;
    try {
      const preview = await fetchJson('/api/server/config/apply-preview');
      const forceRequired =
        scope === 'active_sessions' && preview?.impact?.requiresForceForActiveReload;
      if (forceRequired) {
        const sessionCount = preview.impact.activeSessionCount ?? 0;
        if (
          !window.confirm(
            `作用域=运行中会话；当前有 ${sessionCount} 个活跃会话，重载可能导致分析状态重置。确定继续？`
          )
        ) {
          return null;
        }
        force = true;
      } else if (
        !window.confirm(`将应用 analyzers（scope=${scope}）。确认发布？`)
      ) {
        return null;
      }
    } catch (_) {
      if (!window.confirm(`将应用 analyzers（scope=${scope}）。确认发布？`)) return null;
    }
    return fetchJson('/api/server/config/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actor: 'config_center', scope, force }),
    });
  }

  // ---------- Speech ----------
  function renderSpeechForm(cfg) {
    const el = document.getElementById('speech-form');
    if (!el) return;
    const s = cfg.analyzers?.speech || {};
    const ms = cfg.matchers?.speech || {};
    el.innerHTML = [
      '<div class="cc-tiny">生产语音识别固定由儿童端浏览器提供；以下旧版本地分析参数只读保留。</div>',
      field('speech.enabled（固定关闭）', boolSelect('s-en', false)),
      field('speech.mode', modeSelect('s-mode', s.mode)),
      field('speech.language', `<input class="cc-inp" id="s-lang" value="${esc(s.language || 'zh')}" />`),
      field(
        'speech.accumulation_duration',
        `<input class="cc-inp" type="number" id="s-acc" value="${s.accumulation_duration ?? 2}" step="0.5" />`
      ),
      field('matchers.speech.enabled（固定关闭）', boolSelect('ms-en', false)),
      field('matchers.speech.mode', modeSelect('ms-mode', ms.mode)),
      field(
        'matchers.speech.threshold',
        `<input class="cc-inp" type="number" id="ms-th" value="${ms.threshold ?? 60}" />`
      ),
    ].join('');
    el.querySelectorAll('input,select').forEach((n) =>
      n.addEventListener('change', () => setDirty('speech', true))
    );
    el.querySelectorAll('input,select').forEach((n) => { n.disabled = true; });

    const adv = document.getElementById('speech-advanced-form');
    if (adv) {
      adv.innerHTML = [
        field('speech.device', `<input class="cc-inp" id="s-dev" value="${esc(s.device || '')}" />`),
        field(
          'speech.model_name',
          `<input class="cc-inp" id="s-mn" value="${esc(s.model_name || '')}" />`
        ),
        field(
          'speech.model_path',
          `<input class="cc-inp" id="s-mp" value="${esc(s.model_path || '')}" />`
        ),
        field(
          'speech.sample_rate',
          `<input class="cc-inp" type="number" id="s-sr" value="${s.sample_rate ?? 1}" />`
        ),
        field(
          'speech.sample_rate_audio',
          `<input class="cc-inp" type="number" id="s-sra" value="${s.sample_rate_audio ?? 16000}" />`
        ),
      ].join('');
      adv.querySelectorAll('input,select').forEach((n) =>
        n.addEventListener('change', () => setDirty('speech', true))
      );
      adv.querySelectorAll('input,select').forEach((n) => { n.disabled = true; });
    }
  }

  function readSpeechPatch() {
    return {
      analyzers: {
        speech: {
          enabled: false,
          mode: modeVal('s-mode'),
          language: document.getElementById('s-lang').value,
          accumulation_duration: Number(document.getElementById('s-acc').value),
          device: document.getElementById('s-dev')?.value,
          model_name: document.getElementById('s-mn')?.value,
          model_path: document.getElementById('s-mp')?.value,
          sample_rate: numOr('s-sr', 1),
          sample_rate_audio: numOr('s-sra', 16000),
        },
      },
      matchers: {
        speech: {
          enabled: false,
          mode: modeVal('ms-mode'),
          threshold: Number(document.getElementById('ms-th').value),
        },
      },
    };
  }

  async function loadSpeechModule() {
    const cfg = await fetchJson('/api/server/config');
    analyzersConfig = cfg.config;
    renderSpeechForm(analyzersConfig);
    setDirty('speech', false);
  }

  // ---------- Report ----------
  const WEIGHT_KEYS = [
    'attention',
    'matching',
    'ordering',
  ];

  function updateWeightSum() {
    const el = document.getElementById('report-weight-sum');
    if (!el) return;
    let sum = 0;
    WEIGHT_KEYS.forEach((k) => {
      const n = document.getElementById('w-' + k);
      if (n) sum += Number(n.value) || 0;
    });
    el.textContent = `和 = ${sum}`;
    el.className = 'cc-badge ' + (Math.abs(sum - 100) < 0.01 ? 'primary' : 'danger');
  }

  function renderReportForm(cfg) {
    const el = document.getElementById('report-form');
    const schemaLine = document.getElementById('report-schema-line');
    if (schemaLine) {
      schemaLine.textContent = `schema_version: ${cfg.schema_version || '—'}（只读） · narrative: ${
        cfg.narrative_provider || 'rule'
      }`;
    }
    if (!el) return;
    const w = cfg.weights || {};
    const ic = cfg.interactive_course || {};
    const minimums = cfg.sample_sufficiency?.minimum_effective_samples || {};
    const weightFields = WEIGHT_KEYS.map((k) =>
      field(
        `weights.${k}`,
        `<input class="cc-inp" type="number" id="w-${k}" value="${w[k] ?? 20}" step="1" />`
      )
    ).join('');
    el.innerHTML =
      field(
        '训练参考线（%）',
        `<input class="cc-inp" type="number" id="r-course-goal" min="0" max="100" value="${cfg.course_goal_score ?? 70}" step="1" />`
      ) +
      weightFields +
      field(
        'narrative_provider',
        `<select class="cc-inp" id="r-narr">
        <option value="rule"${cfg.narrative_provider !== 'mock' ? ' selected' : ''}>rule</option>
        <option value="mock"${cfg.narrative_provider === 'mock' ? ' selected' : ''}>mock</option>
      </select>`
      ) +
      field(
        'interactive accuracy_weight',
        `<input class="cc-inp" type="number" id="ic-acc" value="${ic.accuracy_weight ?? 0.75}" step="0.05" />`
      ) +
      field(
        'interactive response_weight',
        `<input class="cc-inp" type="number" id="ic-res" value="${ic.response_weight ?? 0.25}" step="0.05" />`
      ) +
      field(
        'interactive objective_weight',
        `<input class="cc-inp" type="number" id="ic-obj" value="${ic.objective_weight ?? 0.7}" step="0.05" />`
      ) +
      field(
        'interactive teacher_weight',
        `<input class="cc-inp" type="number" id="ic-tea" value="${ic.teacher_weight ?? 0.3}" step="0.05" />`
      ) +
      field(
        'ideal_response_sec',
        `<input class="cc-inp" type="number" id="ic-ideal" value="${ic.ideal_response_sec ?? 3}" step="0.5" />`
      ) +
      field(
        'slow_response_sec',
        `<input class="cc-inp" type="number" id="ic-slow" value="${ic.slow_response_sec ?? 12}" step="0.5" />`
      ) +
      field(
        '配对最低有效作答题数',
        `<input class="cc-inp" type="number" id="sample-pairing" min="1" max="100" value="${minimums.pairing ?? 5}" step="1" />`
      ) +
      field(
        '排序最低有效作答题数',
        `<input class="cc-inp" type="number" id="sample-ordering" min="1" max="100" value="${minimums.ordering ?? 5}" step="1" />`
      );
    el.querySelectorAll('input,select').forEach((n) => {
      n.addEventListener('input', () => {
        setDirty('report', true);
        updateWeightSum();
      });
      n.addEventListener('change', () => {
        setDirty('report', true);
        updateWeightSum();
      });
    });
    updateWeightSum();
  }

  function readReportPatch() {
    const weights = {};
    WEIGHT_KEYS.forEach((k) => {
      weights[k] = Number(document.getElementById('w-' + k).value);
    });
    return {
      course_goal_score: Number(document.getElementById('r-course-goal').value),
      weights,
      narrative_provider: document.getElementById('r-narr').value,
      interactive_course: {
        accuracy_weight: Number(document.getElementById('ic-acc').value),
        response_weight: Number(document.getElementById('ic-res').value),
        objective_weight: Number(document.getElementById('ic-obj').value),
        teacher_weight: Number(document.getElementById('ic-tea').value),
        ideal_response_sec: Number(document.getElementById('ic-ideal').value),
        slow_response_sec: Number(document.getElementById('ic-slow').value),
      },
      sample_sufficiency: {
        minimum_effective_samples: {
          pairing: Number(document.getElementById('sample-pairing').value),
          ordering: Number(document.getElementById('sample-ordering').value),
        },
      },
    };
  }

  async function loadReportModule() {
    const data = await fetchJson('/api/server/config/report-scoring');
    reportConfig = data.config;
    renderReportForm(reportConfig);
    setDirty('report', false);
  }

  async function saveReportDisk() {
    if (!window.confirm('将写入 report_scoring.yaml（仅新报告生效）。继续？')) return;
    const data = await fetchJson('/api/server/config/report-scoring', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: readReportPatch() }),
    });
    reportConfig = data.config;
    renderReportForm(reportConfig);
    setDirty('report', false);
    toast('已写盘', data.message || 'report_scoring');
  }

  // ---------- Bind ----------
  function bindActions() {
    document.getElementById('btn-ov-apply-runtime')?.addEventListener('click', async () => {
      try {
        await applyRuntimeModes();
      } catch (e) {
        toast('应用失败', String(e.message || e), 'danger');
      }
    });
    document.getElementById('btn-ov-preset')?.addEventListener('click', async () => {
      try {
        await applyPreset();
      } catch (e) {
        toast('预设失败', String(e.message || e), 'danger');
      }
    });
    document.getElementById('btn-ov-rollback')?.addEventListener('click', async () => {
      try {
        await rollbackConfig();
      } catch (e) {
        toast('回滚失败', String(e.message || e), 'danger');
      }
    });
    document.getElementById('btn-ov-reset')?.addEventListener('click', async () => {
      try {
        await resetDefaults();
      } catch (e) {
        toast('恢复默认失败', String(e.message || e), 'danger');
      }
    });

    document.getElementById('btn-cam-save')?.addEventListener('click', async () => {
      try {
        await saveCameraDisk();
      } catch (e) {
        toast('写盘失败', String(e.message || e), 'danger');
      }
    });
    document.getElementById('btn-cam-reload')?.addEventListener('click', () =>
      loadCameraModule().catch((e) => toast('加载失败', String(e.message || e), 'danger'))
    );
    document.getElementById('btn-attn-mem')?.addEventListener('click', async () => {
      try {
        await analyzersUpdateMem(readAttnPatch());
        setDirty('attn', false);
        toast('已更新内存', '请再保存 YAML 并发布');
      } catch (e) {
        toast('更新失败', String(e.message || e), 'danger');
      }
    });
    document.getElementById('btn-attn-save')?.addEventListener('click', async () => {
      try {
        await analyzersUpdateMem(readAttnPatch());
        await analyzersSaveYaml();
        setDirty('attn', false);
        toast('已保存 YAML', '');
      } catch (e) {
        toast('保存失败', String(e.message || e), 'danger');
      }
    });
    document.getElementById('btn-attn-apply')?.addEventListener('click', async () => {
      try {
        await analyzersUpdateMem(readAttnPatch());
        await analyzersSaveYaml();
        const r = await analyzersApply();
        if (!r) return;
        setDirty('attn', false);
        toast('已发布应用', r.message || 'analyzers');
      } catch (e) {
        toast('发布失败', String(e.message || e), 'danger');
      }
    });

    document.getElementById('btn-speech-mem')?.addEventListener('click', async () => {
      try {
        await analyzersUpdateMem(readSpeechPatch());
        setDirty('speech', false);
        toast('已更新内存', '');
      } catch (e) {
        toast('失败', String(e.message || e), 'danger');
      }
    });
    document.getElementById('btn-speech-save')?.addEventListener('click', async () => {
      try {
        await analyzersUpdateMem(readSpeechPatch());
        await analyzersSaveYaml();
        setDirty('speech', false);
        toast('已保存 YAML', '');
      } catch (e) {
        toast('失败', String(e.message || e), 'danger');
      }
    });
    document.getElementById('btn-speech-apply')?.addEventListener('click', async () => {
      try {
        await analyzersUpdateMem(readSpeechPatch());
        await analyzersSaveYaml();
        const r = await analyzersApply();
        if (!r) return;
        setDirty('speech', false);
        toast('已发布应用', r.message || 'speech');
      } catch (e) {
        toast('失败', String(e.message || e), 'danger');
      }
    });

    document.getElementById('btn-report-save')?.addEventListener('click', async () => {
      try {
        await saveReportDisk();
      } catch (e) {
        toast('写盘失败', String(e.message || e), 'danger');
      }
    });
    document.getElementById('btn-report-reload')?.addEventListener('click', () =>
      loadReportModule().catch((e) => toast('加载失败', String(e.message || e), 'danger'))
    );

    window.addEventListener('beforeunload', (e) => {
      if (Object.values(dirty).some(Boolean)) {
        e.preventDefault();
        e.returnValue = '';
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    bindActions();
    const m = moduleName();
    if (m === 'overview') loadOverview();
    if (m === 'camera') loadCameraModule().catch((e) => toast('加载失败', String(e.message || e), 'danger'));
    if (m === 'speech') loadSpeechModule().catch((e) => toast('加载失败', String(e.message || e), 'danger'));
    if (m === 'report') loadReportModule().catch((e) => toast('加载失败', String(e.message || e), 'danger'));
  });
})();
