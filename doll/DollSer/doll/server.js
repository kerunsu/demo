const express = require('express');
const { Client } = require('node-osc');
const fs = require('fs');
const path = require('path');

const WEB_PORT = Number(process.env.DOLL_WEB_PORT || 3000);
const OSC_HOST = process.env.DOLL_OSC_HOST || '127.0.0.1';
const OSC_PORT = Number(process.env.DOLL_OSC_PORT || 12000);
const SETTINGS_XML_PATH = path.resolve(__dirname, '..', 'bin', 'data', 'Settings.xml');
const DATA_DIR = process.env.DOLL_DATA_DIR
  ? path.resolve(process.env.DOLL_DATA_DIR)
  : path.join(__dirname, 'data');
const PRESETS_JSON_PATH = path.join(DATA_DIR, 'motion-presets.json');
const SAFETY_JSON_PATH = path.join(DATA_DIR, 'workbench-safety.json');
const PUBLIC_DIR = path.join(__dirname, 'public');
const FACE_MEDIA_DIR = path.join(__dirname, 'face-media');
const EXPRESSIONS_DIR = path.join(__dirname, 'expressions');
const IDLE_EXPRESSIONS_DIR = path.join(EXPRESSIONS_DIR, 'idle');
const FACE_MEDIA_ROUTE = '/face-media';
const EXPRESSIONS_ROUTE = '/expressions';
const FACE_VIDEO_EXTENSIONS = new Set(['.mp4', '.webm', '.ogg', '.mov', '.m4v']);
const FACE_IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.webp', '.gif']);
const SUPPORTED_FACE_EXTENSIONS = new Set([...FACE_VIDEO_EXTENSIONS, ...FACE_IMAGE_EXTENSIONS]);

const AXES = ['pitch', 'yaw', 'arml', 'armr'];
const ARM_AXES = new Set(['arml', 'armr']);
const ARM_BASELINE_VERSION = 2;
const ARM_BASELINE_SHIFT_DEG = 90;
const ARM_CENTER = 270;
const ARM_SAFE_MIN = 0;
const ARM_SAFE_MAX = 359;
const AXIS_TAGS = {
  pitch: { angle: 'Pitch', time: 'Pitch_Time' },
  yaw: { angle: 'Yaw', time: 'Yaw_Time' },
  arml: { angle: 'ArmL', time: 'ArmL_Time' },
  armr: { angle: 'ArmR', time: 'ArmR_Time' },
};

const DEFAULT_SETTINGS = {
  com: 7,
  pose: {
    pitch: 200,
    yaw: 160,
    arml: 320,
    armr: 50,
  },
  times: {
    pitch: 200,
    yaw: 200,
    arml: 200,
    armr: 200,
  },
};

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

const app = express();
const oscClient = new Client(OSC_HOST, OSC_PORT);

let currentPose = { ...DEFAULT_SETTINGS.pose };
let currentTimes = { ...DEFAULT_SETTINGS.times };
let activeSequence = null;
let nextSequenceId = 1;
let activeFaceCueToken = '';
const faceEventClients = new Set();
let faceState = {
  mediaId: '',
  loop: true,
  clipStartSec: 0,
  clipEndSec: 0,
  updatedAt: new Date().toISOString(),
};
let lastCommand = {
  type: 'boot',
  at: new Date().toISOString(),
  summary: 'Server started',
};

ensureDirectory(FACE_MEDIA_DIR);
ensureDirectory(EXPRESSIONS_DIR);
ensureDirectory(IDLE_EXPRESSIONS_DIR);
ensureDirectory(DATA_DIR);

app.use(express.json({ limit: '1mb' }));
app.use(express.static(PUBLIC_DIR));
app.use(FACE_MEDIA_ROUTE, express.static(FACE_MEDIA_DIR, {
  fallthrough: false,
  etag: true,
  immutable: false,
  maxAge: '1h',
}));
app.use(EXPRESSIONS_ROUTE, express.static(EXPRESSIONS_DIR, {
  fallthrough: false,
  etag: true,
  immutable: false,
  maxAge: '1h',
}));

function ensureDirectory(directoryPath) {
  fs.mkdirSync(directoryPath, { recursive: true });
}

function clampAngle(value, fallback = 180) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.min(359, Math.max(0, Math.round(parsed)));
}

function shiftLegacyArmAngle(value) {
  return Math.min(ARM_SAFE_MAX, Math.max(0, Math.round(Number(value) + ARM_BASELINE_SHIFT_DEG)));
}

function clampTime(value, fallback = 200) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.min(5000, Math.max(50, Math.round(parsed)));
}

function clampPause(value, fallback = 200) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.min(10000, Math.max(0, Math.round(parsed)));
}

function clampExpressionDuration(value, fallback = 1000) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(30000, Math.max(100, Math.round(parsed)));
}

function clampExpressionOffset(value, fallback = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(30000, Math.max(-30000, Math.round(parsed)));
}

function clampSequenceWait(value, fallback = 200) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.min(30000, Math.max(0, Math.round(parsed)));
}

