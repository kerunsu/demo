/**
 * 行为绑定的表情主时间轴编辑器。
 * 映射仍写 course_map.json；本文件只管理 sequence 字段，保持旧映射可用。
 */
(function () {
  const DEFAULT_SEQUENCE = () => ({
    expressionMediaId: '',
    expressionDurationMs: 0,
    motionOffsetMs: 0,
    audio: { offsetMs: 0 },
  });

  function asMs(value) {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
  }

  function normalize(raw) {
    // 保持对 mappingData 内原对象的引用，保存动作时不会丢掉尚未点击保存的微调。
    const source = raw && typeof raw === 'object' ? raw : {};
    const audio = source.audio && typeof source.audio === 'object' ? source.audio : {};
    source.expressionMediaId = String(source.expressionMediaId || '');
    source.expressionDurationMs = asMs(source.expressionDurationMs);
    source.motionOffsetMs = asMs(source.motionOffsetMs);
    source.audio = {
      offsetMs: asMs(audio.offsetMs),
    };
    return source;
  }

  function sequenceFor(config, auxType) {
    config.__sequence = config.__sequence || {};
    config.__sequence[auxType] = normalize(config.__sequence[auxType]);
    return config.__sequence[auxType];
  }

  function field(label, input) {
    const wrap = document.createElement('label');
    wrap.className = 'behavior-sequence-field';
    const text = document.createElement('span');
    text.textContent = label;
    wrap.append(text, input);
    return wrap;
  }

  function numberInput(value, help) {
    const input = document.createElement('input');
    input.type = 'number';
    input.min = '0';
    input.step = '10';
    input.value = String(value || 0);
    input.title = help;
    return input;
  }

  function pathInput(value) {
    const input = document.createElement('input');
    input.type = 'text';
    input.readOnly = true;
    input.value = value || '';
    input.placeholder = '未指定：使用上方表情选择';
    return input;
  }

  function chooseMedia(root, onPick) {
    if (typeof window.openMediaPicker !== 'function') {
      window.alert('媒资选择器尚未加载');
      return;
    }
    window.openMediaPicker({ root }, onPick);
  }

  const TERMINAL_PHASES = new Set(['completed', 'degraded', 'failed', 'cancelled']);

  function testStatusMessage(status) {
    const components = status?.components || {};
    const componentText = Object.entries(components)
      .filter(([, item]) => item && item.required)
      .map(([name, item]) => `${name}=${item.status || 'unknown'}`)
      .join(' · ');
    return [
      status?.message || status?.phase || '状态未知',
      componentText,
      status?.error ? `错误：${status.error}` : '',
    ].filter(Boolean).join('；');
  }

  function renderTestStatus(status, fallbackTitle = '') {
    const panel = document.getElementById('behavior-test-status');
    if (!panel) return;
    const phase = status?.phase || 'unknown';
    const commandId = status?.commandId || status?.behaviorId || '';
    const actual = [status?.motion, status?.emotion].filter(Boolean).join(' + ') || '无输出';
    panel.dataset.state = phase;
    panel.className = `cc-notice ${phase === 'failed' ? 'danger' : phase === 'degraded' ? 'warning' : phase === 'completed' ? 'success' : 'info'}`;
    panel.innerHTML = '';
    const title = document.createElement('strong');
    title.textContent = fallbackTitle || `测试状态：${phase}`;
    const detail = document.createElement('div');
    detail.className = 'cc-tiny';
    detail.textContent = `${commandId ? `命令 ${commandId} · ` : ''}${testStatusMessage(status)} · 实际计划：${actual}`;
    panel.append(title, detail);
  }

  function readablePreviewError(data, httpStatus) {
    const targets = Array.isArray(data?.missingTargets)
      ? data.missingTargets.map((item) => item.detail || item.code).filter(Boolean)
      : [];
    return targets.join('；') || data?.message || data?.detail || data?.error || `HTTP ${httpStatus}`;
  }

  async function refreshBehaviorControlStatus() {
    const panel = document.getElementById('behavior-test-status');
    if (!panel || ['submitting', 'queued', 'running'].includes(panel.dataset.state)) return;
    try {
      const res = await fetch('/api/robot/control/status', { cache: 'no-store' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) throw new Error(readablePreviewError(data, res.status));
      const control = data.control || {};
      const targets = control.targets || {};
      panel.dataset.state = 'ready-check';
      panel.className = `cc-notice ${targets.motionReady && targets.robotDisplayOnline ? 'success' : 'warning'}`;
      panel.innerHTML = '';
      const title = document.createElement('strong');
      title.textContent = targets.motionReady && targets.robotDisplayOnline
        ? '测试目标已就绪'
        : '测试目标尚未就绪';
      const detail = document.createElement('div');
      detail.className = 'cc-tiny';
      detail.textContent = `模式=${control.controlMode || '未知'} · 动作=${targets.motionDetail || '未知'} · 表情页=${targets.robotDisplayOnline ? '在线' : '离线（请打开 /robot/emotion）'} · 控制页=${targets.robotControlOnline ? '在线' : '离线'}`;
      panel.append(title, detail);
    } catch (error) {
      renderTestStatus({
        phase: 'failed',
        message: `无法读取控制状态：${error?.message || error}`,
      }, '控制状态不可用');
    }
  }

  async function pollCommandStatus(statusUrl, commandId, timeoutMs) {
    const deadline = Date.now() + Math.max(5000, timeoutMs || 15000);
    while (Date.now() < deadline) {
      const res = await fetch(statusUrl, { cache: 'no-store' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success || !data.status) {
        throw new Error(readablePreviewError(data, res.status));
      }
      renderTestStatus(data.status);
      if (TERMINAL_PHASES.has(data.status.phase)) return data.status;
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
    throw new Error(`命令 ${commandId} 状态等待超时；请在实时监控查看最后状态`);
  }

  function renderOne(config, auxType) {
    const slot = document.getElementById(`slot-${auxType}`)?.closest('.action-slot');
    if (!slot) return;
    slot.querySelector('.behavior-sequence-controls')?.remove();
    const seq = sequenceFor(config, auxType);
    const panel = document.createElement('div');
    panel.className = 'behavior-sequence-controls';

    const title = document.createElement('div');
    title.className = 'behavior-sequence-title';
    title.textContent = '表情主时间轴';
    panel.appendChild(title);

    const grid = document.createElement('div');
    grid.className = 'behavior-sequence-grid';
    const duration = numberInput(seq.expressionDurationMs, '表情从开始到回到 idle 的总时长');
    duration.addEventListener('input', () => { seq.expressionDurationMs = asMs(duration.value); });
    const motionOffset = numberInput(seq.motionOffsetMs, '动作从表情开始后多久启动');
    motionOffset.addEventListener('input', () => { seq.motionOffsetMs = asMs(motionOffset.value); });
    const audioOffset = numberInput(seq.audio.offsetMs, '语音从表情开始后多久启动');
    audioOffset.addEventListener('input', () => { seq.audio.offsetMs = asMs(audioOffset.value); });
    grid.append(
      field('表情总时长（毫秒）', duration),
      field('动作开始偏移（毫秒）', motionOffset),
      field('语音开始偏移（毫秒）', audioOffset),
    );
    panel.appendChild(grid);

    const paths = document.createElement('div');
    paths.className = 'behavior-sequence-paths';
    const expressionPath = pathInput(seq.expressionMediaId);
    const pickExpression = document.createElement('button');
    pickExpression.type = 'button';
    pickExpression.className = 'btn-test-small';
    pickExpression.textContent = '选表情媒体';
    pickExpression.addEventListener('click', () => chooseMedia('Emotions', (path) => {
      seq.expressionMediaId = path;
      expressionPath.value = path;
    }));
    paths.append(field('表情媒体（可覆盖上方表情）', expressionPath), pickExpression);
    panel.appendChild(paths);

    const hint = document.createElement('p');
    hint.className = 'behavior-sequence-hint';
    hint.textContent = '语音内容仍由当前课程/课点决定，这里只调整它在表情开始后的播放时间。下一行为会等待本序列结束。';
    panel.appendChild(hint);
    slot.appendChild(panel);
  }

  window.renderSequenceControls = (config) => {
    (window.ALL_AUX_TYPES || []).forEach((auxType) => renderOne(config, auxType));
    refreshBehaviorControlStatus();
  };
  window.refreshBehaviorControlStatus = refreshBehaviorControlStatus;

  window.applyImportedTimingDefaults = (config, auxType, motionName) => {
    const metadata = (window.motionMetadata || {})[motionName] || {};
    const imported = metadata.expression || {};
    const seq = sequenceFor(config, auxType);
    if (!seq.expressionMediaId && imported.mediaId) seq.expressionMediaId = imported.mediaId;
    if (!seq.expressionDurationMs && imported.durationMs) seq.expressionDurationMs = asMs(imported.durationMs);
    if (!seq.motionOffsetMs && metadata.motionStartTime) seq.motionOffsetMs = asMs(metadata.motionStartTime);
    window.renderSequenceControls(config);
  };

  window.testBehaviorSequence = async (auxType, config, triggerButton = null) => {
    const motions = auxType === 'idle'
      ? (config.idle ? [config.idle] : [])
      : (config[auxType] || []);
    const emotion = (window.currentEmotions || {})[auxType] || '';
    const sequence = sequenceFor(config, auxType);
    if (!motions.length && !emotion && !sequence.expressionMediaId) {
      window.alert('请至少配置一个动作或表情');
      return;
    }
    const originalText = triggerButton?.textContent || '';
    if (triggerButton) {
      triggerButton.disabled = true;
      triggerButton.textContent = '提交中…';
    }
    renderTestStatus({ phase: 'submitting', message: '正在检查执行目标并提交当前绑定' });
    try {
      const res = await fetch('/api/robot/sequence/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          motions,
          emotion,
          sequence,
          auxType,
          courseId: window.currentScope?.courseId || null,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        throw new Error(readablePreviewError(data, res.status));
      }
      const queued = {
        phase: data.phase || 'queued',
        commandId: data.sequenceId,
        motion: data.actualPlan?.motion,
        emotion: data.actualPlan?.emotion,
        message: '命令已接收，等待实际执行',
        components: {},
      };
      renderTestStatus(queued);
      if (window.ccToast) {
        window.ccToast('测试命令已接收', `正在跟踪 ${data.sequenceId}`, 'warning');
      } else {
        console.info(`测试命令已接收：${data.sequenceId}`);
      }
      if (triggerButton) triggerButton.textContent = '执行中…';
      const terminal = await pollCommandStatus(
        data.statusUrl,
        data.sequenceId,
        Math.min(90000, Number(data.durationMs || 0) + 15000),
      );
      const terminalText = testStatusMessage(terminal);
      if (window.ccToast) {
        window.ccToast(
          terminal.phase === 'completed' ? '测试完成' : '测试有异常',
          terminalText,
          terminal.phase === 'completed' ? 'success' : 'warning',
        );
      }
    } catch (error) {
      const message = error?.message || String(error);
      renderTestStatus({ phase: 'failed', message, error: message }, '测试失败');
      if (window.ccToast) window.ccToast('测试失败', message, 'danger');
      else window.alert(`测试失败：${message}`);
    } finally {
      if (triggerButton) {
        triggerButton.disabled = false;
        triggerButton.textContent = originalText || '▶ 测试';
      }
    }
  };
})();
