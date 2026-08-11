const AXES = [
  { key: 'pitch', label: 'Pitch', title: '\u5934\u90e8\u4fef\u4ef0' },
  { key: 'yaw', label: 'Yaw', title: '\u5934\u90e8\u6c34\u5e73' },
  { key: 'arml', label: 'ArmL', title: '\u5de6\u81c2' },
  { key: 'armr', label: 'ArmR', title: '\u53f3\u81c2' },
];

const ARM_AXES = new Set(['arml', 'armr']);
const ARM_BASELINE_VERSION = 2;
const ARM_BASELINE_SHIFT_DEG = 90;
const ARM_CENTER = 270;
const ARM_SAFE_MIN = 0;
const ARM_SAFE_MAX = 359;
// Matches the authoritative first frame of the configured 空动作.
const DEFAULT_POSE = { pitch: 200, yaw: 160, arml: 320, armr: 50 };
const DEFAULT_TIMES = { pitch: 240, yaw: 240, arml: 240, armr: 240 };
const DOLLSER_AXIS_FIELDS = {
  pitch: { angle: 'Pitch', time: 'Pitch_Time', address: '/pitch', displayName: 'Pitch' },
  yaw: { angle: 'Yaw', time: 'Yaw_Time', address: '/yaw', displayName: 'Yaw' },
  arml: { angle: 'ArmL', time: 'ArmL_Time', address: '/arml', displayName: 'ArmL' },
  armr: { angle: 'ArmR', time: 'ArmR_Time', address: '/armr', displayName: 'ArmR' },
};
const LOCAL_RECORD_KEY = 'servo_workbench_recent_records_v1';
const LOCAL_TEMP_PRESET_KEY = 'servo_workbench_temp_presets_v1';
const LOCAL_SAFETY_KEY = 'servo_workbench_safety_v2';
const LOCAL_NEUTRAL_RETURN_KEY = 'servo_workbench_neutral_return_ms_v1';
const MAX_HISTORY = 80;
const SNAP_MS = 20;
const DEFAULT_RETURN_MS = 360;
const DEFAULT_NEUTRAL_RETURN_MS = 420;
const DEFAULT_SAFETY = {
  armBaselineVersion: ARM_BASELINE_VERSION,
  maxAngularVelocity: 160,
  axes: {
    pitch: { center: 200, direction: 1, forwardRange: 40, backwardRange: 80, min: 120, max: 240 },
    yaw: { center: 160, direction: 1, forwardRange: 80, backwardRange: 40, min: 120, max: 240 },
    arml: { center: 320, direction: 1, forwardRange: 45, backwardRange: 45, min: 275, max: 359 },
    armr: { center: 50, direction: 1, forwardRange: 45, backwardRange: 45, min: 5, max: 95 },
  },
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function clamp(value, min, max, fallback) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, Math.round(parsed)));
}

function clampRange(value, fallback = 30) {
  return clamp(value, 0, 180, fallback);
}

function normalizeDirection(value, fallback = 1) {
  return Number(value) < 0 ? -1 : (Number(fallback) < 0 ? -1 : 1);
}

function getAxisHardBounds(axisKey) {
  if (ARM_AXES.has(axisKey)) return { min: ARM_SAFE_MIN, max: ARM_SAFE_MAX };
  return { min: 0, max: 359 };
}

function deriveAxisLimits(axisKey, center, direction, forwardRange, backwardRange) {
  const hard = getAxisHardBounds(axisKey);
  const forwardAngle = center + direction * forwardRange;
  const backwardAngle = center - direction * backwardRange;
  return {
    min: Math.max(hard.min, Math.min(center, forwardAngle, backwardAngle)),
    max: Math.min(hard.max, Math.max(center, forwardAngle, backwardAngle)),
  };
}