function clampAngularVelocity(value, fallback = DEFAULT_SAFETY.maxAngularVelocity) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.min(720, Math.max(1, Math.round(parsed)));
}

function clampRange(value, fallback = 30) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.min(180, Math.max(0, Math.round(parsed)));
}

function normalizeDirection(value, fallback = 1) {
  return Number(value) < 0 ? -1 : (Number(fallback) < 0 ? -1 : 1);
}

function getAxisHardBounds(axis) {
  if (ARM_AXES.has(axis)) {
    return { min: ARM_SAFE_MIN, max: ARM_SAFE_MAX };
  }

  return { min: 0, max: 359 };
}

function deriveAxisLimits(axis, center, direction, forwardRange, backwardRange) {
  const hard = getAxisHardBounds(axis);
  const forwardAngle = center + direction * forwardRange;
  const backwardAngle = center - direction * backwardRange;
  const min = Math.max(hard.min, Math.min(center, forwardAngle, backwardAngle));
  const max = Math.min(hard.max, Math.max(center, forwardAngle, backwardAngle));

  return { min, max };
}

function clampFaceLoop(value, fallback = true) {
  if (value === undefined || value === null) {
    return fallback;
  }

  return value !== false;
}

function clampFaceSeconds(value, fallback = 0) {
  if (value === '' || value === null || value === undefined) {
    return fallback;
  }

  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.min(24 * 60 * 60, Math.max(0, Math.round(parsed * 10) / 10));
}

function normalizeFaceClip(clipStartSec, clipEndSec) {
  const start = clampFaceSeconds(clipStartSec, 0);
  const end = clampFaceSeconds(clipEndSec, 0);

  return {
    clipStartSec: start,
    clipEndSec: end > start ? end : 0,
  };
}

function readTag(xml, tagName, fallback) {
  const pattern = new RegExp(`<${tagName}>([\\s\\S]*?)<\\/${tagName}>`, 'i');
  const match = xml.match(pattern);
  if (!match) {
    return fallback;
  }

  return match[1].trim();
}

function normalizeSettings(input) {
  const base = input || {};
  const pose = {};
  const times = {};

  AXES.forEach((axis) => {
    pose[axis] = clampAngle(base.pose?.[axis], DEFAULT_SETTINGS.pose[axis]);
    times[axis] = clampTime(base.times?.[axis], DEFAULT_SETTINGS.times[axis]);
  });

  const comParsed = Number(base.com);
  const com = Number.isFinite(comParsed) ? Math.max(0, Math.round(comParsed)) : DEFAULT_SETTINGS.com;

  return { com, pose, times };
}

function clampTimelineMs(value, fallback = 2400) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.min(30000, Math.max(500, Math.round(parsed)));
}

function clampStartMs(value, fallback = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }

  return Math.min(30000, Math.max(0, Math.round(parsed)));
}

function sanitizePresetText(value, fallback, maxLength = 120) {
  const text = String(value || '').trim();
  return (text || fallback).slice(0, maxLength);
}

function normalizePresetAction(action, index = 0, options = {}) {
  const axis = AXES.includes(action?.axis) ? action.axis : 'pitch';
  const rawAngle = clampAngle(action?.angle, DEFAULT_SETTINGS.pose[axis]);
  const angle = options.legacyArmBaseline && ARM_AXES.has(axis) && action?.angle !== undefined
    ? shiftLegacyArmAngle(rawAngle)
    : rawAngle;
  return {
    id: sanitizePresetText(action?.id, `action-${Date.now()}-${index}`, 80),
    axis,
    label: sanitizePresetText(action?.label, `Action ${index + 1}`, 48),
    startMs: clampStartMs(action?.startMs, 0),
    angle,
    moveMs: clampTime(action?.moveMs, 300),
    requestedMoveMs: clampTime(action?.requestedMoveMs ?? action?.moveMs, 300),
    holdMs: clampPause(action?.holdMs, 160),
    returnToCenter: action?.returnToCenter !== false,
    returnMoveMs: clampTime(action?.returnMoveMs, 360),
  };
}

function normalizePresetExpression(preset = {}) {
  const legacyAction = Array.isArray(preset.actions)
    ? preset.actions.find((action) => action?.expressionId)
    : null;
  const source = preset.expression || (legacyAction ? {
    mediaId: legacyAction.expressionId,
    offsetMs: Number(legacyAction.expressionStartMs ?? legacyAction.startMs ?? 0) - Number(legacyAction.startMs || 0),
    durationMs: legacyAction.expressionDurationMs,
    loop: legacyAction.expressionLoop,
  } : {});

  return {
    mediaId: sanitizePresetText(source.mediaId, '', 160),
    offsetMs: clampExpressionOffset(source.offsetMs, 0),
    durationMs: clampExpressionDuration(source.durationMs, preset.durationMs || 1000),
    loop: source.loop !== false,
  };
}

