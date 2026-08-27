(function () {
  if (document.body?.dataset?.module !== 'latency') return;

  const sourceLabels = {
    network: '网络链路',
    server: 'Server 内部',
    sync: '同步预留',
    endpoint: '终端准备',
    insufficient_data: '数据不足',
  };
  let refreshTimer = null;
  let selectedSession = null;

  const byId = (id) => document.getElementById(id);
  const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
  const ms = (value) => Number.isFinite(Number(value)) ? `${Math.round(Number(value))}ms` : '—';

  async function fetchJson(url) {
    const response = await fetch(url, { credentials: 'same-origin' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.success === false) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function renderSummary(report) {
    const summary = report.summary || {};
    byId('latency-network').textContent = ms(summary.network?.p95Ms);
    byId('latency-server').textContent = ms(summary.serverDispatch?.p95Ms);
    byId('latency-sync').textContent = ms(summary.plannedSyncLead?.p50Ms);
    byId('latency-source').textContent = sourceLabels[summary.primarySource] || summary.primarySource || '—';
    byId('latency-sample-count').textContent = `${summary.interactionCount || 0} 个交互样本`;
    byId('latency-updated-at').textContent = report.generatedAt
      ? `报告生成：${new Date(report.generatedAt).toLocaleString()}`
      : '尚未生成';
  }

  function renderDataQuality(report) {
    const root = byId('latency-quality');
    const quality = report.dataQuality || {};
    const recovered = Number(quality.recoveredLegacyRows || 0);
    const noData = Number(quality.rowCount || 0) === 0;
    const tone = !quality.isolated ? 'bad' : recovered || noData ? 'warning' : 'good';
    root.className = `latency-quality visible ${tone}`;
    if (!quality.isolated) {
      root.textContent = `日志不可信：检测到 ${quality.observedMediaSessionIds?.length || 0} 个媒体会话混在同一报告中。`;
    } else if (recovered) {
      root.textContent = `日志已隔离：当前会话共 ${quality.rowCount || 0} 条事件，其中 ${recovered} 条从旧版错位目录按录制 ID 安全恢复。`;
    } else if (noData) {
      root.textContent = '当前录制轮次没有可用的独立审计事件；它可能来自修复前且未留下可确认的录制 ID。请完成一轮新测试。';
    } else {
      root.textContent = `日志隔离正常：仅统计媒体会话 ${report.mediaSessionId || '当前最新会话'}，共 ${quality.rowCount || 0} 条事件。`;
    }
  }

  function renderModalities(report) {
    const root = byId('latency-modality-grid');
    const entries = Object.entries(report.modalities || {})
      .filter(([key]) => key === 'display' || key === 'audio');
    root.innerHTML = entries.map(([key, item]) => {
      const p95 = Number(item.p95Ms || 0);
      const width = Math.min(100, Math.max(2, p95 / 20));
      const displayStages = key === 'display' && item.endpointStages
        ? `<div class="cc-tiny">预检 ${ms(item.endpointStages.preflightMs?.p50Ms)} · 加载 ${ms(item.endpointStages.preloadMs?.p50Ms)} · 淡入 ${ms(item.endpointStages.crossfadeMs?.p50Ms)}</div>`
        : '';
      return `<article class="latency-modality-card" data-modality="${esc(key)}">
        <div class="latency-modality-head"><strong>${esc(item.label)}</strong><span>${item.samples || 0} 样本</span></div>
        <div class="latency-modality-value">P50 ${ms(item.p50Ms)} · P95 ${ms(item.p95Ms)}</div>
        <div class="latency-bar"><i style="width:${width}%"></i></div>
        <div class="cc-tiny">最大 ${ms(item.maxMs)}</div>
        ${displayStages}
      </article>`;
    }).join('');
  }

  function renderFocusRail(report) {
    const candidates = [];
    (report.interactions || []).forEach((interaction) => {
      Object.entries(interaction.modalities || {})
        .filter(([modality]) => modality === 'display' || modality === 'audio')
        .forEach(([modality, detail]) => {
        if (Number.isFinite(Number(detail.startObservedMs))) {
          candidates.push({ interaction, modality, detail });
        }
      });
    });
    candidates.sort((a, b) => Number(b.detail.startObservedMs) - Number(a.detail.startObservedMs));
    const slowest = candidates[0];
    const rail = byId('latency-focus-rail');
    const legend = byId('latency-focus-legend');
    if (!slowest) {
      byId('latency-focus-caption').textContent = '当前会话没有可关联的真实启动回执。';
      byId('latency-focus-total').textContent = '—';
      rail.innerHTML = '';
      legend.innerHTML = '';
      return;
    }
    const contributors = (slowest.detail.contributors || []).filter((item) => Number(item.ms) > 0);
    const sum = Math.max(1, contributors.reduce((total, item) => total + Number(item.ms), 0));
    rail.innerHTML = contributors.map((item) => {
      const width = Math.max(3, Number(item.ms) / sum * 100);
      return `<div class="latency-rail-segment ${esc(item.source)}" style="width:${width}%" title="${esc(item.label)} ${ms(item.ms)}">${width >= 12 ? ms(item.ms) : ''}</div>`;
    }).join('');
    const colors = { network: '#55a6d9', server: '#7657c8', sync: '#315efb', endpoint: '#d89019' };
    legend.innerHTML = contributors.map((item) => `<span style="--rail-color:${colors[item.source] || '#98a2b3'}">${esc(item.label)} ${ms(item.ms)}</span>`).join('');
    byId('latency-focus-caption').textContent = `${slowest.interaction.intent || '交互'} · ${(report.modalities?.[slowest.modality]?.label || slowest.modality)} · ${slowest.interaction.requestId || ''}`;
    byId('latency-focus-total').textContent = ms(slowest.detail.startObservedMs);
  }

  function renderDialogue(report) {
    const dialogue = report.dialogue || {};
    const metrics = dialogue.metrics || {};
    const stages = [
      ['vadSilenceTailMs', '停声截句'],
      ['audioEncodingMs', '音频编码'],
      ['sttMs', '旧版本地识别'],
      ['replyGenerationMs', '回复生成'],
      ['clientTtsStartupMs', '浏览器开口'],
    ];
    byId('dialogue-round-count').textContent = `${dialogue.roundCount || 0} 轮`;
    byId('dialogue-stage-grid').innerHTML = stages.map(([key, label]) => {
      const item = metrics[key] || {};
      const detail = key === 'sttMs'
        ? `<span>本机 ${ms(metrics.sttLocalAttemptMs?.p50Ms)} · 回退 ${ms(metrics.sttRemoteFallbackMs?.p50Ms)}</span>`
        : '';
      return `<article class="dialogue-stage"><span>${esc(label)} · P50</span><strong>${ms(item.p50Ms)}</strong><span>${item.samples || 0} 个样本 · P95 ${ms(item.p95Ms)}</span>${detail}</article>`;
    }).join('');
    const body = byId('dialogue-latency-body');
    const rounds = dialogue.rounds || [];
    body.innerHTML = rounds.length ? rounds.slice(0, 50).map((item) => {
      const m = item.metrics || {};
      const observed = item.observedAt ? new Date(item.observedAt).toLocaleTimeString() : '—';
      return `<tr><td><b>${esc(item.outcome)}</b><small>${esc(observed)} · ${esc(item.provider || '未知 provider')}</small></td><td>${ms(m.vadSilenceTailMs)}</td><td>${ms(m.audioEncodingMs)}</td><td>${ms(m.sttMs)}<small>转换 ${ms(m.sttConvertMs)} · 本机 ${ms(m.sttLocalAttemptMs)} · 回退 ${ms(m.sttRemoteFallbackMs)}</small></td><td>${ms(m.replyGenerationMs)}</td><td>${ms(m.serverToDecisionMs)}</td><td>${ms(m.clientTtsStartupMs)}<small>端到端 ${ms(m.ttsStartObservedMs)}</small></td></tr>`;
    }).join('') : '<tr><td colspan="7">当前日志还没有带分段时间的自然对话；更新儿童端后完成一轮对话即可显示。</td></tr>';
  }

  function findingHtml(item) {
    const severity = item.severity || 'info';
    return `<div class="latency-finding ${esc(severity)}"><b>${esc(item.title)}</b><p>${esc(item.detail)}</p></div>`;
  }

  function renderFindings(report) {
    byId('latency-findings').innerHTML = (report.findings || []).map(findingHtml).join('') || '<p class="cc-tiny">暂无自动判断。</p>';
    byId('latency-notes').innerHTML = (report.measurementNotes || []).map((item) => `<li>${esc(item)}</li>`).join('');
  }

  function modalityCell(item, name) {
    const detail = item.modalities?.[name];
    if (!detail) return '<td class="muted">未配置/未上报</td>';
    const source = detail.dominantSource?.source;
    let note = sourceLabels[source] || source || '';
    if (detail.measurementQuality === 'dispatch_proxy') note = `${note} · 下发代理，非实际起动`;
    if (name === 'display' && detail.endpointStages) {
      const stage = detail.endpointStages;
      note = `预检 ${ms(stage.preflightMs)} · 加载 ${ms(stage.preloadMs)} · 淡入 ${ms(stage.crossfadeMs)}`;
    }
    return `<td><b>${ms(detail.startObservedMs)}</b><small>${esc(note)}</small></td>`;
  }

  function renderInteractions(report) {
    const body = byId('latency-interaction-body');
    const rows = report.interactions || [];
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="7">暂无可关联样本。开始课程并触发提问、提示或表扬后刷新。</td></tr>';
      return;
    }
    body.innerHTML = rows.slice(0, 50).map((item) => {
      const observed = item.observedAt ? new Date(item.observedAt).toLocaleTimeString() : '—';
      return `<tr>
        <td><b>${esc(item.intent)}</b><small>${esc(observed)}</small></td>
        <td>${ms(item.metrics?.teacherNetworkRttMs)}</td>
        <td>${ms(item.metrics?.serverDispatchMs)}</td>
        <td>${ms(item.metrics?.plannedSyncLeadMs)}</td>
        ${modalityCell(item, 'display')}
        ${modalityCell(item, 'audio')}
        <td><span class="cc-badge gray">${esc(sourceLabels[item.primarySource] || item.primarySource)}</span></td>
      </tr>`;
    }).join('');
  }

  function renderVoiceStrategy(report) {
    const voice = report.voiceStrategy || {};
    byId('voice-strategy-summary').textContent = voice.summary || '';
    byId('voice-scenario-grid').innerHTML = (voice.scenarios || []).map((item) => `
      <article class="voice-scenario ${esc(item.status)}">
        <div><strong>${esc(item.name)}</strong><span>${esc(item.status)}</span></div>
        <p>${esc(item.expected)}</p><small>${esc(item.evidence)}</small>
      </article>`).join('');
    byId('voice-strategy-findings').innerHTML = (voice.findings || []).map(findingHtml).join('');
  }

  async function loadReport() {
    const option = byId('latency-session-select').selectedOptions[0];
    const trainingId = option?.dataset?.trainingId || '';
    const mediaSessionId = option?.value || '';
    if (!trainingId) return;
    selectedSession = { trainingId, mediaSessionId };
    const query = mediaSessionId ? `?mediaSessionId=${encodeURIComponent(mediaSessionId)}` : '';
    const report = await fetchJson(`/api/v2/timeline/${encodeURIComponent(trainingId)}/latency${query}`);
    renderSummary(report);
    renderDataQuality(report);
    renderModalities(report);
    renderFocusRail(report);
    renderFindings(report);
    renderInteractions(report);
    renderDialogue(report);
    renderVoiceStrategy(report);
    const mediaParam = mediaSessionId ? `&mediaSessionId=${encodeURIComponent(mediaSessionId)}` : '';
    byId('latency-export-md').href = `/api/v2/timeline/${encodeURIComponent(trainingId)}/latency?format=markdown${mediaParam}`;
    byId('latency-export-csv').href = `/api/v2/timeline/${encodeURIComponent(trainingId)}?format=csv${mediaParam}`;
  }

  async function loadSessions() {
    const select = byId('latency-session-select');
    const previous = select.value;
    const data = await fetchJson('/api/v2/timeline/latency/sessions?limit=200');
    const sessions = data.sessions || [];
    select.innerHTML = sessions.length
      ? sessions.map((item) => {
          const active = item.liveActive ? ' · 进行中' : '';
          const time = item.recordingStartedAt ? new Date(item.recordingStartedAt).toLocaleString() : '时间未知';
          return `<option value="${esc(item.mediaSessionId || '')}" data-training-id="${esc(item.trainingSessionId)}">${esc(item.studentName)} · ${esc(item.folderName || '')} · ${esc(time)}${active}</option>`;
        }).join('')
      : '<option value="">暂无含训练 ID 的录制</option>';
    if (previous && sessions.some((item) => item.mediaSessionId === previous)) select.value = previous;
    await loadReport();
  }

  async function refresh() {
    const button = byId('latency-refresh');
    button.disabled = true;
    try {
      await loadSessions();
    } catch (error) {
      byId('latency-findings').innerHTML = findingHtml({ severity: 'warning', title: '加载失败', detail: error.message || String(error) });
    } finally {
      button.disabled = false;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    byId('latency-refresh').addEventListener('click', refresh);
    byId('latency-session-select').addEventListener('change', () => loadReport().catch(console.error));
    byId('latency-auto-refresh').addEventListener('change', (event) => {
      if (refreshTimer) clearInterval(refreshTimer);
      refreshTimer = event.target.checked ? setInterval(() => loadReport().catch(() => {}), 5000) : null;
    });
    refresh();
  });
})();
