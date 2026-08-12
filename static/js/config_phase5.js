/* 配置中心 · 设备与录制。前端只消费稳定 API，不读取 DB、绝对路径或硬件。 */
(function () {
  const api = {
    async request(path, options) {
      const response = await fetch(path, options || {});
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || body.error || `HTTP ${response.status}`);
      return body;
    },
    json(path, method, value) {
      return this.request(path, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(value || {}),
      });
    },
  };
  window.phase5Api = api;

  const byId = (id) => document.getElementById(id);
  const text = (id, value) => { const node = byId(id); if (node) node.textContent = value; };
  const html = (id, value) => { const node = byId(id); if (node) node.innerHTML = value; };
  const escapeHtml = (value) => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const pretty = (value) => JSON.stringify(value, null, 2);
  let stagingId = null;

  function formatBytes(value) {
    let size = Number(value || 0);
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let index = 0;
    while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
    return `${size.toFixed(index ? 1 : 0)} ${units[index]}`;
  }

  function statusLabel(device) {
    if (!device.enabled) return ['已停用', 'gray'];
    if (device.captureReady) return ['已连接', 'primary'];
    if (device.connectionStatus === 'connected_not_capture_enabled') return ['已连接，未接入多轨录制', 'gray'];
    if (device.connectionStatus === 'check_failed') return ['设备检查失败', 'gray'];
    if (device.connectionStatus === 'runtime_online_unprobed') return ['Runtime 在线，待设备自检', 'gray'];
    if (device.connectionStatus === 'runtime_offline') return ['Runtime 未连接', 'gray'];
    return ['尚未验证', 'gray'];
  }

  function deviceCard(device, configurable) {
    const [label, badge] = statusLabel(device);
    const kind = device.kind === 'video' ? '摄像头' : '麦克风';
    const required = device.required ? '必需' : '可选';
    const actions = configurable ? `
      <div class="cc-form-row" style="margin-top:7px;">
        <button class="cc-btn soft small" data-device-toggle="${escapeHtml(device.deviceId)}" data-enabled="${device.enabled ? '1' : '0'}">${device.enabled ? '停用' : '启用'}</button>
        <button class="cc-btn soft small" data-device-required="${escapeHtml(device.deviceId)}" data-required="${device.required ? '1' : '0'}">设为${device.required ? '可选' : '必需'}</button>
        <button class="cc-btn danger small" data-device-delete="${escapeHtml(device.deviceId)}">移除</button>
      </div>` : '';
    return `<div style="border:1px solid #e2e7f0;border-radius:10px;padding:10px;margin:8px 0;">
      <div><b>${escapeHtml(kind)} · ${escapeHtml(device.deviceId)}</b>
        <span class="cc-badge ${badge}">${label}</span>
        <span class="cc-badge gray">${required}</span>
      </div>
      <div class="cc-tiny">轨道 ${escapeHtml(device.trackId)} · ${escapeHtml(device.role)}${device.filename ? ` · ${escapeHtml(device.filename)}` : ''}</div>
      ${device.operatorHint ? `<div class="cc-tiny">${escapeHtml(device.operatorHint)}</div>` : ''}
      ${actions}
    </div>`;
  }

  function renderDevices(devices) {
    html('phase5-default-device-list', `
      <div class="cc-tiny"><b>默认设备（无需添加）</b></div>
      ${(devices.defaults || []).map((item) => deviceCard(item, false)).join('')}`);
    html('phase5-device-list', `
      <div class="cc-tiny"><b>额外环境设备</b></div>
      ${(devices.configured || []).map((item) => deviceCard(item, true)).join('') || '<div class="cc-tiny">当前没有额外环境设备。</div>'}`);
    text('phase5-required-status', devices.allRequiredReady ? '全部通过' : '未全部通过');
  }

  function sessionDetails(session) {
    const files = (session.files || []).map((file) =>
      `<li><code>${escapeHtml(file.filename)}</code> · ${formatBytes(file.sizeBytes)}</li>`
    ).join('') || '<li>尚无已保存文件</li>';
    const tracks = (session.tracks || []).map((track) =>
      `<li>${escapeHtml(track.trackId || '未标识轨道')} · ${escapeHtml(track.deviceId || track.role || '')} · <code>${escapeHtml(track.filename || '')}</code></li>`
    ).join('');
    const reasons = (session.degradationReasons || []).map(escapeHtml).join('；');
    const locked = !!session.locked;
    return `<details style="border-top:1px solid #edf0f5;padding:9px 0;">
      <summary><b>${escapeHtml(session.folderName)}</b> · ${escapeHtml(session.status)} · ${formatBytes(session.totalBytes)}
        ${locked ? '<span class="cc-badge warn">已上锁</span>' : ''}
      </summary>
      <div class="cc-tiny">开始：${escapeHtml(session.recordingStartedAt || '未知')} · 时长：${session.durationSec == null ? '未知' : `${session.durationSec}s`} · 时间轴 ${session.timelineRows || 0} 行</div>
      ${reasons ? `<div class="cc-notice warning">降级/异常：${reasons}</div>` : ''}
      ${tracks ? `<div class="cc-tiny"><b>轨道</b><ul>${tracks}</ul></div>` : ''}
      <div class="cc-tiny"><b>文件</b><ul>${files}</ul></div>
      <div class="cc-form-row" style="margin-top:7px;">
        <button type="button" class="cc-btn soft small" data-reveal-folder="${escapeHtml(session.folderName)}">在服务器本机打开文件夹</button>
        <button type="button" class="cc-btn small ${locked ? 'soft' : 'danger'}" data-lock-folder="${escapeHtml(session.folderName)}" data-locked="${locked ? '1' : '0'}">${locked ? '解锁' : '上锁'}</button>
        <button type="button" class="cc-btn danger small" data-delete-folder="${escapeHtml(session.folderName)}" ${locked ? 'disabled title="已上锁，请先解锁再删除"' : ''}>删除</button>
      </div>
    </details>`;
  }

  function renderRecordings(recordings) {
    text('phase5-session-count', recordings.storage?.sessionCount ?? 0);
    text('phase5-storage-size', formatBytes(recordings.storage?.totalBytes));
    const groups = recordings.children || [];
    html('phase5-recording-groups', groups.map((group) => {
      const student = group.student || {};
      const detail = [student.age != null ? `${student.age} 岁` : '', student.teacher ? `教师：${student.teacher}` : ''].filter(Boolean).join(' · ');
      return `<section style="border:1px solid #dfe5ef;border-radius:12px;padding:12px;margin:10px 0;">
        <div><b>${escapeHtml(student.name || '未关联儿童')}</b> <span class="cc-badge gray">${(group.sessions || []).length} 场</span></div>
        <div class="cc-tiny">${escapeHtml(detail)} · 共 ${formatBytes(group.totalBytes)}</div>
        ${(group.sessions || []).map(sessionDetails).join('')}
      </section>`;
    }).join('') || '<div class="cc-tiny">暂未找到课程录制。</div>');
  }

  function renderActiveRecordings(recordings) {
    const items = Array.isArray(recordings) ? recordings : [];
    text('phase5-active-recording-count', `${items.length} 场`);
    if (!items.length) {
      html('phase5-active-recordings', '<div class="cc-tiny">当前没有进行中的录制。</div>');
      return;
    }
    html('phase5-active-recordings', items.map((item) => {
      const started = item.startedAtIso
        ? new Date(item.startedAtIso).toLocaleString() : '未知';
      const student = item.studentId != null ? `儿童 #${item.studentId}` : '未关联儿童';
      const training = item.trainingSessionId || '—';
      return `<div style="border:1px solid #ffd9a8;background:#fff8f0;border-radius:10px;padding:10px;margin:8px 0;">
        <div><b>${escapeHtml(student)}</b> <span class="cc-badge warn">录制中</span>
          <span class="cc-tiny">${escapeHtml(item.humanDirName || item.sessionId || '')}</span></div>
        <div class="cc-tiny">开始：${escapeHtml(started)} · 训练：<code>${escapeHtml(training)}</code></div>
        <div class="cc-form-row" style="margin-top:7px;">
          <button type="button" class="cc-btn danger small" data-force-stop="${escapeHtml(item.sessionId)}">强制关闭录制</button>
          <button type="button" class="cc-btn soft small" data-force-stop-refresh>刷新</button>
        </div>
      </div>`;
    }).join(''));
  }

  async function loadActiveRecordings() {
    try {
      const body = await api.request('/api/v2/control/recordings/active');
      renderActiveRecordings(body.recordings || []);
    } catch (error) {
      text('phase5-active-recording-count', '—');
      html('phase5-active-recordings', `<div class="cc-notice warning">进行中录制加载失败：${escapeHtml(error.message)}</div>`);
    }
  }

  async function forceStopRecording(sessionId) {
    if (!window.confirm(`确认强制关闭这场录制吗？\n\n${sessionId}\n\n教师端将收到提示并需重新选择角色和课程。`)) return;
    try {
      const result = await api.json(`/api/v2/control/recordings/${encodeURIComponent(sessionId)}/force-stop`, 'POST', {});
      text('phase5-active-recording-count', '已强制关闭');
      await loadActiveRecordings();
      await loadOverview();
    } catch (error) {
      window.alert(`强制关闭失败：${error.message}`);
      await loadActiveRecordings();
    }
  }

  async function toggleRecordingLock(folderName, locked) {
    try {
      await api.json(`/api/v2/control/recordings/${encodeURIComponent(folderName)}/lock`, 'POST', { locked });
      await loadOverview();
    } catch (error) {
      window.alert(`上锁/解锁失败：${error.message}`);
    }
  }

  async function deleteRecording(folderName) {
    if (!window.confirm(`确认删除这场录制吗？\n\n${folderName}\n\n该文件夹内的全部文件将被永久删除，无法恢复。`)) return;
    try {
      await api.request(`/api/v2/control/recordings/${encodeURIComponent(folderName)}`, { method: 'DELETE' });
      await loadOverview();
    } catch (error) {
      window.alert(`删除失败：${error.message}`);
    }
  }

  async function loadOverview() {
    try {
      const body = await api.request('/api/v2/control/overview');
      renderDevices(body.devices || {});
      renderRecordings(body.recordings || {});
    } catch (error) {
      text('phase5-required-status', '检查失败');
      html('phase5-device-list', `<div class="cc-notice warning">总览加载失败：${escapeHtml(error.message)}</div>`);
    }
  }
  window.loadPhase5 = async () => { await Promise.all([loadOverview(), loadActiveRecordings()]); };

  async function addDevice() {
    const deviceId = byId('phase5-device-id').value.trim();
    if (!deviceId) return text('phase5-device-warning', '请输入设备编号。');
    try {
      const deviceIndex = Number(byId('phase5-device-index').value);
      if (!Number.isInteger(deviceIndex) || deviceIndex < 0) {
        return text('phase5-device-warning', '设备序号必须是大于等于 0 的整数。');
      }
      await api.json('/api/v2/capture/devices', 'POST', {
        deviceId,
        kind: byId('phase5-device-kind').value,
        role: byId('phase5-device-role').value,
        owner: byId('phase5-device-owner').value,
        selector: { index: deviceIndex },
        required: byId('phase5-device-required').checked,
        enabled: true,
      });
      byId('phase5-device-id').value = '';
      await loadOverview();
    } catch (error) { text('phase5-device-warning', `设备添加失败：${error.message}`); }
  }

  async function patchDevice(deviceId, value) {
    await api.json(`/api/v2/capture/devices/${encodeURIComponent(deviceId)}`, 'PATCH', value);
    await loadOverview();
  }

  async function removeDevice(deviceId) {
    if (!window.confirm(`确认从下一场课程配置中移除 ${deviceId}？历史录制不会删除。`)) return;
    await api.request(`/api/v2/capture/devices/${encodeURIComponent(deviceId)}`, { method: 'DELETE' });
    await loadOverview();
  }

  async function discoverDevices() {
    text('phase5-device-warning', '正在扫描 Server 电脑上的摄像头，请稍候…');
    try {
      const body = await api.request('/api/v2/capture/devices/candidates');
      const candidates = body.candidates || [];
      html('phase5-device-candidates', `
        <div class="cc-tiny"><b>本机发现的摄像头（点击后才会加入配置）</b></div>
        ${candidates.map((item) => `<div style="border:1px solid #e2e7f0;border-radius:10px;padding:10px;margin:8px 0;display:flex;align-items:center;justify-content:space-between;gap:10px;">
          <div><b>${escapeHtml(item.name)}</b><div class="cc-tiny">系统设备序号 ${item.index}</div></div>
          ${item.configuredDeviceId
            ? `<span class="cc-badge primary">已添加</span>`
            : `<button type="button" class="cc-btn primary small" data-device-candidate-add="${item.index}">添加到配置</button>`}
        </div>`).join('') || '<div class="cc-notice warning">没有发现可用摄像头，请确认摄像头已连接且未被其他程序独占。</div>'}`);
      text('phase5-device-warning', candidates.length
        ? '扫描完成。只有点击“添加到配置”的摄像头，才会进入课前检查和实时监控。'
        : '未发现可用摄像头。请检查连接后重试。');
    } catch (error) { text('phase5-device-warning', `设备发现失败：${error.message}`); }
  }

  async function addCandidate(index) {
    try {
      await api.json('/api/v2/capture/devices/candidates', 'POST', { index, required: false });
      text('phase5-device-warning', `摄像头 ${index} 已加入配置，正在执行课前首帧检查…`);
      await checkDevices();
      await discoverDevices();
    } catch (error) { text('phase5-device-warning', `摄像头添加失败：${error.message}`); }
  }

  async function checkDevices() {
    text('phase5-device-warning', '正在读取每台设备的首帧/首音频块…');
    try {
      const result = await api.json('/api/v2/control/devices/check', 'POST', {});
      text('phase5-device-warning', result.allConnected
        ? '设备检查完成：所有已检查设备均取得首样本。'
        : result.error === 'robot_runtime_upgrade_required'
          ? '机器人端在线，但版本过旧或协议不兼容，请升级 Robot Runtime 后重试。'
          : '设备检查完成：存在未连接或未取得首样本的设备，请查看状态。');
      await loadOverview();
    } catch (error) {
      text('phase5-device-warning', `设备检查失败：${error.message}`);
      await loadOverview();
    }
  }

  async function freezeDevices() {
    try {
      const result = await api.json('/api/v2/capture/snapshot', 'POST', {});
      text('phase5-device-warning', `下一场设备清单包含 ${(result.devices || []).length} 台额外设备；正式开课仍以当时自检结果为准。`);
    } catch (error) { text('phase5-device-warning', `设备清单生成失败：${error.message}`); }
  }

  async function inspectSession() {
    const id = byId('phase5-session-id').value.trim();
    if (!id) return text('phase5-session-result', '请输入 session id。');
    try { text('phase5-session-result', pretty(await api.request(`/api/media/${encodeURIComponent(id)}/status?includeQuality=1`))); }
    catch (error) { text('phase5-session-result', `检查失败：${error.message}`); }
  }

  async function revealFolder(folderName) {
    try { await api.json(`/api/v2/control/sessions/${encodeURIComponent(folderName)}/reveal`, 'POST', {}); }
    catch (error) { window.alert(`无法打开文件夹：${error.message}`); }
  }

  async function stageAssets() {
    const files = Array.from(byId('phase5-asset-files')?.files || []);
    if (!files.length) return text('phase5-asset-result', '请选择文件或 ZIP。');
    const data = new FormData();
    data.append('kind', byId('phase5-asset-kind').value);
    files.forEach((file) => data.append('files', file));
    try {
      const body = await api.request('/api/v2/assets/batch-import', { method: 'POST', body: data });
      stagingId = body.stage && body.stage.stagingId;
      text('phase5-asset-result', pretty(body.stage || body));
      byId('phase5-asset-commit').hidden = !stagingId;
    } catch (error) { text('phase5-asset-result', `导入失败：${error.message}`); }
  }

  async function commitAssets() {
    if (!stagingId) return;
    try {
      text('phase5-asset-result', pretty(await api.json(`/api/v2/assets/batch-import/${stagingId}/commit`, 'POST', { conflict: 'skip' })));
      byId('phase5-asset-commit').hidden = true;
    } catch (error) { text('phase5-asset-result', `提交失败：${error.message}`); }
  }

  async function resolveProfile() {
    const courseId = byId('phase5-profile-course').value.trim();
    if (!courseId) return text('phase5-profile-result', '请输入课程编号。');
    try {
      text('phase5-profile-result', pretty(await api.json('/api/v2/interaction/resolve', 'POST', {
        courseId,
        courseType: 'naming',
        eventKey: byId('phase5-profile-event').value.trim() || 'question.naming',
        sceneKey: byId('phase5-profile-scene').value.trim() || null,
        sessionId: 'control-preview',
      })));
    } catch (error) { text('phase5-profile-result', `解析失败：${error.message}`); }
  }

  document.addEventListener('DOMContentLoaded', () => {
    byId('phase5-overview-refresh')?.addEventListener('click', loadOverview);
    byId('phase5-device-refresh')?.addEventListener('click', checkDevices);
    byId('phase5-device-add')?.addEventListener('click', addDevice);
    byId('phase5-device-discover')?.addEventListener('click', discoverDevices);
    byId('phase5-device-freeze')?.addEventListener('click', freezeDevices);
    byId('phase5-device-candidates')?.addEventListener('click', (event) => {
      const button = event.target.closest('[data-device-candidate-add]');
      if (button) addCandidate(Number(button.dataset.deviceCandidateAdd));
    });
    byId('phase5-session-check')?.addEventListener('click', inspectSession);
    byId('phase5-asset-stage')?.addEventListener('click', stageAssets);
    byId('phase5-asset-commit')?.addEventListener('click', commitAssets);
    byId('phase5-profile-resolve')?.addEventListener('click', resolveProfile);
    byId('page-phase5')?.addEventListener('click', async (event) => {
      const target = event.target.closest('button');
      if (!target) return;
      try {
        if (target.dataset.deviceDelete) await removeDevice(target.dataset.deviceDelete);
        if (target.dataset.deviceToggle) await patchDevice(target.dataset.deviceToggle, { enabled: target.dataset.enabled !== '1' });
        if (target.dataset.deviceRequired) await patchDevice(target.dataset.deviceRequired, { required: target.dataset.required !== '1' });
        if (target.dataset.revealFolder) await revealFolder(target.dataset.revealFolder);
        if (target.dataset.forceStop) await forceStopRecording(target.dataset.forceStop);
        if (target.dataset.forceStopRefresh) await loadActiveRecordings();
        if (target.dataset.lockFolder) await toggleRecordingLock(target.dataset.lockFolder, target.dataset.locked !== '1');
        if (target.dataset.deleteFolder) await deleteRecording(target.dataset.deleteFolder);
      } catch (error) { text('phase5-device-warning', `操作失败：${error.message}`); }
    });
    if (document.body.dataset.module === 'devices') window.loadPhase5();
  });
})();