function normalizeMotionPreset(preset, index = 0) {
  const legacyArmBaseline = Number(preset?.armBaselineVersion || 1) < ARM_BASELINE_VERSION;
  const centers = {};
  const neutralFallback = preset?.centers?.pitch ?? preset?.centers?.yaw ?? DEFAULT_SETTINGS.pose.pitch;
  const neutral = clampAngle(preset?.neutral, neutralFallback);
  AXES.forEach((axis) => {
    const rawCenter = clampAngle(preset?.centers?.[axis], DEFAULT_SETTINGS.pose[axis] ?? neutral);
    centers[axis] = legacyArmBaseline && ARM_AXES.has(axis) && preset?.centers?.[axis] !== undefined
      ? shiftLegacyArmAngle(rawCenter)
      : rawCenter;
  });

  const actions = Array.isArray(preset?.actions)
    ? preset.actions.map((action, actionIndex) => normalizePresetAction(action, actionIndex, { legacyArmBaseline }))
    : [];

  return {
    id: sanitizePresetText(preset?.id, `preset-${Date.now()}-${index}`, 80),
    name: sanitizePresetText(preset?.name, `Preset ${index + 1}`, 48),
    notes: sanitizePresetText(preset?.notes, '', 400),
    durationMs: clampTimelineMs(preset?.durationMs, 2400),
    neutral,
    armBaselineVersion: ARM_BASELINE_VERSION,
    centers,
    actions,
    expression: normalizePresetExpression(preset),
    updatedAt: preset?.updatedAt || new Date().toISOString(),
  };
}

function readMotionPresets() {
  if (!fs.existsSync(PRESETS_JSON_PATH)) {
    return [];
  }

  const raw = fs.readFileSync(PRESETS_JSON_PATH, 'utf8');
  const parsed = JSON.parse(raw || '[]');
  if (!Array.isArray(parsed)) {
    return [];
  }

  return parsed.map((preset, index) => normalizeMotionPreset(preset, index));
}

function writeMotionPresets(presets) {
  const normalized = Array.isArray(presets)
    ? presets.map((preset, index) => normalizeMotionPreset(preset, index))
    : [];

  fs.writeFileSync(PRESETS_JSON_PATH, JSON.stringify(normalized, null, 2), 'utf8');
  return normalized;
}