function uid(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

function shiftLegacyArmAngle(value) {
  return Math.min(ARM_SAFE_MAX, Math.max(0, Math.round(Number(value) + ARM_BASELINE_SHIFT_DEG)));
}

function createPreset(overrides = {}) {
  const legacyArmBaseline = Number(overrides.armBaselineVersion || 1) < ARM_BASELINE_VERSION;
  const neutralFallback = overrides.centers?.pitch ?? overrides.centers?.yaw ?? DEFAULT_POSE.pitch;
  const neutral = clamp(overrides.neutral, 0, 359, neutralFallback);
  const centers = AXES.reduce((result, axis) => {
    const rawCenter = clamp(overrides.centers?.[axis.key], 0, 359, DEFAULT_POSE[axis.key] ?? neutral);
    result[axis.key] = legacyArmBaseline && ARM_AXES.has(axis.key) && overrides.centers?.[axis.key] !== undefined
      ? shiftLegacyArmAngle(rawCenter)
      : rawCenter;
    return result;
  }, {});
  const legacyExpressionAction = Array.isArray(overrides.actions)
    ? overrides.actions.find((action) => action?.expressionId)
    : null;
  const expressionSource = overrides.expression || (legacyExpressionAction ? {
    mediaId: legacyExpressionAction.expressionId,
    offsetMs: Number(legacyExpressionAction.expressionStartMs ?? legacyExpressionAction.startMs ?? 0) - Number(legacyExpressionAction.startMs || 0),
    durationMs: legacyExpressionAction.expressionDurationMs,
    loop: legacyExpressionAction.expressionLoop,
  } : {});
  return {
    id: overrides.id || uid('preset'),
    name: overrides.name || '\u65b0\u7684\u52a8\u4f5c',
    notes: overrides.notes || '',
    durationMs: clamp(overrides.durationMs, 500, 30000, 2400),
    neutral,
    armBaselineVersion: ARM_BASELINE_VERSION,
    centers,
    actions: Array.isArray(overrides.actions)
      ? overrides.actions.map((action) => createAction(action, { legacyArmBaseline }))
      : [],
    expression: {
      mediaId: String(expressionSource.mediaId || '').slice(0, 160),
      offsetMs: clamp(expressionSource.offsetMs, -30000, 30000, 0),
      durationMs: clamp(expressionSource.durationMs, 100, 30000, overrides.durationMs || 1000),
      loop: expressionSource.loop !== false,
    },
    builtin: Boolean(overrides.builtin),
    temporary: Boolean(overrides.temporary),
    stashed: Boolean(overrides.stashed),
    dirty: Boolean(overrides.dirty),
    updatedAt: overrides.updatedAt || new Date().toISOString(),
  };
}

function createAction(overrides = {}, options = {}) {
  const axis = AXES.some((item) => item.key === overrides.axis) ? overrides.axis : 'pitch';
  const requestedMoveMs = clamp(overrides.requestedMoveMs ?? overrides.moveMs, 50, 5000, 300);
  const startMs = clamp(overrides.startMs, 0, 30000, 0);
  const holdMs = clamp(overrides.holdMs, 0, 10000, 160);
  const returnMoveMs = clamp(overrides.returnMoveMs, 50, 5000, DEFAULT_RETURN_MS);
  const returnToCenter = overrides.returnToCenter !== false;
  const rawAngle = clamp(overrides.angle, 0, 359, DEFAULT_POSE[axis]);
  const angle = options.legacyArmBaseline && ARM_AXES.has(axis) && overrides.angle !== undefined
    ? shiftLegacyArmAngle(rawAngle)
    : rawAngle;
  return {
    id: overrides.id || uid('action'),
    axis,
    label: overrides.label || `${AXES.find((item) => item.key === axis).label} \u52a8\u4f5c`,
    startMs,
    angle,
    moveMs: clamp(overrides.moveMs, 50, 5000, requestedMoveMs),
    requestedMoveMs,
    holdMs,
    returnToCenter,
    returnMoveMs,
  };
}

const BUILTIN_PRESETS = [
  createPreset({
    id: 'builtin-nod',
    name: '点头确认',
    notes: '轻点两次，适合确认和回应。',
    durationMs: 1700,
    builtin: true,
    actions: [
      { axis: 'pitch', label: '点头 1', startMs: 0, angle: 196, moveMs: 220, holdMs: 40 },
      { axis: 'pitch', label: '点头 2', startMs: 460, angle: 192, moveMs: 220, holdMs: 40 },
    ],
  }),
  createPreset({
    id: 'builtin-greet',
    name: '挥手问候',
    notes: '右臂挥两次，头部略微抬起。',
    durationMs: 2600,
    builtin: true,
    actions: [
      { axis: 'pitch', label: '抬头保持', startMs: 0, angle: 168, moveMs: 280, holdMs: 1200 },
      { axis: 'armr', label: '挥手 1', startMs: 420, angle: 222, moveMs: 220, holdMs: 70 },
      { axis: 'armr', label: '挥手 2', startMs: 900, angle: 218, moveMs: 220, holdMs: 70 },
    ],
  }),
  createPreset({
    id: 'builtin-encourage',
    name: '鼓励',
    notes: '双臂上扬，头部轻微跟随。',
    durationMs: 2200,
    builtin: true,
    actions: [
      { axis: 'pitch', label: '轻抬头', startMs: 80, angle: 170, moveMs: 260, holdMs: 340 },
      { axis: 'arml', label: '左臂上扬', startMs: 160, angle: 208, moveMs: 320, holdMs: 260 },
      { axis: 'armr', label: '右臂上扬', startMs: 160, angle: 208, moveMs: 320, holdMs: 260 },
    ],
  }),
  createPreset({
    id: 'builtin-look-left-down',
    name: '左下看',
    notes: '头部同步转向左下，用作视线引导。',
    durationMs: 1600,
    builtin: true,
    actions: [
      { axis: 'pitch', label: '低头', startMs: 0, angle: 198, moveMs: 280, holdMs: 420 },
      { axis: 'yaw', label: '向左', startMs: 0, angle: 162, moveMs: 280, holdMs: 420 },
    ],
  }),
];

class Workbench {
  constructor() {
    this.dom = {};
    this.settings = { com: 7, pose: { ...DEFAULT_POSE }, times: { ...DEFAULT_TIMES } };
    this.currentPose = { ...DEFAULT_POSE };
    this.currentTimes = { ...DEFAULT_TIMES };
    this.savedPresets = [];
    this.tempPresets = this.restoreTempPresets();
    this.presets = clone(BUILTIN_PRESETS);
    this.selectedPresetId = this.presets[0].id;
    this.selectedActionId = this.presets[0].actions[0]?.id || '';
    this.sequenceRunning = false;
    this.pollTimer = null;
    this.toastTimer = null;
    this.undoStack = [];
    this.redoStack = [];
    this.pendingEditSnapshot = null;
    this.dragState = null;
    this.clipboardAction = null;
    this.safety = this.restoreSafetySettings();
    this.neutralReturnMs = this.restoreNeutralReturnMs();
    this.records = this.restoreRecords();
    this.faceLibrary = [];
    this.facePreviewTimer = null;
    this.expressionDurationCache = new Map();

    this.cacheDom();
    this.bindEvents();
    this.bootstrap();
  }

  cacheDom() {
    [
      'connection-badge', 'sequence-badge', 'osc-badge', 'preset-list', 'new-preset',
      'duplicate-preset', 'delete-preset', 'preset-name', 'preset-notes', 'duration-ms',
      'stash-preset', 'save-preset', 'export-preset', 'import-preset', 'import-file', 'play-preset', 'stop-sequence', 'send-neutral', 'neutral-time', 'undo-action', 'redo-action', 'ruler', 'timeline',
      'add-action', 'delete-action', 'action-inspector', 'send-current', 'save-config', 'config-com',
      'global-time', 'safety-settings', 'safety-modal', 'close-safety', 'safety-max-velocity', 'safety-axis-grid', 'log', 'toast',
      'delivery-status', 'test-preset', 'open-face-display',
      'sequence-expression-id', 'sequence-expression-offset', 'sequence-expression-duration', 'sequence-expression-loop',
      'preview-sequence-expression', 'refresh-expressions', 'sequence-expression-help',
    ].forEach((id) => {
      this.dom[id] = document.getElementById(id);
    });
  }

  bindEvents() {
    this.dom['new-preset'].addEventListener('click', () => this.createNewPreset());
    this.dom['duplicate-preset'].addEventListener('click', () => this.duplicatePreset());
    this.dom['delete-preset'].addEventListener('click', () => this.deletePreset());
    this.dom['stash-preset'].addEventListener('click', () => this.stashPreset());
    this.dom['save-preset'].addEventListener('click', () => this.savePreset());
    this.dom['export-preset'].addEventListener('click', () => this.exportSelectedPreset());
    this.dom['import-preset'].addEventListener('click', () => this.dom['import-file'].click());
    this.dom['import-file'].addEventListener('change', (event) => this.importPresetFromFile(event));
    this.dom['play-preset'].addEventListener('click', () => this.playSelectedPreset());
    this.dom['test-preset'].addEventListener('click', () => this.simulatePreset());
    this.dom['open-face-display'].addEventListener('click', () => window.open('/face.html', '_blank', 'noopener'));
    ['sequence-expression-id', 'sequence-expression-offset', 'sequence-expression-duration', 'sequence-expression-loop'].forEach((id) => {
      this.dom[id].addEventListener('change', (event) => this.updateSequenceExpression(event));
    });
    this.dom['preview-sequence-expression'].addEventListener('click', () => this.previewSequenceExpression());
    this.dom['refresh-expressions'].addEventListener('click', () => this.loadFaceLibrary(true));
    this.dom['stop-sequence'].addEventListener('click', () => this.stopSequence());
    this.dom['send-neutral'].addEventListener('click', () => this.sendNeutral());
    this.dom['neutral-time'].addEventListener('change', (event) => {
      this.neutralReturnMs = clamp(event.target.value, 50, 5000, DEFAULT_NEUTRAL_RETURN_MS);
      localStorage.setItem(LOCAL_NEUTRAL_RETURN_KEY, String(this.neutralReturnMs));
      this.dom['neutral-time'].value = this.neutralReturnMs;
      this.toast(`回中速度已设为 ${this.neutralReturnMs} ms`);
    });
    this.dom['undo-action'].addEventListener('click', () => this.undo());
    this.dom['redo-action'].addEventListener('click', () => this.redo());
    this.dom['safety-settings'].addEventListener('click', () => this.openSafetySettings());
    this.dom['close-safety']?.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      this.closeSafetySettings();
    });
    this.dom['send-current'].addEventListener('click', () => this.sendCurrentPose());
    this.dom['save-config'].addEventListener('click', () => this.saveConfig());
    this.dom['add-action']?.addEventListener('click', () => this.addAction());
    this.dom['delete-action']?.addEventListener('click', () => this.deleteSelectedAction());

    ['preset-name', 'preset-notes', 'duration-ms'].forEach((id) => {
      this.dom[id].addEventListener('focus', () => this.beginFieldEdit(`${id} edit`));
      this.dom[id].addEventListener('blur', () => this.commitFieldEdit());
    });

    this.dom['preset-name'].addEventListener('input', (event) => {
      this.getSelectedPreset().name = event.target.value.trim() || '\u672a\u547d\u540d\u52a8\u4f5c';
      this.syncPresetToSource(this.getSelectedPreset());
      this.renderPresetList();
    });

    this.dom['preset-notes'].addEventListener('input', (event) => {
      const preset = this.getSelectedPreset();
      preset.notes = event.target.value;
      this.syncPresetToSource(preset);
    });

    this.dom['duration-ms'].addEventListener('change', (event) => {
      const preset = this.getSelectedPreset();
      preset.durationMs = clamp(event.target.value, 500, 30000, 2400);
      this.syncPresetToSource(preset);
      this.renderTimeline();
    });

    this.dom['safety-max-velocity'].addEventListener('change', (event) => {
      this.safety.maxAngularVelocity = clamp(event.target.value, 1, 720, this.safety.maxAngularVelocity);
      this.saveSafetySettings();
      this.normalizePresetCenters(this.getSelectedPreset());
      this.applySafetyToPreset(this.getSelectedPreset(), { toast: true });
      this.render();
    });

    this.dom['safety-axis-grid'].addEventListener('change', (event) => {
      const input = event.target.closest('[data-safety-axis]');
      if (!input) return;

      const axis = input.dataset.safetyAxis;
      const field = input.dataset.safetyField;
      const limits = this.safety.axes[axis];
      if (!limits) return;

      const preset = this.getSelectedPreset();
      const preserveRelative = field === 'center' || field === 'direction';
      const relativeByActionId = preserveRelative
        ? new Map(preset.actions
          .filter((action) => action.axis === axis)
          .map((action) => [action.id, this.angleToRelative(axis, action.angle)]))
        : null;

      if (field === 'center') {
        limits.center = clamp(input.value, 0, 359, this.getAxisCenter(preset, axis));
      } else if (field === 'direction') {
        limits.direction = normalizeDirection(input.value, limits.direction);
      } else if (field === 'forwardRange' || field === 'backwardRange') {
        limits[field] = clampRange(input.value, limits[field]);
      }

      this.recalculateAxisLimits(axis);
      this.setAxisCenter(preset, axis, limits.center);

      if (relativeByActionId) {
        preset.actions.forEach((action) => {
          if (action.axis !== axis || !relativeByActionId.has(action.id)) return;
          action.angle = this.relativeToAngle(axis, relativeByActionId.get(action.id));
        });
      }

      this.saveSafetySettings();
      this.normalizePresetCenters(this.getSelectedPreset());
      this.applySafetyToPreset(this.getSelectedPreset(), { toast: true });
      this.render();
    });

    this.dom['global-time'].addEventListener('change', (event) => {
      const time = clamp(event.target.value, 50, 5000, 240);
      AXES.forEach((axis) => {
        this.currentTimes[axis.key] = time;
      });
    });

    this.dom['timeline'].addEventListener('click', (event) => {
      const addButton = event.target.closest('[data-add-axis]');
      const block = event.target.closest('[data-action-id]');

      if (addButton) {
        this.addAction(addButton.dataset.addAxis);
        return;
      }

      if (block) {
        this.selectedActionId = block.dataset.actionId;
        this.render();
        return;
      }

    });

    this.dom['timeline'].addEventListener('pointerdown', (event) => this.beginDragAction(event));

    this.dom['action-inspector'].addEventListener('focusin', (event) => {
      if (event.target.closest('[data-action-field]')) {
        this.beginFieldEdit('action edit');
      }
    });
    this.dom['action-inspector'].addEventListener('focusout', (event) => {
      if (event.target.closest('[data-action-field]')) {
        this.commitFieldEdit();
      }
    });
    this.dom['action-inspector'].addEventListener('input', (event) => this.updateSelectedAction(event));
    this.dom['action-inspector'].addEventListener('change', (event) => this.updateSelectedAction(event));
    this.dom['action-inspector'].addEventListener('click', (event) => {
      const button = event.target.closest('[data-delete-action]');
      const nudgeButton = event.target.closest('[data-action-nudge]');
      if (button) {
        this.deleteSelectedAction();
        return;
      }

      if (nudgeButton) {
        this.nudgeSelectedAction(nudgeButton.dataset.actionNudge, Number(nudgeButton.dataset.nudgeValue || 0));
        return;
      }

    });
    this.dom['action-inspector'].addEventListener('change', (event) => {
      const quickControl = event.target.closest('[data-action-quick]');
      if (quickControl) {
        this.applyActionQuickControl(quickControl.dataset.actionQuick, quickControl.value);
      }
    });

    document.addEventListener('pointermove', (event) => this.dragAction(event));
    document.addEventListener('pointerup', (event) => this.endDragAction(event));
    document.addEventListener('keydown', (event) => this.handleShortcuts(event));
  }

  async bootstrap() {
    await Promise.all([this.loadConfig(), this.loadSafetySettings(), this.loadSavedPresets(), this.loadFaceLibrary()]);
    this.render();
    this.startPolling();
  }

  async api(path, options = {}) {
    const response = await fetch(path, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `\u8bf7\u6c42\u5931\u8d25: ${path}`);
    }
    return payload;
  }

  async loadConfig(showToast = false) {
    try {
      const payload = await this.api('/api/config');
      this.settings = payload.config;
      this.currentPose = payload.current.pose;
      this.currentTimes = payload.current.times;
      this.dom['config-com'].value = this.settings.com;
      this.dom['global-time'].value = Math.max(...Object.values(this.currentTimes));
      this.dom['connection-badge'].textContent = '\u5df2\u8fde\u63a5';
      this.dom['connection-badge'].className = 'badge ok';
      this.dom['osc-badge'].textContent = `OSC ${payload.osc.host}:${payload.osc.port}`;
      this.updateSequenceStatus(payload.sequence, payload.lastCommand);
      if (showToast) this.toast('\u5df2\u91cd\u65b0\u8bfb\u53d6 Settings.xml');
    } catch (error) {
      this.dom['connection-badge'].textContent = '\u8fde\u63a5\u5931\u8d25';
      this.dom['connection-badge'].className = 'badge';
      this.log(`\u8fde\u63a5\u5931\u8d25: ${error.message}`);
    }
  }

  async loadSavedPresets() {
    try {
      const payload = await this.api('/api/presets');
      this.savedPresets = payload.presets.map((preset) => createPreset({ ...preset, dirty: false, temporary: false, stashed: false }));
      this.mergePresets();
    } catch (error) {
      this.log(`\u8bfb\u53d6\u9884\u8bbe\u5931\u8d25: ${error.message}`);
    }
  }

  async loadSafetySettings() {
    try {
      const payload = await this.api('/api/safety');
      this.safety = this.normalizeSafetySettings(payload.safety);
      this.saveSafetySettings({ remote: false });
    } catch (error) {
      this.log(`\u8bfb\u53d6\u5b89\u5168\u8bbe\u7f6e\u5931\u8d25\uff0c\u4f7f\u7528\u672c\u5730\u7f13\u5b58: ${error.message}`);
    }
  }

  async loadFaceLibrary(showToast = false) {
    try {
      const payload = await this.api('/api/face/media');
      this.faceLibrary = Array.isArray(payload.face?.library) ? payload.face.library : [];
      if (showToast) this.toast(`已读取 ${this.faceLibrary.length} 个表情文件`);
      this.renderTimeline();
      this.renderInspector();
      this.renderSequenceExpressionFields();
    } catch (error) {
      this.log(`读取表情目录失败: ${error.message}`);
    }
  }

  mergePresets() {
    this.presets = [
      ...clone(BUILTIN_PRESETS),
      ...this.tempPresets.map((preset) => createPreset({ ...preset, builtin: false, temporary: true })),
      ...this.savedPresets.map((preset) => createPreset({ ...preset, builtin: false, temporary: false })),
    ];
    this.presets.forEach((preset) => {
      this.normalizePresetCenters(preset);
      this.applySafetyToPreset(preset);
    });
    if (!this.presets.some((preset) => preset.id === this.selectedPresetId)) {
      this.selectedPresetId = this.presets[0]?.id || '';
      this.selectedActionId = this.presets[0]?.actions[0]?.id || '';
    }
  }

  snapshot() {
    return {
      savedPresets: clone(this.savedPresets),
      tempPresets: clone(this.tempPresets),
      presets: clone(this.presets),
      selectedPresetId: this.selectedPresetId,
      selectedActionId: this.selectedActionId,
    };
  }

  restoreSnapshot(snapshot) {
    this.savedPresets = clone(snapshot.savedPresets);
    this.tempPresets = clone(snapshot.tempPresets || []);
    this.presets = clone(snapshot.presets);
    this.selectedPresetId = snapshot.selectedPresetId;
    this.selectedActionId = snapshot.selectedActionId;
    this.render();
    this.updateHistoryButtons();
  }

  pushHistory(label = 'edit') {
    this.undoStack.push({ label, state: this.snapshot() });
    if (this.undoStack.length > MAX_HISTORY) {
      this.undoStack.shift();
    }
    this.redoStack = [];
    this.updateHistoryButtons();
  }

  beginFieldEdit(label) {
    if (this.pendingEditSnapshot) return;
    this.pendingEditSnapshot = { label, state: this.snapshot() };
  }

  commitFieldEdit() {
    if (!this.pendingEditSnapshot) return;
    const before = JSON.stringify(this.pendingEditSnapshot.state.presets);
    const after = JSON.stringify(this.presets);

    if (before !== after) {
      this.undoStack.push(this.pendingEditSnapshot);
      if (this.undoStack.length > MAX_HISTORY) {
        this.undoStack.shift();
      }
      this.redoStack = [];
      this.updateHistoryButtons();
    }

    this.pendingEditSnapshot = null;
  }

  undo() {
    this.commitFieldEdit();
    const entry = this.undoStack.pop();
    if (!entry) return;

    this.redoStack.push({ label: entry.label, state: this.snapshot() });
    this.restoreSnapshot(entry.state);
    this.toast(`\u5df2\u64a4\u9500: ${this.humanHistoryLabel(entry.label)}`);
  }

  redo() {
    const entry = this.redoStack.pop();
    if (!entry) return;

    this.undoStack.push({ label: entry.label, state: this.snapshot() });
    this.restoreSnapshot(entry.state);
    this.toast(`\u5df2\u91cd\u505a: ${this.humanHistoryLabel(entry.label)}`);
  }

  updateHistoryButtons() {
    if (!this.dom['undo-action'] || !this.dom['redo-action']) return;
    this.dom['undo-action'].disabled = this.undoStack.length === 0;
    this.dom['redo-action'].disabled = this.redoStack.length === 0;
  }

  humanHistoryLabel(label) {
    const labels = {
      'new preset': '\u65b0\u5efa\u9884\u8bbe',
      'duplicate preset': '\u590d\u5236\u9884\u8bbe',
      'delete preset': '\u5220\u9664\u9884\u8bbe',
      'add action': '\u65b0\u5efa\u52a8\u4f5c\u5757',
      'delete action': '\u5220\u9664\u52a8\u4f5c\u5757',
      'drag action': '\u79fb\u52a8\u52a8\u4f5c\u5757',
      'resize action': '\u8c03\u6574\u52a8\u4f5c\u5757\u65f6\u957f',
      'stash preset': '\u6682\u5b58\u52a8\u4f5c',
      'action edit': '\u7f16\u8f91\u52a8\u4f5c\u5757',
      'center angle edit': '\u7f16\u8f91\u4e2d\u4f4d\u89d2\u5ea6',
      'preset-name edit': '\u7f16\u8f91\u540d\u79f0',
      'preset-notes edit': '\u7f16\u8f91\u5907\u6ce8',
      'duration-ms edit': '\u7f16\u8f91\u603b\u65f6\u957f',
      'sequence expression edit': '编辑序列表情',
    };
    return labels[label] || '\u7f16\u8f91';
  }

  handleShortcuts(event) {
    if (event.key === 'Escape' && this.dom['safety-modal']?.open) {
      event.preventDefault();
      this.closeSafetySettings();
      return;
    }

    const isUndo = (event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === 'z';
    const isRedo = (event.ctrlKey || event.metaKey) && (event.key.toLowerCase() === 'y' || (event.shiftKey && event.key.toLowerCase() === 'z'));
    const isCopy = (event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === 'c';
    const isPaste = (event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === 'v';
    const activeTag = document.activeElement?.tagName?.toLowerCase();
    const isTextEditing = ['input', 'textarea', 'select'].includes(activeTag) || document.activeElement?.isContentEditable;

    if (isUndo) {
      event.preventDefault();
      this.undo();
    }

    if (isRedo) {
      event.preventDefault();
      this.redo();
    }

    if (isTextEditing) return;

    if (isCopy) {
      event.preventDefault();
      this.copySelectedAction();
    }

    if (isPaste) {
      event.preventDefault();
      this.pasteActionBlock();
    }
  }

  getSelectedPreset() {
    return this.presets.find((preset) => preset.id === this.selectedPresetId) || this.presets[0];
  }

  syncPresetToSource(preset = this.getSelectedPreset(), options = {}) {
    if (!preset || preset.builtin) return;

    if (!preset.temporary && options.dirty !== false) {
      preset.dirty = true;
    }

    const normalized = createPreset({ ...preset, builtin: false, temporary: Boolean(preset.temporary) });
    if (preset.temporary) {
      const index = this.tempPresets.findIndex((item) => item.id === preset.id);
      if (index >= 0) {
        this.tempPresets[index] = { ...normalized, temporary: true, builtin: false };
      } else {
        this.tempPresets.unshift({ ...normalized, temporary: true, builtin: false });
      }
      if (options.persist !== false) this.saveTempPresets();
      return;
    }

    const index = this.savedPresets.findIndex((item) => item.id === preset.id);
    if (index >= 0) {
      this.savedPresets[index] = { ...normalized, temporary: false, builtin: false };
    }
  }

  getSelectedAction() {
    const preset = this.getSelectedPreset();
    return preset.actions.find((action) => action.id === this.selectedActionId) || null;
  }

  getAxisCenter(preset = this.getSelectedPreset(), axisKey = 'pitch') {
    const safetyCenter = this.safety?.axes?.[axisKey]?.center;
    return clamp(safetyCenter, 0, 359, preset?.centers?.[axisKey] ?? preset?.neutral ?? DEFAULT_POSE[axisKey] ?? 180);
  }

  getAxisDirection(axisKey) {
    return normalizeDirection(this.getAxisSafety(axisKey).direction, DEFAULT_SAFETY.axes[axisKey]?.direction ?? 1);
  }

  getAxisRange(axisKey, field) {
    const fallback = DEFAULT_SAFETY.axes[axisKey]?.[field] ?? 30;
    return clampRange(this.getAxisSafety(axisKey)[field], fallback);
  }

  angleToRelative(axisKey, angle) {
    const center = this.getAxisCenter(this.getSelectedPreset(), axisKey);
    return clamp((clamp(angle, 0, 359, center) - center) * this.getAxisDirection(axisKey), -180, 180, 0);
  }

  relativeToAngle(axisKey, relativeOffset) {
    const center = this.getAxisCenter(this.getSelectedPreset(), axisKey);
    const forwardRange = this.getAxisRange(axisKey, 'forwardRange');
    const backwardRange = this.getAxisRange(axisKey, 'backwardRange');
    const offset = clamp(relativeOffset, -backwardRange, forwardRange, 0);
    return this.clampAxisAngle(axisKey, center + this.getAxisDirection(axisKey) * offset, center);
  }

  recalculateAxisLimits(axisKey) {
    const limits = this.getAxisSafety(axisKey);
    const fallback = DEFAULT_SAFETY.axes[axisKey] || { center: 180, direction: 1, forwardRange: 30, backwardRange: 30 };
    const hard = getAxisHardBounds(axisKey);
    limits.center = clamp(limits.center, hard.min, hard.max, fallback.center);
    limits.direction = normalizeDirection(limits.direction, fallback.direction);
    limits.forwardRange = clampRange(limits.forwardRange, fallback.forwardRange);
    limits.backwardRange = clampRange(limits.backwardRange, fallback.backwardRange);
    const derived = deriveAxisLimits(axisKey, limits.center, limits.direction, limits.forwardRange, limits.backwardRange);
    limits.min = derived.min;
    limits.max = derived.max;
    return limits;
  }

  setAxisCenter(preset, axisKey, center) {
    const nextCenter = this.clampAxisAngle(axisKey, center, this.getAxisCenter(preset, axisKey));
    if (!this.safety.axes[axisKey]) this.safety.axes[axisKey] = { ...DEFAULT_SAFETY.axes[axisKey] };
    this.safety.axes[axisKey].center = nextCenter;
    if (!preset.centers) preset.centers = {};
    preset.centers[axisKey] = nextCenter;
    preset.neutral = preset.centers.pitch ?? preset.neutral ?? 180;
  }

  normalizePresetCenters(preset) {
    AXES.forEach((axis) => {
      this.setAxisCenter(preset, axis.key, this.getAxisCenter(preset, axis.key));
    });
  }

  openSafetySettings() {
    this.dom['safety-modal'].open = true;
  }

  closeSafetySettings() {
    this.dom['safety-modal'].open = false;
  }

  getAxisSafety(axisKey) {
    return this.safety.axes[axisKey] || DEFAULT_SAFETY.axes[axisKey] || { min: 0, max: 359 };
  }

  clampAxisAngle(axisKey, angle, fallback = 180) {
    const limits = this.getAxisSafety(axisKey);
    return clamp(angle, limits.min, limits.max, fallback);
  }

  enforceActionSafety(action, options = {}) {
    if (!action) return false;

    const preset = this.getSelectedPreset();
    const beforeAngle = action.angle;
    const beforeMove = action.moveMs;
    const beforeReturnMove = action.returnMoveMs;
    action.angle = this.clampAxisAngle(action.axis, action.angle, beforeAngle);
    action.requestedMoveMs = clamp(action.requestedMoveMs ?? action.moveMs, 50, 5000, action.moveMs);
    action.returnMoveMs = clamp(action.returnMoveMs, 50, 5000, DEFAULT_RETURN_MS);

    const maxVelocity = Math.max(1, Number(this.safety.maxAngularVelocity) || DEFAULT_SAFETY.maxAngularVelocity);
    const deltaDeg = Math.abs(this.angleToRelative(action.axis, action.angle));
    const minMoveMs = clamp(Math.ceil((deltaDeg / maxVelocity) * 1000), 50, 5000, 50);
    action.moveMs = clamp(Math.max(action.requestedMoveMs, minMoveMs), 50, 5000, beforeMove);
    action.returnMoveMs = clamp(Math.max(action.returnMoveMs, minMoveMs), 50, 5000, beforeReturnMove);

    const changed = beforeAngle !== action.angle || beforeMove !== action.moveMs || beforeReturnMove !== action.returnMoveMs;
    if (changed && !options.silent) {
      this.toast('\u5df2\u6309\u5b89\u5168\u9650\u5236\u8c03\u6574\u89d2\u5ea6\u6216\u901f\u5ea6');
    }
    return changed;
  }

  applySafetyToPreset(preset, options = {}) {
    if (!preset) return false;
    let changed = false;
    preset.actions.forEach((action) => {
      changed = this.enforceActionSafety(action, { silent: true }) || changed;
    });
    if (changed && options.toast) {
      this.toast('\u5df2\u6309\u5b89\u5168\u9650\u5236\u4fee\u6b63\u5f53\u524d\u52a8\u4f5c');
    }
    return changed;
  }

  copySelectedAction() {
    const action = this.getSelectedAction();
    if (!action) {
      this.toast('\u5148\u9009\u62e9\u4e00\u4e2a\u52a8\u4f5c\u5757');
      return;
    }

    this.clipboardAction = clone(action);
    this.toast(`\u5df2\u590d\u5236\u52a8\u4f5c\u5757: ${action.label}`);
  }

  pasteActionBlock() {
    if (!this.clipboardAction) {
      this.toast('\u526a\u8d34\u677f\u91cc\u8fd8\u6ca1\u6709\u52a8\u4f5c\u5757');
      return;
    }

    const preset = this.getSelectedPreset();
    this.commitFieldEdit();
    this.pushHistory('paste action');
    const source = this.clipboardAction;
    const action = createAction({
      ...source,
      id: uid('action'),
      label: `${source.label} \u526f\u672c`,
    });
    this.enforceActionSafety(action, { silent: true });
    preset.actions.push(action);
    this.selectedActionId = action.id;
    this.syncPresetToSource(preset);
    this.render();
    this.toast('\u5df2\u7c98\u8d34\u52a8\u4f5c\u5757');
  }

  render() {
    this.renderPresetList();
    this.renderPresetFields();
    this.renderSafetyPanel();
    this.renderTimeline();
    this.renderInspector();
    this.renderDeliveryStatus();
    this.updateHistoryButtons();
  }

  getDeliveryReport(preset = this.getSelectedPreset()) {
    const normalized = createPreset(clone(preset));
    this.normalizePresetCenters(normalized);
    this.applySafetyToPreset(normalized);
    const payload = this.buildUnifiedDollSerExportPayload(normalized);
    return { payload, report: MotionStandard.validateMotionDocument(payload) };
  }

  renderDeliveryStatus() {
    if (!this.dom['delivery-status']) return;
    const { report } = this.getDeliveryReport();
    const status = report.valid
      ? (report.warnings.length ? `格式合格，建议确认 ${report.warnings.length} 项提醒` : '格式合格，可以导出交付')
      : `发现 ${report.errors.length} 项错误，暂不能导出`;
    const visibleIssues = report.issues.slice(0, 4);

    this.dom['delivery-status'].innerHTML = `
      <div class="delivery-summary">
        <div class="delivery-metric"><span>指令</span><strong>${report.stats.commandCount}</strong></div>
        <div class="delivery-metric"><span>控制轴</span><strong>${report.stats.axisCount}/4</strong></div>
        <div class="delivery-metric"><span>表情</span><strong>${report.stats.expressionCount || 0}</strong></div>
        <div class="delivery-metric"><span>总时长</span><strong>${report.stats.durationMs} ms</strong></div>
      </div>
      <p class="delivery-result ${report.valid ? '' : 'has-errors'}">${this.escape(status)}</p>
      ${visibleIssues.length ? `<ul class="issue-list">${visibleIssues.map((item) => (
        `<li>${item.severity === 'error' ? '错误' : '提醒'} · ${this.escape(MotionStandard.formatIssue(item))}</li>`
      )).join('')}</ul>` : ''}
    `;
    this.dom['export-preset'].disabled = !report.valid;
    this.dom['test-preset'].disabled = report.stats.commandCount === 0;
  }

  simulatePreset() {
    const preset = this.getSelectedPreset();
    const { payload, report } = this.getDeliveryReport(preset);
    if (!report.valid) {
      this.toast(`模拟测试未通过：${report.errors[0].message}`);
      this.log(`模拟测试失败 ${preset.name}: ${report.errors.map(MotionStandard.formatIssue).join('；')}`);
      return;
    }

    const commandSummary = payload.commands.map((command) => (
      `${command.time}ms ${command.axis} → ${command.angle}° / ${command.moveMs}ms`
    )).join('；');
    this.log(`模拟测试通过 ${preset.name}: ${payload.commands.length} 条指令，${payload.durationMs} ms${report.warnings.length ? `，${report.warnings.length} 项提醒` : ''}`);
    this.log(`模拟指令: ${commandSummary}`);
    if (payload.expression) {
      this.log(`模拟表情: ${payload.expression.mediaId}: ${payload.expression.time}ms 开始，相对动作序列 ${payload.expression.offsetMs}ms，显示 ${payload.expression.durationMs}ms`);
    }
    this.toast(report.warnings.length ? `模拟通过，需确认 ${report.warnings.length} 项提醒` : '模拟测试通过，可以进行实机测试或导出');
  }

  renderPresetList() {
    this.dom['preset-list'].innerHTML = this.presets.map((preset) => `
      <button class="preset-item ${preset.id === this.selectedPresetId ? 'active' : ''}" type="button" data-preset-id="${preset.id}">
        <div class="preset-title-row">
          <strong>${this.escape(preset.name)}</strong>
          <span class="preset-badge ${this.getPresetState(preset).className}">${this.getPresetState(preset).label}</span>
        </div>
        <span>${preset.actions.length} \u4e2a\u52a8\u4f5c\u5757 ? ${preset.durationMs} ms</span>
      </button>
    `).join('');

    this.dom['preset-list'].querySelectorAll('[data-preset-id]').forEach((button) => {
      button.addEventListener('click', () => {
        this.selectedPresetId = button.dataset.presetId;
        const firstAction = this.getSelectedPreset().actions[0];
        this.selectedActionId = firstAction?.id || '';
        this.render();
      });
    });

    this.dom['delete-preset'].disabled = this.getSelectedPreset().builtin;
  }

  getPresetKindLabel(preset) {
    if (preset.builtin) return '\u7cfb\u7edf\u6a21\u677f';
    if (preset.temporary && preset.stashed) return '\u6682\u5b58';
    if (preset.temporary) return '\u672a\u4fdd\u5b58';
    if (preset.dirty) return '\u672a\u4fdd\u5b58';
    return '\u6587\u4ef6\u9884\u8bbe';
  }

  getPresetState(preset) {
    if (preset.builtin) return { label: '\u6a21\u677f', className: 'template' };
    if (preset.temporary && preset.stashed) return { label: '\u6682\u5b58', className: 'stashed' };
    if (preset.temporary || preset.dirty) return { label: '\u672a\u4fdd\u5b58', className: 'draft' };
    return { label: '\u5df2\u4fdd\u5b58', className: 'saved' };
  }

  renderPresetFields() {
    const preset = this.getSelectedPreset();
    this.normalizePresetCenters(preset);
    this.dom['preset-name'].value = preset.name;
    this.dom['preset-notes'].value = preset.notes || '';
    this.dom['duration-ms'].value = preset.durationMs;
    this.dom['neutral-time'].value = this.neutralReturnMs;
    this.renderSequenceExpressionFields();
  }

  renderSequenceExpressionFields() {
    const preset = this.getSelectedPreset();
    const expression = preset.expression;
    const missing = expression.mediaId && !this.faceLibrary.some((item) => item.id === expression.mediaId);
    this.dom['sequence-expression-id'].innerHTML = `
      <option value="">不使用表情</option>
      ${missing ? `<option value="${this.escape(expression.mediaId)}" selected>${this.escape(expression.mediaId)} · 文件未找到</option>` : ''}
      ${this.faceLibrary.map((media) => (
        `<option value="${this.escape(media.id)}" ${expression.mediaId === media.id ? 'selected' : ''}>${this.escape(media.fileName)} · ${media.mediaType === 'image' ? '图片' : '视频'}</option>`
      )).join('')}
    `;
    this.dom['sequence-expression-offset'].value = expression.offsetMs;
    this.dom['sequence-expression-duration'].value = expression.durationMs;
    this.dom['sequence-expression-loop'].value = String(expression.loop);
    this.dom['duration-ms'].readOnly = false;
    this.dom['duration-ms'].title = '表情不会修改舵机序列时长，只会扩展统一播放时间轴';
    const relation = expression.offsetMs < 0
      ? `表情比动作序列提前 ${(Math.abs(expression.offsetMs) / 1000).toFixed(2)} 秒`
      : (expression.offsetMs > 0 ? `表情比动作序列延后 ${(expression.offsetMs / 1000).toFixed(2)} 秒` : '表情与动作序列同时开始');
    const totalDurationMs = this.getSequencePlaybackTiming(preset).totalDurationMs;
    this.dom['sequence-expression-help'].textContent = expression.mediaId
      ? `${relation}。舵机序列保持 ${preset.durationMs} ms，统一播放总时长为 ${totalDurationMs} ms。`
      : '每个动作序列只匹配一个表情。选择文件后可在下方表情轨道调整时间。';
    this.dom['preview-sequence-expression'].disabled = !expression.mediaId;
  }

  async updateSequenceExpression(event) {
    const preset = this.getSelectedPreset();
    const presetId = preset.id;
    this.pushHistory('sequence expression edit');
    this.captureSequenceExpressionForm(preset);
    if (event?.target?.id === 'sequence-expression-id' && preset.expression.mediaId) {
      const mediaDurationMs = await this.readExpressionMediaDurationMs(preset.expression.mediaId);
      if (this.getSelectedPreset().id !== presetId) return;
      if (mediaDurationMs > 0) preset.expression.durationMs = mediaDurationMs;
    }
    this.syncPresetToSource(preset);
    this.renderTimeline();
    this.renderSequenceExpressionFields();
    this.renderDeliveryStatus();
  }

  captureSequenceExpressionForm(preset = this.getSelectedPreset()) {
    if (!preset || !this.dom['sequence-expression-id']) return;
    preset.expression = {
      mediaId: this.dom['sequence-expression-id'].value,
      offsetMs: clamp(this.dom['sequence-expression-offset'].value, -30000, 30000, 0),
      durationMs: clamp(this.dom['sequence-expression-duration'].value, 100, 30000, preset.durationMs),
      loop: this.dom['sequence-expression-loop'].value === 'true',
    };
  }

  readExpressionMediaDurationMs(mediaId) {
    if (this.expressionDurationCache.has(mediaId)) {
      return Promise.resolve(this.expressionDurationCache.get(mediaId));
    }
    const media = this.faceLibrary.find((item) => item.id === mediaId);
    if (!media || media.mediaType !== 'video') return Promise.resolve(0);

    return new Promise((resolve) => {
      const video = document.createElement('video');
      let settled = false;
      const finish = (durationMs = 0) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        video.removeAttribute('src');
        video.load();
        if (durationMs > 0) this.expressionDurationCache.set(mediaId, durationMs);
        resolve(durationMs);
      };
      const timer = setTimeout(() => finish(0), 4000);
      video.preload = 'metadata';
      video.muted = true;
      video.addEventListener('loadedmetadata', () => {
        const durationMs = Number.isFinite(video.duration) ? Math.round(video.duration * 1000) : 0;
        finish(durationMs);
      }, { once: true });
      video.addEventListener('error', () => finish(0), { once: true });
      video.src = `${media.url}?v=${encodeURIComponent(media.updatedAt || '')}`;
      video.load();
    });
  }

  renderSafetyPanel() {
    this.dom['safety-max-velocity'].value = this.safety.maxAngularVelocity;
    this.dom['safety-axis-grid'].innerHTML = AXES.map((axis) => {
      const limits = this.recalculateAxisLimits(axis.key);
      const center = this.getAxisCenter(this.getSelectedPreset(), axis.key);
      const direction = this.getAxisDirection(axis.key);
      return `
        <div class="safety-axis-card">
          <div class="safety-axis-title"><span class="axis-dot ${axis.key}"></span>${axis.label}</div>
          <label>
            <span>中位角度</span>
            <input data-safety-axis="${axis.key}" data-safety-field="center" type="number" min="0" max="359" step="1" value="${center}">
          </label>
          <label>
            <span>正方向</span>
            <select data-safety-axis="${axis.key}" data-safety-field="direction">
              <option value="1" ${direction > 0 ? 'selected' : ''}>+ 增加角度</option>
              <option value="-1" ${direction < 0 ? 'selected' : ''}>- 减少角度</option>
            </select>
          </label>
          <label>
            <span>前向行程 +°</span>
            <input data-safety-axis="${axis.key}" data-safety-field="forwardRange" type="number" min="0" max="180" step="1" value="${limits.forwardRange}">
          </label>
          <label>
            <span>后向行程 -°</span>
            <input data-safety-axis="${axis.key}" data-safety-field="backwardRange" type="number" min="0" max="180" step="1" value="${limits.backwardRange}">
          </label>
          <p class="help-text">安全范围 ${limits.min}° - ${limits.max}°</p>
        </div>
      `;
    }).join('');
  }

  getSequencePlaybackTiming(preset = this.getSelectedPreset()) {
    const expression = preset.expression || { mediaId: '', offsetMs: 0, durationMs: preset.durationMs, loop: true };
    const timing = MotionStandard.buildSequenceExpressionTiming(expression, preset.durationMs);
    return {
      expression,
      offsetMs: timing.offsetMs,
      motionStartMs: timing.motionStartTime,
      expressionStartMs: timing.expressionTime,
      totalDurationMs: Math.max(500, timing.durationMs),
    };
  }

  renderTimeline() {
    const preset = this.getSelectedPreset();
    const timing = this.getSequencePlaybackTiming(preset);
    const duration = timing.totalDurationMs;
    const ticks = [];
    const step = duration <= 3000 ? 500 : 1000;

    for (let ms = 0; ms <= duration; ms += step) {
      ticks.push(`<span class="tick" style="left:${(ms / duration) * 100}%">${ms}ms</span>`);
    }
    this.dom['ruler'].innerHTML = ticks.join('');

    const axisTracks = AXES.map((axis) => {
      const actions = preset.actions
        .filter((action) => action.axis === axis.key)
        .sort((left, right) => left.startMs - right.startMs);

      return `
        <article class="track">
          <div class="track-side">
            <div class="axis-name"><span class="axis-dot ${axis.key}"></span>${axis.label}</div>
            <small style="color: var(--muted)">${axis.title}</small>
            <small style="color: var(--muted)">中位 ${this.getAxisCenter(preset, axis.key)}° · +${this.getAxisRange(axis.key, 'forwardRange')} / -${this.getAxisRange(axis.key, 'backwardRange')}</small>
            <button data-add-axis="${axis.key}" type="button">在此轨道新建动作</button>
          </div>
          <div class="lane" data-lane-axis="${axis.key}">
            ${actions.map((action) => {
              const playbackStartMs = action.startMs + timing.motionStartMs;
              const left = Math.min(98, (playbackStartMs / duration) * 100);
              const width = Math.max(4, (this.getActionSpan(action) / duration) * 100);
              const relativeOffset = this.angleToRelative(action.axis, action.angle);
              return `
                <button
                  class="block ${axis.key} ${action.id === this.selectedActionId ? 'selected' : ''} ${this.dragState?.actionId === action.id ? 'dragging' : ''}"
                  type="button"
                  data-action-id="${action.id}"
                  data-drag-action="true"
                  style="left:${left}%;width:${Math.min(width, 100 - left)}%"
                  title="拖动调整开始时间，拖到其他轨道可移动轨道"
                >
                  <span class="resize-handle left" data-resize-edge="left"></span>
                  <strong>${this.escape(action.label)}</strong>
                  <span>${playbackStartMs}ms · ${relativeOffset >= 0 ? '+' : ''}${relativeOffset}° · ${action.angle}°</span>
                  <span class="resize-handle right" data-resize-edge="right"></span>
                </button>
              `;
            }).join('')}
          </div>
        </article>
      `;
    }).join('');

    const expression = timing.expression;
    const expressionMedia = this.faceLibrary.find((item) => item.id === expression.mediaId);
    const expressionTrack = `
      <article class="track expression-track">
        <div class="track-side">
          <div class="axis-name"><span class="expression-dot"></span>表情</div>
          <small style="color: var(--muted)">与上方动作共用时间刻度</small>
          <small style="color: var(--muted)">${this.faceLibrary.length} 个可用文件 · ${expression.mediaId ? '已匹配序列表情' : '未匹配'}</small>
        </div>
        <div class="lane" data-lane-expression="true">
          ${expression.mediaId ? (() => {
            const left = Math.min(98, (timing.expressionStartMs / duration) * 100);
            const width = Math.max(4, (expression.durationMs / duration) * 100);
            return `
              <button
                class="block expression-block ${this.dragState?.mode?.startsWith('sequence-expression') ? 'dragging' : ''}"
                type="button"
                data-sequence-expression="true"
                style="left:${left}%;width:${Math.min(width, 100 - left)}%"
                title="拖动对齐表情，拖左右边缘调整显示时长"
              >
                <span class="resize-handle left" data-resize-edge="left"></span>
                <strong>${this.escape(expressionMedia?.fileName || expression.mediaId)}</strong>
                <span>${timing.expressionStartMs}ms · ${expression.durationMs}ms · 偏移 ${expression.offsetMs}ms</span>
                <span class="resize-handle right" data-resize-edge="right"></span>
              </button>
            `;
          })() : ''}
        </div>
      </article>
    `;
    this.dom['timeline'].innerHTML = axisTracks + expressionTrack;
  }

  renderInspector() {
    const action = this.getSelectedAction();
    if (this.dom['delete-action']) {
      this.dom['delete-action'].disabled = !action;
    }
    if (!action) {
      this.dom['action-inspector'].innerHTML = '<div class="empty">先在某条轨道里点击“在此轨道新建动作”，或选择一个已有动作块。</div>';
      return;
    }

    const preset = this.getSelectedPreset();
    const center = this.getAxisCenter(preset, action.axis);
    const safetyLimits = this.getAxisSafety(action.axis);
    const totalMs = this.getActionSpan(action);
    const signedDeltaDeg = this.angleToRelative(action.axis, action.angle);
    const deltaDeg = Math.abs(signedDeltaDeg);
    const angularVelocity = action.moveMs > 0 ? (deltaDeg / (action.moveMs / 1000)) : 0;
    const speedLabel = this.getSpeedLabel(action.moveMs);

    this.dom['action-inspector'].innerHTML = `
      <div class="metric-strip">
        <div class="metric-box">
          <span>总时长</span>
          <strong>${totalMs} ms</strong>
        </div>
        <div class="metric-box">
          <span>角度变化</span>
          <strong>${deltaDeg}°</strong>
        </div>
        <div class="metric-box">
          <span>角速度</span>
          <strong>${angularVelocity.toFixed(1)} °/s</strong>
        </div>
      </div>
      <div class="inspector-grid">
        <label class="wide">
          <span>名称</span>
          <input data-action-field="label" type="text" maxlength="48" value="${this.escape(action.label)}">
        </label>
        <label>
          <span>轨道</span>
          <select data-action-field="axis">
            ${AXES.map((axis) => `<option value="${axis.key}" ${action.axis === axis.key ? 'selected' : ''}>${axis.label} · ${axis.title}</option>`).join('')}
          </select>
        </label>
        <label>
          <span>相对中位偏移</span>
          <input data-action-field="relativeAngle" type="number" min="${-this.getAxisRange(action.axis, 'backwardRange')}" max="${this.getAxisRange(action.axis, 'forwardRange')}" step="1" value="${signedDeltaDeg}">
        </label>
        <label>
          <span>舵机绝对角度</span>
          <input data-action-field="angle" type="number" min="${safetyLimits.min}" max="${safetyLimits.max}" value="${action.angle}">
        </label>
        <label>
          <span>到位时间 / 速度 ms</span>
          <input data-action-field="moveMs" type="number" min="50" max="5000" step="10" value="${action.moveMs}">
        </label>
        <label>
          <span>结束回中位</span>
          <select data-action-field="returnToCenter">
            <option value="true" ${action.returnToCenter ? 'selected' : ''}>是</option>
            <option value="false" ${!action.returnToCenter ? 'selected' : ''}>否</option>
          </select>
        </label>
        <label>
          <span>回位速度 ms</span>
          <input data-action-field="returnMoveMs" type="number" min="50" max="5000" step="10" value="${action.returnMoveMs}">
        </label>
      </div>
      <details class="action-section" style="margin-top: 10px;">
        <summary class="group-label">时间细节</summary>
        <div class="inspector-grid">
          <label>
            <span>开始 ms</span>
            <input data-action-field="startMs" type="number" min="0" max="30000" step="20" value="${action.startMs}">
          </label>
          <label>
            <span>保持 ms</span>
            <input data-action-field="holdMs" type="number" min="0" max="10000" step="10" value="${action.holdMs}">
          </label>
        </div>
        <p class="help-text">开始和保持通常直接在时间轴上拖动更快；这里用于精确输入或复核。</p>
      </details>
      <section class="action-section" style="margin-top: 10px;">
        <div class="group-label">微调</div>
        <div class="micro-grid">
          <label>
            <span>预设角度</span>
            <select data-action-quick="anglePreset">
              <option value="">当前: ${action.angle}°</option>
              <option value="0">中位 ${center}°</option>
              <option value="-8">小幅 -8°</option>
              <option value="8">小幅 +8°</option>
              <option value="-18">中幅 -18°</option>
              <option value="18">中幅 +18°</option>
              <option value="-32">大幅 -32°</option>
              <option value="32">大幅 +32°</option>
            </select>
          </label>
          <label>
            <span>速度档位</span>
            <select data-action-quick="speedPreset">
              <option value="">当前: ${speedLabel}</option>
              <option value="620">慢速找角度</option>
              <option value="360">自然</option>
              <option value="220">利落</option>
              <option value="140">很快</option>
            </select>
          </label>
          <label>
            <span>回位速度档位</span>
            <select data-action-quick="returnSpeedPreset">
              <option value="">当前: ${this.getSpeedLabel(action.returnMoveMs)}</option>
              <option value="520">慢速</option>
              <option value="360">自然</option>
              <option value="220">利落</option>
              <option value="140">很快</option>
            </select>
          </label>
          <label>
            <span>保持档位</span>
            <select data-action-quick="holdPreset">
              <option value="">当前: ${action.holdMs} ms</option>
              <option value="0">不保持</option>
              <option value="120">短停</option>
              <option value="320">自然停顿</option>
              <option value="700">强调停顿</option>
            </select>
          </label>
          <label>
            <span>动作总时长</span>
            <select data-action-quick="spanPreset">
              <option value="">当前: ${totalMs} ms</option>
              <option value="360">短促 360ms</option>
              <option value="640">自然 640ms</option>
              <option value="1000">展开 1000ms</option>
              <option value="1500">强调 1500ms</option>
            </select>
          </label>
          <label>
            <span>起始对齐</span>
            <select data-action-quick="startPreset">
              <option value="">当前: ${action.startMs} ms</option>
              <option value="0">从开头开始</option>
              <option value="250">稍后 250ms</option>
              <option value="500">半秒后</option>
              <option value="1000">一秒后</option>
            </select>
          </label>
        </div>
        <div>
          <p class="help-text">角度微调</p>
          <div class="nudge-row">
            <button type="button" data-action-nudge="angle" data-nudge-value="-5">-5°</button>
            <button type="button" data-action-nudge="angle" data-nudge-value="-1">-1°</button>
            <button type="button" data-action-nudge="angle" data-nudge-value="1">+1°</button>
            <button type="button" data-action-nudge="angle" data-nudge-value="5">+5°</button>
          </div>
        </div>
        <p class="help-text">当前目标相对中位 ${signedDeltaDeg >= 0 ? '+' : ''}${signedDeltaDeg}°。速度数值越小动作越快；角速度按“角度变化 / 到位时间”估算。</p>
        <details class="action-section">
          <summary class="group-label">时间微调</summary>
          <p class="help-text">时间通常直接在轨道上拖动；这里用于需要一点点补偿时。</p>
          <div class="nudge-row">
            <button type="button" data-action-nudge="startMs" data-nudge-value="-40">提前</button>
            <button type="button" data-action-nudge="startMs" data-nudge-value="40">延后</button>
            <button type="button" data-action-nudge="moveMs" data-nudge-value="-40">更快</button>
            <button type="button" data-action-nudge="moveMs" data-nudge-value="40">更慢</button>
          </div>
          <div class="nudge-row" style="margin-top: 6px;">
            <button type="button" data-action-nudge="holdMs" data-nudge-value="-80">少停</button>
            <button type="button" data-action-nudge="holdMs" data-nudge-value="80">多停</button>
            <button type="button" data-action-nudge="spanMs" data-nudge-value="-80">缩短</button>
            <button type="button" data-action-nudge="spanMs" data-nudge-value="80">拉长</button>
          </div>
        </details>
      </section>
    `;
  }

  updateSelectedAction(event) {
    const field = event.target.dataset.actionField;
    if (!field) return;

    const action = this.getSelectedAction();
    if (!action) return;

    const previousRelative = this.angleToRelative(action.axis, action.angle);

    if (field === 'label') action.label = event.target.value;
    if (field === 'axis') {
      action.axis = event.target.value;
      action.angle = this.relativeToAngle(action.axis, previousRelative);
    }
    if (field === 'angle') action.angle = clamp(event.target.value, 0, 359, action.angle);
    if (field === 'relativeAngle') action.angle = this.relativeToAngle(action.axis, event.target.value);
    if (field === 'startMs') action.startMs = clamp(event.target.value, 0, 30000, action.startMs);
    if (field === 'moveMs') {
      action.requestedMoveMs = clamp(event.target.value, 50, 5000, action.requestedMoveMs ?? action.moveMs);
      action.moveMs = action.requestedMoveMs;
    }
    if (field === 'returnMoveMs') action.returnMoveMs = clamp(event.target.value, 50, 5000, action.returnMoveMs);
    if (field === 'holdMs') action.holdMs = clamp(event.target.value, 0, 10000, action.holdMs);
    if (field === 'returnToCenter') action.returnToCenter = event.target.value === 'true';

    this.enforceActionSafety(action, { silent: event.type === 'input' });
    this.syncPresetToSource(this.getSelectedPreset());
    this.renderPresetList();
    this.renderTimeline();
    if (event.type === 'change') this.renderInspector();
  }

  getSpeedLabel(moveMs) {
    if (moveMs <= 170) return '很快';
    if (moveMs <= 260) return '利落';
    if (moveMs <= 460) return '自然';
    return '\u6162\u901f';
  }

  async previewSequenceExpression() {
    const expression = this.getSelectedPreset().expression;
    if (!expression.mediaId) {
      this.toast('请先为当前动作序列选择表情文件');
      return;
    }

    clearTimeout(this.facePreviewTimer);
    try {
      await this.api('/api/face/play', {
        method: 'POST',
        body: JSON.stringify({ mediaId: expression.mediaId, loop: expression.loop }),
      });
      this.toast(`正在预览序列表情: ${expression.mediaId}`);
      this.facePreviewTimer = setTimeout(() => {
        this.api('/api/face/stop', { method: 'POST', body: '{}' }).catch(() => {});
      }, expression.durationMs);
    } catch (error) {
      this.toast(`表情预览失败: ${error.message}`);
    }
  }

  nudgeSelectedAction(field, delta) {
    const action = this.getSelectedAction();
    const preset = this.getSelectedPreset();
    if (!action || !Number.isFinite(delta)) return;

    this.commitFieldEdit();
    this.pushHistory('action edit');

    if (field === 'angle') {
      action.angle = this.relativeToAngle(action.axis, this.angleToRelative(action.axis, action.angle) + delta);
    }

    if (field === 'startMs') {
      action.startMs = this.snapMs(clamp(action.startMs + delta, 0, preset.durationMs, action.startMs));
    }

    if (field === 'moveMs') {
      action.requestedMoveMs = clamp((action.requestedMoveMs ?? action.moveMs) + delta, 50, 5000, action.requestedMoveMs ?? action.moveMs);
      action.moveMs = action.requestedMoveMs;
    }

    if (field === 'returnMoveMs') {
      action.returnMoveMs = clamp(action.returnMoveMs + delta, 50, 5000, action.returnMoveMs);
    }

    if (field === 'holdMs') {
      action.holdMs = clamp(action.holdMs + delta, 0, 10000, action.holdMs);
    }

    if (field === 'spanMs') {
      this.setActionSpan(action, clamp(this.getActionSpan(action) + delta, this.getMinimumActionSpan(action), 30000, this.getActionSpan(action)));
    }

    this.enforceActionSafety(action);
    this.syncPresetToSource(preset);
    this.renderPresetList();
    this.renderTimeline();
    this.renderInspector();
  }

  applyActionQuickControl(kind, value) {
    const action = this.getSelectedAction();
    if (!action || value === '') return;

    this.commitFieldEdit();
    this.pushHistory('action edit');

    if (kind === 'speedPreset') {
      action.requestedMoveMs = clamp(value, 50, 5000, action.requestedMoveMs ?? action.moveMs);
      action.moveMs = action.requestedMoveMs;
    }

    if (kind === 'returnSpeedPreset') {
      action.returnMoveMs = clamp(value, 50, 5000, action.returnMoveMs);
    }

    if (kind === 'anglePreset') {
      action.angle = this.relativeToAngle(action.axis, Number(value));
    }

    if (kind === 'holdPreset') {
      action.holdMs = clamp(value, 0, 10000, action.holdMs);
    }

    if (kind === 'spanPreset') {
      this.setActionSpan(action, clamp(value, this.getMinimumActionSpan(action), 30000, this.getActionSpan(action)));
    }

    if (kind === 'startPreset') {
      const preset = this.getSelectedPreset();
      action.startMs = this.snapMs(clamp(value, 0, preset.durationMs, action.startMs));
    }

    this.enforceActionSafety(action);
    this.syncPresetToSource(this.getSelectedPreset());
    this.renderPresetList();
    this.renderTimeline();
    this.renderInspector();
  }

  beginDragAction(event) {
    const block = event.target.closest('[data-drag-action], [data-sequence-expression]');
    if (!block) return;

    const preset = this.getSelectedPreset();
    const isSequenceExpression = block.hasAttribute('data-sequence-expression');
    const lane = block.closest(isSequenceExpression ? '[data-lane-expression]' : '[data-lane-axis]');
    const action = isSequenceExpression ? null : preset.actions.find((item) => item.id === block.dataset.actionId);
    if ((!isSequenceExpression && !action) || !lane) return;

    event.preventDefault();
    if (action) this.selectedActionId = action.id;
    const rect = lane.getBoundingClientRect();
    const timing = this.getSequencePlaybackTiming(preset);

    this.dragState = {
      actionId: action?.id || '',
      pointerId: event.pointerId,
      startClientX: event.clientX,
      laneLeft: rect.left,
      laneWidth: rect.width,
      durationMs: timing.totalDurationMs,
      startMs: action?.startMs || 0,
      startSpanMs: action ? this.getActionSpan(action) : 0,
      startHoldMs: action?.holdMs || 0,
      startAxis: action?.axis || '',
      startRelativeAngle: action ? this.angleToRelative(action.axis, action.angle) : 0,
      expressionOffsetMs: preset.expression.offsetMs,
      expressionStartMs: timing.expressionStartMs,
      expressionDurationMs: preset.expression.durationMs,
      motionStartMs: timing.motionStartMs,
      mode: isSequenceExpression
        ? (event.target.dataset.resizeEdge ? 'sequence-expression-resize' : 'sequence-expression-move')
        : (event.target.dataset.resizeEdge ? 'resize' : 'move'),
      edge: event.target.dataset.resizeEdge || '',
      historyPushed: false,
      moved: false,
    };

    block.setPointerCapture?.(event.pointerId);
    this.renderTimeline();
    if (!isSequenceExpression) this.renderInspector();
  }

  dragAction(event) {
    if (!this.dragState) return;

    const preset = this.getSelectedPreset();
    const action = preset.actions.find((item) => item.id === this.dragState.actionId);
    const isSequenceExpression = this.dragState.mode.startsWith('sequence-expression');
    if (!isSequenceExpression && !action) return;

    const deltaPx = event.clientX - this.dragState.startClientX;
    if (!this.dragState.moved && Math.abs(deltaPx) < 3) return;

    if (!this.dragState.historyPushed) {
      this.pushHistory(isSequenceExpression ? 'sequence expression edit' : (this.dragState.mode.includes('resize') ? 'resize action' : 'drag action'));
      this.dragState.historyPushed = true;
    }

    this.dragState.moved = true;
    const deltaMs = (deltaPx / Math.max(1, this.dragState.laneWidth)) * this.dragState.durationMs;

    if (this.dragState.mode === 'sequence-expression-resize') {
      const oldEnd = this.dragState.expressionStartMs + this.dragState.expressionDurationMs;
      if (this.dragState.edge === 'right') {
        preset.expression.durationMs = this.snapMs(clamp(
          this.dragState.expressionDurationMs + deltaMs,
          100,
          30000,
          this.dragState.expressionDurationMs
        ));
      } else {
        const nextStart = this.snapMs(clamp(
          this.dragState.expressionStartMs + deltaMs,
          0,
          oldEnd - 100,
          this.dragState.expressionStartMs
        ));
        preset.expression.offsetMs = this.snapMs(clamp(nextStart - this.dragState.motionStartMs, -30000, 30000, preset.expression.offsetMs));
        preset.expression.durationMs = oldEnd - nextStart;
      }
    } else if (this.dragState.mode === 'sequence-expression-move') {
      const nextStart = this.snapMs(clamp(
        this.dragState.expressionStartMs + deltaMs,
        0,
        this.dragState.durationMs,
        this.dragState.expressionStartMs
      ));
      preset.expression.offsetMs = this.snapMs(clamp(nextStart - this.dragState.motionStartMs, -30000, 30000, preset.expression.offsetMs));
    } else if (this.dragState.mode === 'resize') {
      this.resizeActionByDrag(action, deltaMs, preset.durationMs);
    } else {
      const actionSpan = this.getActionSpan(action);
      action.startMs = this.snapMs(clamp(this.dragState.startMs + deltaMs, 0, Math.max(0, preset.durationMs - actionSpan), action.startMs));

      const targetLane = document.elementFromPoint(event.clientX, event.clientY)?.closest?.('[data-lane-axis]');
      if (targetLane?.dataset.laneAxis && AXES.some((axis) => axis.key === targetLane.dataset.laneAxis)) {
        const nextAxis = targetLane.dataset.laneAxis;
        if (action.axis !== nextAxis) {
          action.axis = nextAxis;
          action.angle = this.relativeToAngle(nextAxis, this.dragState.startRelativeAngle);
        }
        this.enforceActionSafety(action, { silent: true });
      }
    }

    this.renderTimeline();
    if (isSequenceExpression) this.renderSequenceExpressionFields();
    else this.renderInspector();
  }

  endDragAction(event) {
    if (!this.dragState) return;

    const wasMoved = this.dragState.moved;
    const actionId = this.dragState.actionId;
    const wasSequenceExpression = this.dragState.mode.startsWith('sequence-expression');
    this.dragState = null;

    if (!wasMoved) {
      if (actionId) this.selectedActionId = actionId;
      this.render();
    } else {
      this.syncPresetToSource(this.getSelectedPreset());
      this.renderPresetList();
      this.renderTimeline();
      if (wasSequenceExpression) this.renderSequenceExpressionFields();
      else this.renderInspector();
    }
  }

  snapMs(value) {
    return Math.round(value / SNAP_MS) * SNAP_MS;
  }

  getActionSpan(action) {
    return action.moveMs + action.holdMs + (action.returnToCenter ? action.returnMoveMs : 0);
  }

  getMinimumActionSpan(action) {
    return action.moveMs + (action.returnToCenter ? action.returnMoveMs : 0);
  }

  setActionSpan(action, totalSpanMs) {
    const minimumSpan = this.getMinimumActionSpan(action);
    action.holdMs = Math.max(0, this.snapMs(totalSpanMs - minimumSpan));
  }

  resizeActionByDrag(action, deltaMs, timelineDurationMs) {
    const minimumSpan = this.getMinimumActionSpan(action);

    if (this.dragState.edge === 'right') {
      const maxSpan = Math.max(minimumSpan, timelineDurationMs - this.dragState.startMs);
      const nextSpan = this.snapMs(clamp(this.dragState.startSpanMs + deltaMs, minimumSpan, maxSpan, this.dragState.startSpanMs));
      this.setActionSpan(action, nextSpan);
      return;
    }

    const oldEnd = this.dragState.startMs + this.dragState.startSpanMs;
    const nextStart = this.snapMs(clamp(this.dragState.startMs + deltaMs, 0, oldEnd - minimumSpan, this.dragState.startMs));
    action.startMs = nextStart;
    this.setActionSpan(action, oldEnd - nextStart);
  }

  addAction(axisKey = 'pitch') {
    this.commitFieldEdit();
    this.pushHistory('add action');
    const preset = this.getSelectedPreset();
    const action = createAction({
      axis: axisKey,
      startMs: Math.min(preset.durationMs - 300, Math.max(0, preset.actions.length * 300)),
      angle: this.relativeToAngle(axisKey, 20),
    });
    this.enforceActionSafety(action, { silent: true });
    preset.actions.push(action);
    this.selectedActionId = action.id;
    this.syncPresetToSource(preset);
    this.render();
  }

  deleteSelectedAction() {
    this.commitFieldEdit();
    this.pushHistory('delete action');
    const preset = this.getSelectedPreset();
    preset.actions = preset.actions.filter((action) => action.id !== this.selectedActionId);
    this.selectedActionId = preset.actions[0]?.id || '';
    this.syncPresetToSource(preset);
    this.render();
  }

  createNewPreset() {
    this.commitFieldEdit();
    this.pushHistory('new preset');
    const preset = createPreset({
      id: uid('preset'),
      name: '\u65b0\u7684\u52a8\u4f5c',
      actions: [],
      neutral: this.getAxisCenter(this.getSelectedPreset(), 'pitch'),
      armBaselineVersion: ARM_BASELINE_VERSION,
      centers: AXES.reduce((result, axis) => {
        result[axis.key] = this.getAxisCenter(this.getSelectedPreset(), axis.key);
        return result;
      }, {}),
      temporary: true,
      stashed: false,
    });
    this.tempPresets.unshift(preset);
    this.saveTempPresets();
    this.mergePresets();
    this.selectedPresetId = preset.id;
    this.selectedActionId = '';
    this.render();
  }

  duplicatePreset() {
    this.commitFieldEdit();
    this.pushHistory('duplicate preset');
    const source = clone(this.getSelectedPreset());
    const preset = createPreset({
      ...source,
      id: uid('preset'),
      name: `${source.name} \u526f\u672c`,
      actions: source.actions.map((action) => ({ ...action, id: uid('action') })),
      builtin: false,
      temporary: true,
      stashed: false,
      updatedAt: new Date().toISOString(),
    });
    this.tempPresets.unshift(preset);
    this.saveTempPresets();
    this.mergePresets();
    this.selectedPresetId = preset.id;
    this.selectedActionId = preset.actions[0]?.id || '';
    this.render();
  }

  async deletePreset() {
    const preset = this.getSelectedPreset();
    if (preset.builtin) return;

    try {
      this.commitFieldEdit();
      this.pushHistory('delete preset');
      if (preset.temporary) {
        this.tempPresets = this.tempPresets.filter((item) => item.id !== preset.id);
        this.saveTempPresets();
        this.mergePresets();
        this.selectedPresetId = this.presets[0].id;
        this.selectedActionId = this.presets[0].actions[0]?.id || '';
        this.render();
        this.toast('\u6682\u5b58\u52a8\u4f5c\u5df2\u5220\u9664');
        return;
      }

      await this.api(`/api/presets/${encodeURIComponent(preset.id)}`, { method: 'DELETE' });
      this.savedPresets = this.savedPresets.filter((item) => item.id !== preset.id);
      this.mergePresets();
      this.selectedPresetId = this.presets[0].id;
      this.selectedActionId = this.presets[0].actions[0]?.id || '';
      this.render();
      this.toast('\u9884\u8bbe\u5df2\u5220\u9664');
    } catch (error) {
      this.toast(error.message);
    }
  }

  async savePreset() {
    const preset = this.getSelectedPreset();
    this.captureSequenceExpressionForm(preset);
    const mediaDurationMs = await this.readExpressionMediaDurationMs(preset.expression.mediaId);
    if (mediaDurationMs > 0) preset.expression.durationMs = mediaDurationMs;
    this.normalizePresetCenters(preset);
    this.applySafetyToPreset(preset, { toast: true });
    this.syncPresetToSource(preset);
    const payload = createPreset({ ...preset, builtin: false, temporary: false, updatedAt: new Date().toISOString() });

    if (preset.builtin || preset.temporary) {
      payload.id = uid('preset');
      payload.name = preset.builtin ? `${preset.name} \u8c03\u6574\u7248` : preset.name;
    }

    try {
      const result = await this.api('/api/presets', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      this.savedPresets = result.presets.map((item) => createPreset({ ...item, dirty: false, temporary: false, stashed: false }));
      this.tempPresets = this.tempPresets.filter((item) => item.id !== preset.id && item.id !== result.preset.id);
      this.saveTempPresets();
      this.mergePresets();
      this.selectedPresetId = result.preset.id;
      this.selectedActionId = result.preset.actions[0]?.id || '';
      this.render();
      this.toast(`\u5df2\u4fdd\u5b58\u5230\u9884\u8bbe\u6587\u4ef6: ${result.preset.name}`);
    } catch (error) {
      this.toast(error.message);
    }
  }

  stashPreset() {
    this.commitFieldEdit();
    this.pushHistory('stash preset');
    const source = this.getSelectedPreset();
    this.captureSequenceExpressionForm(source);
    this.normalizePresetCenters(source);
    this.applySafetyToPreset(source, { toast: true });
    const stashed = createPreset({
      ...source,
      id: source.temporary ? source.id : uid('temp'),
      name: source.name,
      builtin: false,
      temporary: true,
      stashed: true,
      updatedAt: new Date().toISOString(),
    });

    const index = this.tempPresets.findIndex((preset) => preset.id === stashed.id);
    if (index >= 0) {
      this.tempPresets[index] = stashed;
    } else {
      this.tempPresets.unshift(stashed);
    }

    this.saveTempPresets();
    this.mergePresets();
    this.selectedPresetId = stashed.id;
    this.render();
    this.toast(`\u5df2\u6682\u5b58\u52a8\u4f5c: ${stashed.name}`);
  }

  async exportSelectedPreset() {
    this.captureSequenceExpressionForm(this.getSelectedPreset());
    const selectedPreset = this.getSelectedPreset();
    const mediaDurationMs = await this.readExpressionMediaDurationMs(selectedPreset.expression.mediaId);
    if (mediaDurationMs > 0) selectedPreset.expression.durationMs = mediaDurationMs;
    const preset = createPreset(clone(this.getSelectedPreset()));
    this.normalizePresetCenters(preset);
    this.applySafetyToPreset(preset, { toast: true });
    const payload = this.buildUnifiedDollSerExportPayload(preset);
    const report = MotionStandard.validateMotionDocument(payload);
    if (!report.valid) {
      this.toast(`导出已停止：${report.errors[0].message}`);
      return;
    }

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.href = url;
    link.download = `${this.slugifyFileName(preset.name)}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    this.toast(`已导出 DollSer 统一动作格式: ${preset.name}`);
  }

  buildUnifiedDollSerExportPayload(preset) {
    const timing = this.getSequencePlaybackTiming(preset);
    const playbackPreset = {
      ...preset,
      durationMs: timing.totalDurationMs,
      actions: preset.actions.map((action) => ({ ...action, startMs: action.startMs + timing.motionStartMs })),
    };
    const commands = this.buildDollSerTimelineCommands(playbackPreset).map((command) => ({
      actionId: command.actionId,
      time: command.atMs,
      axis: this.toPublicAxis(command.axis),
      angle: command.angle,
      moveMs: command.timeMs,
      label: command.label,
      phase: command.phase,
    }));
    const expression = preset.expression.mediaId ? {
      scope: 'sequence',
      mediaId: preset.expression.mediaId,
      time: timing.expressionStartMs,
      motionStartTime: timing.motionStartMs,
      offsetMs: preset.expression.offsetMs,
      leadMs: Math.max(0, -preset.expression.offsetMs),
      leadSeconds: Math.max(0, -preset.expression.offsetMs) / 1000,
      durationMs: preset.expression.durationMs,
      loop: preset.expression.loop,
    } : null;
    const durationMs = Math.max(
      timing.totalDurationMs,
      ...commands.map((command) => command.time + command.moveMs),
      expression ? expression.time + expression.durationMs : 0,
      0
    );

    return {
      version: 2,
      format: 'dollser-motion',
      armBaselineVersion: ARM_BASELINE_VERSION,
      updatedAt: new Date().toISOString(),
      name: preset.name,
      durationMs,
      motionDurationMs: preset.durationMs,
      motionStartTime: timing.motionStartMs,
      initialPose: this.toSeniorPose(preset.centers),
      commands,
      expression,
    };
  }

  async importPresetFromFile(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      const report = MotionStandard.validateMotionDocument(payload);
      if (!report.valid) {
        throw new Error(report.errors.slice(0, 3).map(MotionStandard.formatIssue).join('；'));
      }
      const preset = this.createPresetFromImportedMotion(payload, file.name);

      this.commitFieldEdit();
      this.pushHistory('import preset');
      this.tempPresets.unshift(preset);
      this.saveTempPresets();
      this.mergePresets();
      this.selectedPresetId = preset.id;
      this.selectedActionId = preset.actions[0]?.id || '';
      this.render();
      this.toast(`已导入 JSON: ${preset.name}`);
    } catch (error) {
      this.toast(`导入失败: ${error.message}`);
    }
  }

  createPresetFromImportedMotion(payload) {
    if (payload?.format === 'dollser-motion' && Number(payload.version) === 2) {
      return this.createPresetFromCommandMotion(payload);
    }

    throw new Error('仅支持 version=2 且 format=dollser-motion 的 JSON');
  }

  createPresetFromCommandMotion(payload) {
    const legacyArmBaseline = Number(payload.armBaselineVersion || 1) < ARM_BASELINE_VERSION;
    const sequenceExpression = payload.expression || (Array.isArray(payload.expressions) ? payload.expressions[0] : null);
    const motionStartTime = clamp(
      sequenceExpression?.motionStartTime ?? payload.motionStartTime,
      0,
      30000,
      0
    );
    const commands = Array.isArray(payload.commands)
      ? payload.commands.map((command, index) => this.normalizeImportedCommand(command, index, { legacyArmBaseline }))
      : [];
    commands.forEach((command) => { command.time = Math.max(0, command.time - motionStartTime); });
    if (!commands.length) {
      throw new Error('commands 不能为空');
    }

    const initialPose = this.normalizeImportedPose(payload.initialPose || {}, { legacyArmBaseline });
    const centers = {
      pitch: initialPose.pitch,
      yaw: initialPose.yaw,
      arml: initialPose.arml,
      armr: initialPose.armr,
    };
    const usedReturnIndexes = new Set();
    const actions = [];

    commands
      .filter((command) => command.phase !== 'return')
      .sort((left, right) => left.time - right.time)
      .forEach((command) => {
        const returnIndex = this.findImportedReturnCommandIndex(command, commands, usedReturnIndexes, centers);
        const returnCommand = returnIndex >= 0 ? commands[returnIndex] : null;
        if (returnIndex >= 0) usedReturnIndexes.add(returnIndex);

        const action = createAction({
          id: command.actionId || uid('action'),
          axis: command.axis,
          label: command.label || `${this.getAxisLabel(command.axis)} 动作`,
          startMs: command.time,
          angle: command.angle,
          moveMs: command.moveMs,
          requestedMoveMs: command.moveMs,
          holdMs: returnCommand ? Math.max(0, returnCommand.time - command.time - command.moveMs) : 0,
          returnToCenter: Boolean(returnCommand),
          returnMoveMs: returnCommand?.moveMs ?? DEFAULT_RETURN_MS,
        });
        actions.push(action);
      });

    if (!actions.length) {
      throw new Error('没有可导入的 move 指令');
    }

    const durationMs = clamp(
      payload.motionDurationMs ?? (Number(payload.durationMs) - motionStartTime),
      500,
      30000,
      Math.max(...commands.map((command) => command.time + command.moveMs), 500)
    );

    return createPreset({
      id: uid('preset'),
      name: String(payload.name || '导入动作').slice(0, 48),
      durationMs,
      neutral: centers.pitch,
      armBaselineVersion: ARM_BASELINE_VERSION,
      centers,
      actions,
      expression: {
        mediaId: sequenceExpression?.mediaId || '',
        offsetMs: sequenceExpression?.offsetMs ?? (
          sequenceExpression ? Number(sequenceExpression.time || 0) - motionStartTime : 0
        ),
        durationMs: sequenceExpression?.durationMs ?? payload.motionDurationMs ?? payload.durationMs,
        loop: sequenceExpression?.loop !== false,
      },
      builtin: false,
      temporary: true,
      stashed: true,
      updatedAt: new Date().toISOString(),
    });
  }

  normalizeImportedCommand(command, index, options = {}) {
    const axis = this.fromPublicAxis(command?.axis);
    if (!axis) {
      throw new Error(`commands[${index}].axis 无效`);
    }

    const rawAngle = clamp(command?.angle, 0, 359, DEFAULT_POSE[axis]);
    return {
      actionId: String(command?.actionId || ''),
      time: clamp(command?.time, 0, 30000, 0),
      axis,
      angle: options.legacyArmBaseline && ARM_AXES.has(axis) && command?.angle !== undefined
        ? shiftLegacyArmAngle(rawAngle)
        : rawAngle,
      moveMs: clamp(command?.moveMs, 50, 5000, 300),
      label: String(command?.label || '').slice(0, 48),
      phase: String(command?.phase || 'move'),
    };
  }

  findImportedReturnCommandIndex(command, commands, usedReturnIndexes, centers) {
    let index = -1;
    if (command.actionId) {
      index = commands.findIndex((item, itemIndex) => (
        !usedReturnIndexes.has(itemIndex)
        && item.phase === 'return'
        && item.actionId === command.actionId
        && item.axis === command.axis
        && item.time >= command.time + command.moveMs
      ));
      if (index >= 0) return index;
    }

    return commands.findIndex((item, itemIndex) => (
      !usedReturnIndexes.has(itemIndex)
      && item.phase === 'return'
      && item.axis === command.axis
      && item.time >= command.time + command.moveMs
      && Math.abs(item.angle - centers[command.axis]) <= 1
    ));
  }

  normalizeImportedPose(pose, options = {}) {
    const rawArmL = clamp(pose.armL ?? pose.arml, 0, 359, DEFAULT_POSE.arml);
    const rawArmR = clamp(pose.armR ?? pose.armr, 0, 359, DEFAULT_POSE.armr);
    return {
      pitch: clamp(pose.pitch, 0, 359, DEFAULT_POSE.pitch),
      yaw: clamp(pose.yaw, 0, 359, DEFAULT_POSE.yaw),
      arml: options.legacyArmBaseline && (pose.armL ?? pose.arml) !== undefined ? shiftLegacyArmAngle(rawArmL) : rawArmL,
      armr: options.legacyArmBaseline && (pose.armR ?? pose.armr) !== undefined ? shiftLegacyArmAngle(rawArmR) : rawArmR,
    };
  }

  getAxisLabel(axisKey) {
    return AXES.find((axis) => axis.key === axisKey)?.label || axisKey;
  }

  buildDollSerTimelineCommands(preset) {
    const commands = [];
    const centers = preset.centers;

    preset.actions.forEach((action) => {
      const axisInfo = DOLLSER_AXIS_FIELDS[action.axis];
      commands.push({
        atMs: action.startMs,
        label: action.label,
        actionId: action.id,
        phase: 'move',
        axis: action.axis,
        dollSerAxis: axisInfo.displayName,
        address: axisInfo.address,
        settingsAngleTag: axisInfo.angle,
        settingsTimeTag: axisInfo.time,
        value: action.angle,
        angle: action.angle,
        timeMs: action.moveMs,
      });

      if (action.returnToCenter) {
        const returnAngle = centers[action.axis];
        const returnTimeMs = this.getSafeMoveMs(action.axis, action.angle, returnAngle, action.returnMoveMs);
        commands.push({
          atMs: action.startMs + action.moveMs + action.holdMs,
          label: `${action.label} 回中位`,
          actionId: action.id,
          phase: 'return',
          axis: action.axis,
          dollSerAxis: axisInfo.displayName,
          address: axisInfo.address,
          settingsAngleTag: axisInfo.angle,
          settingsTimeTag: axisInfo.time,
          value: returnAngle,
          angle: returnAngle,
          timeMs: returnTimeMs,
        });
      }
    });

    return commands.sort((left, right) => left.atMs - right.atMs || left.address.localeCompare(right.address));
  }

  toSeniorPose(pose) {
    return {
      pitch: pose.pitch,
      yaw: pose.yaw,
      armL: pose.arml,
      armR: pose.armr,
    };
  }

  toPublicAxis(axisKey) {
    if (axisKey === 'arml') return 'armL';
    if (axisKey === 'armr') return 'armR';
    return axisKey;
  }

  fromPublicAxis(axisKey) {
    if (axisKey === 'armL') return 'arml';
    if (axisKey === 'armR') return 'armr';
    if (['pitch', 'yaw', 'arml', 'armr'].includes(axisKey)) return axisKey;
    return '';
  }

  buildSequence(preset) {
    const events = [];
    this.normalizePresetCenters(preset);
    this.applySafetyToPreset(preset);
    const centers = preset.centers;

    preset.actions.forEach((action) => {
      events.push({
        at: action.startMs,
        axis: action.axis,
        angle: action.angle,
        moveMs: action.moveMs,
        label: action.label,
      });

      if (action.returnToCenter) {
        events.push({
          at: action.startMs + action.moveMs + action.holdMs,
          axis: action.axis,
          angle: centers[action.axis],
          moveMs: this.getSafeMoveMs(action.axis, action.angle, centers[action.axis], action.returnMoveMs),
          label: `${action.label} \u56de\u4e2d\u4f4d`,
        });
      }
    });

    events.sort((left, right) => left.at - right.at);
    const grouped = [];
    if (!events.length || events[0].at > 0) {
      grouped.push({ at: 0, events: [] });
    }
    events.forEach((event) => {
      const group = grouped.find((item) => item.at === event.at);
      if (group) group.events.push(event);
      else grouped.push({ at: event.at, events: [event] });
    });

    let pose = { ...centers };
    const steps = [];
    grouped.forEach((group, index) => {
      const nextAt = grouped[index + 1]?.at ?? preset.durationMs;
      const times = { pitch: 50, yaw: 50, arml: 50, armr: 50 };
      const activeAxes = new Set();
      const labels = [];

      group.events.forEach((event) => {
        pose = { ...pose, [event.axis]: event.angle };
        times[event.axis] = event.moveMs;
        activeAxes.add(event.axis);
        labels.push(event.label);
      });

      if (index === 0) {
        const gentleTimes = this.getGentlePoseTimes(pose);
        AXES.forEach((axis) => {
          if (!group.events.some((event) => event.axis === axis.key)) {
            times[axis.key] = gentleTimes[axis.key];
          }
          activeAxes.add(axis.key);
        });
      }

      const maxMove = Math.max(...Object.values(times));
      const holdMs = Math.max(0, nextAt - group.at - maxMove);
      const waitMs = Math.max(0, nextAt - group.at);

      steps.push({
        label: labels.join(' + ') || '\u8d77\u59cb\u4e2d\u4f4d',
        pose: { ...pose },
        times,
        activeAxes: [...activeAxes],
        holdMs,
        waitMs,
      });
    });

    return steps;
  }

  async playSelectedPreset() {
    clearTimeout(this.facePreviewTimer);
    const preset = this.getSelectedPreset();
    this.captureSequenceExpressionForm(preset);
    const mediaDurationMs = await this.readExpressionMediaDurationMs(preset.expression.mediaId);
    if (mediaDurationMs > 0) preset.expression.durationMs = mediaDurationMs;
    const timing = this.getSequencePlaybackTiming(preset);
    const playbackPreset = {
      ...preset,
      durationMs: timing.totalDurationMs,
      actions: preset.actions.map((action) => ({ ...action, startMs: action.startMs + timing.motionStartMs })),
    };
    const steps = this.buildSequence(playbackPreset);
    const faceCues = preset.expression.mediaId ? [{
      actionId: `sequence-expression-${preset.id}`,
      mediaId: preset.expression.mediaId,
      atMs: timing.expressionStartMs,
      durationMs: preset.expression.durationMs,
      loop: preset.expression.loop,
    }] : [];

    if (!steps.length) {
      this.toast('\u8fd9\u4e2a\u9884\u8bbe\u8fd8\u6ca1\u6709\u52a8\u4f5c\u5757');
      return;
    }

    try {
      await this.api('/api/face/stop', { method: 'POST', body: '{}' });
      await this.api('/api/sequence', {
        method: 'POST',
        body: JSON.stringify({ name: preset.name, steps, faceCues }),
      });
      this.records.unshift({ at: new Date().toISOString(), name: preset.name, steps: steps.length });
      this.records = this.records.slice(0, 8);
      this.saveRecords();
      this.toast(`\u5f00\u59cb\u64ad\u653e: ${preset.name}`);
      this.log(`\u64ad\u653e ${preset.name}: ${steps.length} \u6b65${faceCues.length ? `，${faceCues.length} 个表情提示` : ''}`);
    } catch (error) {
      this.toast(error.message);
    }
  }

  async stopSequence() {
    clearTimeout(this.facePreviewTimer);
    try {
      await this.api('/api/sequence/stop', { method: 'POST', body: '{}' });
      await this.api('/api/face/stop', { method: 'POST', body: '{}' });
      await this.sendNeutral();
      this.toast('\u5df2\u505c\u6b62\u5e76\u56de\u5230\u4e2d\u4f4d');
    } catch (error) {
      this.toast(error.message);
    }
  }


  async sendNeutral() {
    const preset = this.getSelectedPreset();
    this.normalizePresetCenters(preset);
    await this.sendPose(preset.centers, this.getGentlePoseTimes(preset.centers), '\u56de\u5230\u4e2d\u4f4d');
  }

  async sendCurrentPose() {
    const action = this.getSelectedAction();
    if (!action) {
      await this.sendNeutral();
      return;
    }

    const preset = this.getSelectedPreset();
    this.normalizePresetCenters(preset);
    this.enforceActionSafety(action, { silent: true });
    await this.sendPose(
      { ...this.currentPose, [action.axis]: action.angle },
      { ...this.currentTimes, [action.axis]: action.moveMs },
      'Previewed selected action',
      [action.axis]
    );
  }

  getSafeMoveMs(axisKey, fromAngle, toAngle, fallbackMs = DEFAULT_RETURN_MS) {
    const maxVelocity = Math.max(1, Number(this.safety.maxAngularVelocity) || DEFAULT_SAFETY.maxAngularVelocity);
    const delta = Math.abs(clamp(toAngle, 0, 359, 180) - clamp(fromAngle, 0, 359, 180));
    const safeMs = Math.ceil((delta / maxVelocity) * 1000);
    return clamp(Math.max(fallbackMs, safeMs), 50, 5000, DEFAULT_RETURN_MS);
  }

  getGentlePoseTimes(targetPose) {
    return AXES.reduce((times, axis) => {
      times[axis.key] = this.getSafeMoveMs(
        axis.key,
        this.currentPose[axis.key],
        targetPose[axis.key],
        this.neutralReturnMs
      );
      return times;
    }, {});
  }

  async sendPose(pose, times, summary, axes = null) {
    try {
      const payload = await this.api('/api/pose', {
        method: 'POST',
        body: JSON.stringify({ pose, times, summary, axes }),
      });
      this.currentPose = payload.current.pose;
      this.currentTimes = payload.current.times;
      this.toast(summary);
    } catch (error) {
      this.toast(error.message);
    }
  }

  async saveConfig() {
    const preset = this.getSelectedPreset();
    this.normalizePresetCenters(preset);
    const settings = {
      com: clamp(this.dom['config-com'].value, 0, 99, this.settings.com),
      pose: { ...preset.centers },
      times: { ...this.currentTimes },
    };

    try {
      const payload = await this.api('/api/config', {
        method: 'POST',
        body: JSON.stringify(settings),
      });
      this.settings = payload.config;
      this.toast('\u5df2\u4fdd\u5b58\u4e2d\u4f4d\u5230 Settings.xml');
    } catch (error) {
      this.toast(error.message);
    }
  }

  startPolling() {
    clearInterval(this.pollTimer);
    this.pollTimer = setInterval(async () => {
      try {
        const payload = await this.api('/api/sequence/status');
        this.currentPose = payload.current.pose;
        this.currentTimes = payload.current.times;
        this.updateSequenceStatus(payload.sequence, payload.lastCommand);
      } catch (error) {
        this.dom['connection-badge'].textContent = '连接失败';
        this.dom['connection-badge'].className = 'badge';
      }
    }, 1000);
  }

  updateSequenceStatus(sequence, lastCommand) {
    this.sequenceRunning = Boolean(sequence?.running);
    this.dom['sequence-badge'].textContent = this.sequenceRunning
      ? `${sequence.name} ${sequence.currentStep}/${sequence.totalSteps}`
      : '空闲';
    this.dom['sequence-badge'].className = this.sequenceRunning ? 'badge run' : 'badge';

    const poseText = AXES.map((axis) => `${axis.label}:${this.currentPose[axis.key]}`).join(' ');
    const recordText = this.records
      .map((record) => `${new Date(record.at).toLocaleTimeString()} ${record.name} (${record.steps}步)`)
      .join('\n');
    this.dom['log'].textContent = [
      `当前姿态  ${poseText}`,
      `最后指令  ${lastCommand?.summary || '--'}`,
      recordText ? `最近播放\n${recordText}` : '最近播放  --',
    ].join('\n');
  }

  restoreRecords() {
    try {
      const value = JSON.parse(localStorage.getItem(LOCAL_RECORD_KEY) || '[]');
      return Array.isArray(value) ? value.slice(0, 8) : [];
    } catch {
      return [];
    }
  }

  restoreTempPresets() {
    try {
      const value = JSON.parse(localStorage.getItem(LOCAL_TEMP_PRESET_KEY) || '[]');
      return Array.isArray(value) ? value.map((preset) => createPreset({ ...preset, temporary: true, stashed: Boolean(preset.stashed) })) : [];
    } catch {
      return [];
    }
  }

  restoreSafetySettings() {
    try {
      const saved = JSON.parse(localStorage.getItem(LOCAL_SAFETY_KEY) || '{}');
      return this.normalizeSafetySettings(saved);
    } catch {
      return this.normalizeSafetySettings(DEFAULT_SAFETY);
    }
  }

  restoreNeutralReturnMs() {
    return clamp(localStorage.getItem(LOCAL_NEUTRAL_RETURN_KEY), 50, 5000, DEFAULT_NEUTRAL_RETURN_MS);
  }

  saveTempPresets() {
    localStorage.setItem(LOCAL_TEMP_PRESET_KEY, JSON.stringify(this.tempPresets));
  }

  normalizeSafetySettings(settings = {}) {
    const isLegacyArmBaseline = Number(settings.armBaselineVersion || 1) < ARM_BASELINE_VERSION;
    const merged = clone(DEFAULT_SAFETY);
    merged.armBaselineVersion = ARM_BASELINE_VERSION;
    merged.maxAngularVelocity = clamp(settings.maxAngularVelocity, 1, 720, DEFAULT_SAFETY.maxAngularVelocity);
    AXES.forEach((axis) => {
      const current = settings.axes?.[axis.key] || {};
      const fallback = DEFAULT_SAFETY.axes[axis.key];
      let center = clamp(current.center, 0, 359, fallback.center);

      if (isLegacyArmBaseline && ARM_AXES.has(axis.key)) {
        if (current.center !== undefined) center = shiftLegacyArmAngle(center);
      }

      const hard = getAxisHardBounds(axis.key);
      center = clamp(center, hard.min, hard.max, fallback.center);

      const direction = normalizeDirection(current.direction, fallback.direction);
      let forwardRange = clampRange(current.forwardRange, fallback.forwardRange);
      let backwardRange = clampRange(current.backwardRange, fallback.backwardRange);

      if (current.forwardRange === undefined && current.backwardRange === undefined) {
        let min = clamp(current.min, 0, 359, fallback.min);
        let max = clamp(current.max, 0, 359, fallback.max);
        if (isLegacyArmBaseline && ARM_AXES.has(axis.key)) {
          if (current.min !== undefined) min = shiftLegacyArmAngle(min);
          if (current.max !== undefined) max = shiftLegacyArmAngle(max);
        }

        const safeMin = Math.max(hard.min, Math.min(min, max));
        const safeMax = Math.min(hard.max, Math.max(min, max));
        if (direction > 0) {
          forwardRange = Math.max(0, safeMax - center);
          backwardRange = Math.max(0, center - safeMin);
        } else {
          forwardRange = Math.max(0, center - safeMin);
          backwardRange = Math.max(0, safeMax - center);
        }
      }

      const derived = deriveAxisLimits(axis.key, center, direction, forwardRange, backwardRange);
      merged.axes[axis.key] = {
        center,
        direction,
        forwardRange,
        backwardRange,
        min: derived.min,
        max: derived.max,
      };
    });
    return merged;
  }

  saveSafetySettings(options = {}) {
    localStorage.setItem(LOCAL_SAFETY_KEY, JSON.stringify(this.safety));
    if (options.remote === false) return;

    this.api('/api/safety', {
      method: 'POST',
      body: JSON.stringify(this.safety),
    }).catch((error) => {
      this.log(`\u4fdd\u5b58\u5b89\u5168\u8bbe\u7f6e\u5931\u8d25: ${error.message}`);
    });
  }

  saveRecords() {
    localStorage.setItem(LOCAL_RECORD_KEY, JSON.stringify(this.records));
  }

  log(message) {
    this.dom['log'].textContent = `${new Date().toLocaleTimeString()} ${message}\n${this.dom['log'].textContent}`;
  }

  toast(message) {
    clearTimeout(this.toastTimer);
    this.dom['toast'].textContent = message;
    this.dom['toast'].classList.add('show');
    this.toastTimer = setTimeout(() => {
      this.dom['toast'].classList.remove('show');
    }, 2200);
  }

  escape(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  slugifyFileName(value) {
    const cleaned = String(value || 'motion-preset')
      .trim()
      .replace(/[\\/:*?"<>|]+/g, '-')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-+|-+$/g, '');
    return cleaned || 'motion-preset';
  }
}

new Workbench();