function normalizeSafetySettings(settings = {}) {
  const isLegacyArmBaseline = Number(settings.armBaselineVersion || 1) < ARM_BASELINE_VERSION;
  const normalized = {
    armBaselineVersion: ARM_BASELINE_VERSION,
    maxAngularVelocity: clampAngularVelocity(settings.maxAngularVelocity, DEFAULT_SAFETY.maxAngularVelocity),
    axes: {},
    updatedAt: settings.updatedAt || new Date().toISOString(),
  };

  AXES.forEach((axis) => {
    const fallback = DEFAULT_SAFETY.axes[axis];
    const source = settings.axes?.[axis] || {};
    let center = clampAngle(source.center, fallback.center);

    if (isLegacyArmBaseline && ARM_AXES.has(axis)) {
      if (source.center !== undefined) center = shiftLegacyArmAngle(center);
    }

    const hard = getAxisHardBounds(axis);
    center = Math.min(hard.max, Math.max(hard.min, center));

    let direction = normalizeDirection(source.direction, fallback.direction);
    let forwardRange = clampRange(source.forwardRange, fallback.forwardRange);
    let backwardRange = clampRange(source.backwardRange, fallback.backwardRange);

    if (source.forwardRange === undefined && source.backwardRange === undefined) {
      let min = clampAngle(source.min, fallback.min);
      let max = clampAngle(source.max, fallback.max);
      if (isLegacyArmBaseline && ARM_AXES.has(axis)) {
        if (source.min !== undefined) min = shiftLegacyArmAngle(min);
        if (source.max !== undefined) max = shiftLegacyArmAngle(max);
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

    const limits = deriveAxisLimits(axis, center, direction, forwardRange, backwardRange);

    normalized.axes[axis] = {
      center,
      direction,
      forwardRange,
      backwardRange,
      min: limits.min,
      max: limits.max,
    };
  });

  return normalized;
}

function readSafetySettings() {
  if (!fs.existsSync(SAFETY_JSON_PATH)) {
    return normalizeSafetySettings(DEFAULT_SAFETY);
  }

  const raw = fs.readFileSync(SAFETY_JSON_PATH, 'utf8');
  return normalizeSafetySettings(JSON.parse(raw || '{}'));
}

function writeSafetySettings(settings) {
  const normalized = normalizeSafetySettings({
    ...settings,
    updatedAt: new Date().toISOString(),
  });
  fs.writeFileSync(SAFETY_JSON_PATH, JSON.stringify(normalized, null, 2), 'utf8');
  return normalized;
}

function upsertMotionPreset(input) {
  const presets = readMotionPresets();
  const normalized = normalizeMotionPreset({
    ...input,
    id: input?.id || `preset-${Date.now()}`,
    updatedAt: new Date().toISOString(),
  });
  const index = presets.findIndex((preset) => preset.id === normalized.id);

  if (index >= 0) {
    presets[index] = normalized;
  } else {
    presets.unshift(normalized);
  }

  return {
    preset: normalized,
    presets: writeMotionPresets(presets),
  };
}

function readSettingsXml() {
  if (!fs.existsSync(SETTINGS_XML_PATH)) {
    return normalizeSettings(DEFAULT_SETTINGS);
  }

  const xml = fs.readFileSync(SETTINGS_XML_PATH, 'utf8');
  const pose = {};
  const times = {};

  AXES.forEach((axis) => {
    const tags = AXIS_TAGS[axis];
    pose[axis] = clampAngle(readTag(xml, tags.angle, DEFAULT_SETTINGS.pose[axis]), DEFAULT_SETTINGS.pose[axis]);
    times[axis] = clampTime(readTag(xml, tags.time, DEFAULT_SETTINGS.times[axis]), DEFAULT_SETTINGS.times[axis]);
  });

  const com = Math.max(0, Math.round(Number(readTag(xml, 'COM', DEFAULT_SETTINGS.com)) || DEFAULT_SETTINGS.com));
  return { com, pose, times };
}

function writeSettingsXml(settings) {
  const normalized = normalizeSettings(settings);
  const xml = [
    '<?xml version="1.0"?>',
    '<EIGui>',
    `\t<COM>${normalized.com}</COM>`,
    `\t<Pitch>${normalized.pose.pitch}</Pitch>`,
    `\t<Pitch_Time>${normalized.times.pitch}</Pitch_Time>`,
    `\t<Yaw>${normalized.pose.yaw}</Yaw>`,
    `\t<Yaw_Time>${normalized.times.yaw}</Yaw_Time>`,
    `\t<ArmL>${normalized.pose.arml}</ArmL>`,
    `\t<ArmL_Time>${normalized.times.arml}</ArmL_Time>`,
    `\t<ArmR>${normalized.pose.armr}</ArmR>`,
    `\t<ArmR_Time>${normalized.times.armr}</ArmR_Time>`,
    '</EIGui>',
    '',
  ].join('\n');

  fs.writeFileSync(SETTINGS_XML_PATH, xml, 'utf8');
  return normalized;
}

function updateCurrentState(pose, times) {
  currentPose = {
    pitch: clampAngle(pose?.pitch, currentPose.pitch),
    yaw: clampAngle(pose?.yaw, currentPose.yaw),
    arml: clampAngle(pose?.arml, currentPose.arml),
    armr: clampAngle(pose?.armr, currentPose.armr),
  };

  currentTimes = {
    pitch: clampTime(times?.pitch, currentTimes.pitch),
    yaw: clampTime(times?.yaw, currentTimes.yaw),
    arml: clampTime(times?.arml, currentTimes.arml),
    armr: clampTime(times?.armr, currentTimes.armr),
  };
}

function sendAxis(axis, value, time) {
  oscClient.send(`/${axis}`, clampAngle(value, currentPose[axis]), clampTime(time, currentTimes[axis]));
}

function sendPose(pose, options = {}) {
  const normalizedPose = {
    pitch: clampAngle(pose?.pitch, currentPose.pitch),
    yaw: clampAngle(pose?.yaw, currentPose.yaw),
    arml: clampAngle(pose?.arml, currentPose.arml),
    armr: clampAngle(pose?.armr, currentPose.armr),
  };

  const normalizedTimes = {
    pitch: clampTime(options.times?.pitch ?? options.time, currentTimes.pitch),
    yaw: clampTime(options.times?.yaw ?? options.time, currentTimes.yaw),
    arml: clampTime(options.times?.arml ?? options.time, currentTimes.arml),
    armr: clampTime(options.times?.armr ?? options.time, currentTimes.armr),
  };

  const axesToSend = Array.isArray(options.axes) && options.axes.length
    ? options.axes.filter((axis) => AXES.includes(axis))
    : AXES;

  axesToSend.forEach((axis) => {
    sendAxis(axis, normalizedPose[axis], normalizedTimes[axis]);
  });

  updateCurrentState(normalizedPose, normalizedTimes);
  lastCommand = {
    type: options.commandType || 'pose',
    at: new Date().toISOString(),
    summary: options.summary || `Pose P${normalizedPose.pitch} Y${normalizedPose.yaw} L${normalizedPose.arml} R${normalizedPose.armr}`,
  };

  return { pose: normalizedPose, times: normalizedTimes, axes: axesToSend };
}

function getSequenceStatus() {
  if (!activeSequence) {
    return { running: false };
  }

  return {
    running: true,
    id: activeSequence.id,
    name: activeSequence.name,
    startedAt: activeSequence.startedAt,
    currentStep: activeSequence.currentStep,
    totalSteps: activeSequence.totalSteps,
    currentLabel: activeSequence.currentLabel,
  };
}

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function sanitizeFaceFilename(fileName) {
  const normalized = String(fileName || '')
    .replaceAll('\\', '/')
    .split('/')
    .pop()
    .trim();

  const cleaned = normalized.replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/-+/g, '-');
  return cleaned.replace(/^-+|-+$/g, '') || 'expression.mp4';
}

function validateFaceExtension(fileName) {
  const extension = path.extname(fileName).toLowerCase();
  if (!SUPPORTED_FACE_EXTENSIONS.has(extension)) {
    throw new Error(`Unsupported expression media type: ${extension || 'unknown'}`);
  }

  return extension;
}

function normalizeFaceMediaId(mediaId) {
  const normalized = String(mediaId || '').replaceAll('\\', '/').trim();
  if (normalized.startsWith('idle/')) {
    const idleFileName = path.basename(normalized.slice('idle/'.length));
    return idleFileName ? `idle/${idleFileName}` : '';
  }
  return path.basename(normalized);
}

function getFaceMediaFilePath(mediaId) {
  const safeId = normalizeFaceMediaId(mediaId);
  if (safeId.startsWith('idle/')) {
    return path.join(IDLE_EXPRESSIONS_DIR, path.basename(safeId));
  }
  const expressionPath = path.join(EXPRESSIONS_DIR, safeId);
  if (fs.existsSync(expressionPath)) return expressionPath;
  return path.join(FACE_MEDIA_DIR, safeId);
}

function buildFaceMediaRecord(mediaId) {
  const safeId = normalizeFaceMediaId(mediaId);
  const filePath = getFaceMediaFilePath(safeId);
  if (!fs.existsSync(filePath)) {
    return null;
  }

  const stats = fs.statSync(filePath);
  if (!stats.isFile()) {
    return null;
  }

  const isIdle = path.dirname(filePath) === IDLE_EXPRESSIONS_DIR;
  const isExpression = path.dirname(filePath) === EXPRESSIONS_DIR || isIdle;
  return {
    id: safeId,
    fileName: path.basename(safeId),
    url: `${isExpression ? EXPRESSIONS_ROUTE : FACE_MEDIA_ROUTE}/${isIdle ? 'idle/' : ''}${encodeURIComponent(path.basename(safeId))}`,
    size: stats.size,
    updatedAt: stats.mtime.toISOString(),
    extension: path.extname(safeId).toLowerCase(),
    mediaType: FACE_IMAGE_EXTENSIONS.has(path.extname(safeId).toLowerCase()) ? 'image' : 'video',
    category: isIdle ? 'idle' : 'action',
  };
}

function listFaceMedia() {
  ensureDirectory(FACE_MEDIA_DIR);
  ensureDirectory(EXPRESSIONS_DIR);
  return [...new Set([...fs.readdirSync(EXPRESSIONS_DIR), ...fs.readdirSync(FACE_MEDIA_DIR)])]
    .filter((fileName) => SUPPORTED_FACE_EXTENSIONS.has(path.extname(fileName).toLowerCase()))
    .map((fileName) => buildFaceMediaRecord(fileName))
    .filter(Boolean)
    .sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime());
}

function listIdleFaceMedia() {
  ensureDirectory(IDLE_EXPRESSIONS_DIR);
  return fs.readdirSync(IDLE_EXPRESSIONS_DIR)
    .filter((fileName) => SUPPORTED_FACE_EXTENSIONS.has(path.extname(fileName).toLowerCase()))
    .map((fileName) => buildFaceMediaRecord(`idle/${fileName}`))
    .filter(Boolean)
    .sort((left, right) => left.fileName.localeCompare(right.fileName, 'zh-CN'));
}

function getCurrentFaceMedia() {
  if (!faceState.mediaId) {
    return null;
  }

  return buildFaceMediaRecord(faceState.mediaId);
}

function getFacePayload() {
  const library = listFaceMedia();
  const idleLibrary = listIdleFaceMedia();
  const idleMedia = idleLibrary[0] || null;
  let currentMedia = getCurrentFaceMedia();

  if (faceState.mediaId && !currentMedia) {
    faceState = {
      ...faceState,
      mediaId: '',
      updatedAt: new Date().toISOString(),
    };
    currentMedia = null;
  }

  const useIdle = !currentMedia && idleMedia;
  const effectiveMedia = currentMedia || useIdle || null;
  const mode = currentMedia ? 'active' : (useIdle ? 'idle' : 'empty');

  return {
    current: effectiveMedia,
    state: {
      mediaId: effectiveMedia?.id || '',
      mode,
      loop: mode === 'idle' ? true : clampFaceLoop(faceState.loop, true),
      clipStartSec: mode === 'idle' ? 0 : clampFaceSeconds(faceState.clipStartSec, 0),
      clipEndSec: mode === 'idle' ? 0 : clampFaceSeconds(faceState.clipEndSec, 0),
      updatedAt: mode === 'idle' ? idleMedia.updatedAt : faceState.updatedAt,
    },
    library,
    idle: {
      current: idleMedia,
      library: idleLibrary,
      directory: 'doll/expressions/idle',
    },
    facePageUrl: '/face.html',
  };
}

function setFaceState(nextState) {
  const clip = normalizeFaceClip(nextState.clipStartSec, nextState.clipEndSec);
  faceState = {
    mediaId: nextState.mediaId || '',
    loop: clampFaceLoop(nextState.loop, true),
    clipStartSec: clip.clipStartSec,
    clipEndSec: clip.clipEndSec,
    updatedAt: new Date().toISOString(),
  };

  const payload = getFacePayload();
  broadcastFaceState(payload);
  return payload;
}

function writeFaceEvent(response, payload) {
  response.write(`event: face\ndata: ${JSON.stringify({ ok: true, face: payload })}\n\n`);
  response.flush?.();
}

function broadcastFaceState(payload = getFacePayload()) {
  faceEventClients.forEach((response) => {
    try {
      writeFaceEvent(response, payload);
    } catch (error) {
      faceEventClients.delete(response);
    }
  });
}

function clearSequenceFaceCues(sequence, options = {}) {
  (sequence?.faceTimers || []).forEach((timer) => clearTimeout(timer));
  if (options.stopFace !== false && activeFaceCueToken) {
    activeFaceCueToken = '';
    setFaceState({ mediaId: '', loop: true, clipStartSec: 0, clipEndSec: 0 });
  }
}

function scheduleSequenceFaceCues(sequence) {
  sequence.faceTimers = [];
  sequence.faceCues.forEach((cue, index) => {
    const token = `${sequence.id}:${index}:${cue.mediaId}`;
    const startTimer = setTimeout(() => {
      if (!activeSequence || activeSequence.id !== sequence.id) return;
      activeFaceCueToken = token;
      setFaceState({ mediaId: cue.mediaId, loop: cue.loop, clipStartSec: 0, clipEndSec: 0 });
    }, cue.atMs);
    const stopTimer = setTimeout(() => {
      if (activeFaceCueToken !== token) return;
      activeFaceCueToken = '';
      setFaceState({ mediaId: '', loop: true, clipStartSec: 0, clipEndSec: 0 });
    }, cue.atMs + cue.durationMs);
    sequence.faceTimers.push(startTimer, stopTimer);
  });
}

async function runSequence(sequenceId) {
  while (activeSequence && activeSequence.id === sequenceId && activeSequence.currentStep < activeSequence.steps.length) {
    const step = activeSequence.steps[activeSequence.currentStep];
    const moveMs = Math.max(...Object.values(step.times));
    const extraHoldMs = clampPause(step.holdMs, 0);
    const waitMs = step.waitMs === undefined
      ? moveMs + extraHoldMs
      : clampSequenceWait(step.waitMs, moveMs + extraHoldMs);

    activeSequence.currentLabel = step.label || `Step ${activeSequence.currentStep + 1}`;
    sendPose(step.pose, {
      times: step.times,
      axes: step.activeAxes,
      commandType: 'sequence-step',
      summary: `${activeSequence.name}: ${activeSequence.currentLabel}`,
    });

    activeSequence.currentStep += 1;
    // Wait for the move to finish before sending the next target, otherwise
    // longer durations get interrupted mid-way and look like reduced amplitude.
    await delay(waitMs);
  }

  if (activeSequence && activeSequence.id === sequenceId) {
    lastCommand = {
      type: 'sequence-complete',
      at: new Date().toISOString(),
      summary: `${activeSequence.name} finished`,
    };
    clearSequenceFaceCues(activeSequence);
    activeSequence = null;
    broadcastFaceState();
  }
}

function stopSequence(reason = 'Stopped') {
  if (!activeSequence) {
    return false;
  }

  clearSequenceFaceCues(activeSequence);
  lastCommand = {
    type: 'sequence-stop',
    at: new Date().toISOString(),
    summary: `${activeSequence.name} ${reason.toLowerCase()}`,
  };
  activeSequence = null;
  broadcastFaceState();
  return true;
}

function createSequencePayload(body) {
  const name = String(body?.name || 'Sequence').trim() || 'Sequence';
  const steps = Array.isArray(body?.steps) ? body.steps : [];
  if (!steps.length) {
    throw new Error('Sequence is empty.');
  }

  const normalizedSteps = steps.map((step, index) => {
    const pose = {
      pitch: clampAngle(step?.pose?.pitch, currentPose.pitch),
      yaw: clampAngle(step?.pose?.yaw, currentPose.yaw),
      arml: clampAngle(step?.pose?.arml, currentPose.arml),
      armr: clampAngle(step?.pose?.armr, currentPose.armr),
    };

    const times = {
      pitch: clampTime(step?.times?.pitch ?? step?.time, currentTimes.pitch),
      yaw: clampTime(step?.times?.yaw ?? step?.time, currentTimes.yaw),
      arml: clampTime(step?.times?.arml ?? step?.time, currentTimes.arml),
      armr: clampTime(step?.times?.armr ?? step?.time, currentTimes.armr),
    };

    const normalizedStep = {
      label: String(step?.label || `Step ${index + 1}`),
      holdMs: clampPause(step?.holdMs, 0),
      pose,
      times,
      activeAxes: Array.isArray(step?.activeAxes)
        ? step.activeAxes.filter((axis) => AXES.includes(axis))
        : AXES,
    };

    if (step?.waitMs !== undefined) {
      normalizedStep.waitMs = clampSequenceWait(step.waitMs, 0);
    }

    return normalizedStep;
  });

  const faceCues = (Array.isArray(body?.faceCues) ? body.faceCues : [])
    .map((cue, index) => ({
      actionId: sanitizePresetText(cue?.actionId, `face-cue-${index + 1}`, 80),
      mediaId: path.basename(String(cue?.mediaId || '').trim()),
      atMs: clampStartMs(cue?.atMs, 0),
      durationMs: clampExpressionDuration(cue?.durationMs, 1000),
      loop: cue?.loop !== false,
    }))
    .filter((cue) => cue.mediaId && buildFaceMediaRecord(cue.mediaId));

  return { name, steps: normalizedSteps, faceCues };
}

app.get('/api/config', (req, res) => {
  const settings = readSettingsXml();
  updateCurrentState(settings.pose, settings.times);

  res.json({
    ok: true,
    settingsPath: SETTINGS_XML_PATH,
    osc: {
      host: OSC_HOST,
      port: OSC_PORT,
    },
    config: settings,
    current: {
      pose: currentPose,
      times: currentTimes,
    },
    sequence: getSequenceStatus(),
    lastCommand,
    face: getFacePayload(),
  });
});

app.get('/api/safety', (req, res) => {
  res.json({
    ok: true,
    safety: readSafetySettings(),
    safetyPath: SAFETY_JSON_PATH,
  });
});

app.post('/api/safety', (req, res) => {
  const saved = writeSafetySettings(req.body || {});
  res.json({
    ok: true,
    safety: saved,
    safetyPath: SAFETY_JSON_PATH,
  });
});

app.post('/api/config', (req, res) => {
  const settings = normalizeSettings(req.body);
  const saved = writeSettingsXml(settings);
  updateCurrentState(saved.pose, saved.times);

  lastCommand = {
    type: 'save-config',
    at: new Date().toISOString(),
    summary: 'Settings.xml saved',
  };

  res.json({
    ok: true,
    settingsPath: SETTINGS_XML_PATH,
    config: saved,
  });
});

app.post('/api/pose', (req, res) => {
  const result = sendPose(req.body?.pose, {
    time: req.body?.time,
    times: req.body?.times,
    axes: req.body?.axes,
    commandType: 'manual-pose',
    summary: req.body?.summary || 'Manual pose sent',
  });

  res.json({
    ok: true,
    current: result,
    sequence: getSequenceStatus(),
  });
});

app.post('/api/sequence', (req, res) => {
  const payload = createSequencePayload(req.body);
  stopSequence('Replaced');

  activeSequence = {
    id: nextSequenceId++,
    name: payload.name,
    steps: payload.steps,
    currentStep: 0,
    totalSteps: payload.steps.length,
    currentLabel: payload.steps[0]?.label || '',
    faceCues: payload.faceCues,
    faceTimers: [],
    startedAt: new Date().toISOString(),
  };
  activeFaceCueToken = '';
  setFaceState({ mediaId: '', loop: true, clipStartSec: 0, clipEndSec: 0 });

  scheduleSequenceFaceCues(activeSequence);

  runSequence(activeSequence.id).catch((error) => {
    console.error('Sequence failed:', error);
    if (activeSequence) clearSequenceFaceCues(activeSequence);
    lastCommand = {
      type: 'sequence-error',
      at: new Date().toISOString(),
      summary: `Sequence error: ${error.message}`,
    };
    activeSequence = null;
    broadcastFaceState();
  });

  res.json({
    ok: true,
    sequence: getSequenceStatus(),
    face: getFacePayload(),
  });
});

app.get('/api/sequence/status', (req, res) => {
  res.json({
    ok: true,
    sequence: getSequenceStatus(),
    current: {
      pose: currentPose,
      times: currentTimes,
    },
    lastCommand,
    face: getFacePayload(),
  });
});

app.post('/api/sequence/stop', (req, res) => {
  const stopped = stopSequence('Stopped');
  res.json({
    ok: true,
    stopped,
    sequence: getSequenceStatus(),
    face: getFacePayload(),
  });
});

app.get('/api/presets', (req, res) => {
  res.json({
    ok: true,
    presets: readMotionPresets(),
    presetsPath: PRESETS_JSON_PATH,
  });
});

app.post('/api/presets', (req, res) => {
  const result = upsertMotionPreset(req.body);

  lastCommand = {
    type: 'preset-save',
    at: new Date().toISOString(),
    summary: `Preset saved: ${result.preset.name}`,
  };

  res.json({
    ok: true,
    preset: result.preset,
    presets: result.presets,
    presetsPath: PRESETS_JSON_PATH,
  });
});

app.delete('/api/presets/:presetId', (req, res) => {
  const presetId = path.basename(String(req.params.presetId || '').trim());
  const presets = readMotionPresets();
  const nextPresets = presets.filter((preset) => preset.id !== presetId);

  if (nextPresets.length === presets.length) {
    throw new Error('Preset not found.');
  }

  writeMotionPresets(nextPresets);

  lastCommand = {
    type: 'preset-delete',
    at: new Date().toISOString(),
    summary: `Preset deleted: ${presetId}`,
  };

  res.json({
    ok: true,
    presets: nextPresets,
    presetsPath: PRESETS_JSON_PATH,
  });
});

app.get('/api/face/state', (req, res) => {
  res.json({
    ok: true,
    face: getFacePayload(),
  });
});

app.get('/api/face/events', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache, no-transform');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders?.();
  res.socket?.setNoDelay(true);

  faceEventClients.add(res);
  writeFaceEvent(res, getFacePayload());
  const heartbeat = setInterval(() => res.write(': keep-alive\n\n'), 15000);

  req.on('close', () => {
    clearInterval(heartbeat);
    faceEventClients.delete(res);
  });
});

app.get('/api/face/media', (req, res) => {
  res.json({
    ok: true,
    face: getFacePayload(),
  });
});

app.post('/api/face/play', (req, res) => {
  const mediaId = path.basename(String(req.body?.mediaId || '').trim());
  if (!mediaId) {
    throw new Error('Expression mediaId is required.');
  }

  const media = buildFaceMediaRecord(mediaId);
  if (!media) {
    throw new Error('Expression media not found.');
  }

  activeFaceCueToken = '';
  const face = setFaceState({
    mediaId: media.id,
    loop: req.body?.loop,
    clipStartSec: req.body?.clipStartSec,
    clipEndSec: req.body?.clipEndSec,
  });

  const clip = normalizeFaceClip(req.body?.clipStartSec, req.body?.clipEndSec);
  const clipSummary = clip.clipEndSec > clip.clipStartSec
    ? ` (${clip.clipStartSec}s-${clip.clipEndSec}s)`
    : (clip.clipStartSec > 0 ? ` (from ${clip.clipStartSec}s)` : '');

  lastCommand = {
    type: 'face-play',
    at: new Date().toISOString(),
    summary: `Face expression playing: ${media.fileName}${clipSummary}`,
  };

  res.json({
    ok: true,
    face,
  });
});

app.post('/api/face/stop', (req, res) => {
  activeFaceCueToken = '';
  const face = setFaceState({
    mediaId: '',
    loop: req.body?.loop,
    clipStartSec: 0,
    clipEndSec: 0,
  });

  lastCommand = {
    type: 'face-stop',
    at: new Date().toISOString(),
    summary: 'Face expression stopped',
  };

  res.json({
    ok: true,
    face,
  });
});

app.post('/api/face/media', express.raw({
  type: () => true,
  limit: '200mb',
}), (req, res) => {
  const incomingName = decodeURIComponent(String(req.headers['x-file-name'] || ''));
  if (!incomingName) {
    throw new Error('Missing x-file-name header.');
  }

  if (!Buffer.isBuffer(req.body) || req.body.length === 0) {
    throw new Error('Expression upload body is empty.');
  }

  const safeName = sanitizeFaceFilename(incomingName);
  const extension = validateFaceExtension(safeName);
  const baseName = safeName.slice(0, Math.max(1, safeName.length - extension.length));
  const storedName = `${Date.now()}-${baseName}${extension}`;
  const targetPath = path.join(EXPRESSIONS_DIR, storedName);

  fs.writeFileSync(targetPath, req.body);

  const media = buildFaceMediaRecord(storedName);
  res.json({
    ok: true,
    media,
    face: getFacePayload(),
  });
});

app.delete('/api/face/media/:mediaId', (req, res) => {
  const mediaId = path.basename(String(req.params.mediaId || '').trim());
  if (!mediaId) {
    throw new Error('mediaId is required.');
  }

  const filePath = getFaceMediaFilePath(mediaId);
  if (!fs.existsSync(filePath)) {
    throw new Error('Expression media not found.');
  }

  fs.unlinkSync(filePath);

  if (faceState.mediaId === mediaId) {
    setFaceState({ mediaId: '', loop: faceState.loop });
  }

  lastCommand = {
    type: 'face-delete',
    at: new Date().toISOString(),
    summary: `Face expression deleted: ${mediaId}`,
  };

  res.json({
    ok: true,
    face: getFacePayload(),
  });
});

app.use((error, req, res, next) => {
  console.error(error);
  res.status(400).json({
    ok: false,
    error: error.message || 'Unexpected server error.',
  });
});

app.listen(WEB_PORT, () => {
  const bootSettings = readSettingsXml();
  updateCurrentState(bootSettings.pose, bootSettings.times);

  console.log('-----------------------------------------------');
  console.log('Servo Motion Workbench Running');
  console.log(`Web UI:   http://localhost:${WEB_PORT}`);
  console.log(`Face UI:  http://localhost:${WEB_PORT}/face.html`);
  console.log(`OSC Dest: ${OSC_HOST}:${OSC_PORT}`);
  console.log(`Config:   ${SETTINGS_XML_PATH}`);
  console.log(`Neutral:  P${bootSettings.pose.pitch} Y${bootSettings.pose.yaw} L${bootSettings.pose.arml} R${bootSettings.pose.armr}`);
  console.log(`Media:    ${FACE_MEDIA_DIR}`);
  console.log('-----------------------------------------------');
});
