/**
 * 机器人表情显示页面
 * 全屏显示 MP4 表情，响应 WebSocket 事件切换（历史 GIF 只读兼容）
 * 待机池中的素材按真实结尾随机轮播
 * 
 * 逻辑：
 * - 待机表情可被正式交互立即抢占
 * - 正式交互表情完整播放；后续正式事件排队，结束后回到随机待机
 * - 切换时无淡入淡出，紧密衔接
 * - 自动解析GIF帧数据获取真实播放时长
 * - 表情列表与默认表情启动时从 API 拉取（不再硬编码）
 */

// ========== 配置 ==========
let DEFAULT_EMOTION = null; // 兼容旧客户端：等于待机池第一项
let IDLE_EMOTIONS = [];
const EMOTION_BASE_PATH = '/static/resources/Emotions/';
const DEFAULT_GIF_DURATION = 3000; // 解析失败时的默认时长

// 所有可用的表情列表（由 API 填充）
let ALL_EMOTIONS = [];
let EMOTION_STYLES = {};
let GLOBAL_FILTER = {
    enabled: false,
    hueDeg: 0,
    brightness: 1,
    saturation: 1,
    contrast: 1,
    opacity: 1,
};

// ========== 状态管理 ==========
let socket = null;
let currentEmotion = null;
let emotionPlayTimer = null;  // 表情播放完成定时器
let isPlayingNonDefault = false; // 是否正在播放非默认表情
let activeEmotionEvent = null;
const completedEmotionIds = new Map();
const COMPLETED_EMOTION_TTL_MS = 2 * 60 * 1000;
const COMPLETED_EMOTION_MAX = 256;
let renderGeneration = 0; // 防止已过期的异步加载结果重新盖住待机层
let scheduledEmotionTimer = null;
let scheduledEmotionEvent = null;
let emotionAssetsReady = false;
let idlePlayTimer = null;
let lastIdleEmotion = null;
const pendingEmotionEvents = [];

// ========== DOM 元素 ==========
let emotionImg = document.getElementById('emotion-gif');
let emotionVideo = document.getElementById('emotion-video');
const idleImg = document.getElementById('emotion-idle');
const idleVideo = document.getElementById('emotion-idle-video');
const globalFilterLayer = document.getElementById('emotion-global-filter-layer');
const warmedImages = new Set();
const emotionUrls = new Map();
const LOCAL_EMOTION_BASE = 'http://127.0.0.1:19091/assets/emotions/';
const PREWARM_STATUS_URL = `${LOCAL_EMOTION_BASE}prewarm/status`;
const PREWARM_INSTANCE_ID = `emotion-display-${Date.now()}-${Math.random().toString(16).slice(2)}`;

function reportPrewarmStatus(phase, completed, total, current = '', failed = []) {
    fetch(PREWARM_STATUS_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            instanceId: PREWARM_INSTANCE_ID,
            phase,
            completed,
            total,
            current,
            failed,
        }),
    }).catch(() => {});
}

function normalizedStyle(value) {
    return {
        speedMultiplier: Number(value?.speedMultiplier) || 1,
        scale: Number(value?.scale) || 1,
        hueDeg: Number(value?.hueDeg) || 0,
        brightness: Number.isFinite(Number(value?.brightness)) ? Number(value.brightness) : 1,
        saturation: Number.isFinite(Number(value?.saturation)) ? Number(value.saturation) : 1,
        opacity: Number.isFinite(Number(value?.opacity)) ? Number(value.opacity) : 1,
    };
}

function applyGlobalFilter(value) {
    GLOBAL_FILTER = { ...GLOBAL_FILTER, ...(value || {}) };
    if (!globalFilterLayer) return;
    const enabled = GLOBAL_FILTER.enabled === true;
    globalFilterLayer.style.filter = enabled
        ? `hue-rotate(${Number(GLOBAL_FILTER.hueDeg) || 0}deg) `
          + `brightness(${Number(GLOBAL_FILTER.brightness) || 0}) `
          + `saturate(${Number(GLOBAL_FILTER.saturation) || 0}) `
          + `contrast(${Number(GLOBAL_FILTER.contrast) || 0})`
        : 'none';
    globalFilterLayer.style.opacity = enabled
        ? String(Number.isFinite(Number(GLOBAL_FILTER.opacity)) ? GLOBAL_FILTER.opacity : 1)
        : '1';
}

function applyMediaStyle(element, emotionName, override) {
    if (!element) return normalizedStyle(override || EMOTION_STYLES[emotionName]);
    const style = normalizedStyle(override || EMOTION_STYLES[emotionName]);
    element.style.transform = `scale(${style.scale})`;
    element.style.filter = `hue-rotate(${style.hueDeg}deg) brightness(${style.brightness}) saturate(${style.saturation})`;
    element.style.opacity = String(style.opacity);
    if ('playbackRate' in element) element.playbackRate = style.speedMultiplier;
    return style;
}

function applySettingsUpdate(data) {
    const emotionName = data?.emotionName;
    if (data?.globalFilter) applyGlobalFilter(data.globalFilter);
    if (emotionName && data?.style) {
        EMOTION_STYLES[emotionName] = normalizedStyle(data.style);
    }
    if (!emotionName || emotionName !== currentEmotion) return;
    if (emotionName === DEFAULT_EMOTION) {
        applyMediaStyle(isVideo(emotionName) ? idleVideo : idleImg, emotionName);
    } else {
        applyMediaStyle(isVideo(emotionName) ? emotionVideo : emotionImg, emotionName);
    }
}

function mediaUrl(mediaId) {
    const cachedUrl = emotionUrls.get(mediaId);
    if (cachedUrl) return cachedUrl;
    if (/^(resources\/|static\/)/i.test(mediaId || '')) {
        return '/static/' + mediaId.replace(/^static\//i, '');
    }
    return EMOTION_BASE_PATH + mediaId;
}

function isVideo(mediaId) {
    return /\.(mp4|webm|ogg)$/i.test(mediaId || '');
}

function emotionIdentity(payload) {
    const data = typeof payload === 'string' ? {} : (payload || {});
    const behaviorId = String(data.behaviorId || data.behavior_id || '').trim();
    const sequenceId = String(data.sequenceId || data.sequence_id || '').trim();
    const speechId = String(data.speechId || data.speech_id || '').trim();
    const requestId = String(data.requestId || data.request_id || '').trim();
    return {
        behaviorId,
        sequenceId,
        speechId,
        requestId,
        key: behaviorId || sequenceId || speechId || '',
    };
}

function matchesExactEmotionEnvelope(eventData, payload) {
    if (!eventData || !payload) return false;
    const current = emotionIdentity(eventData);
    const expected = emotionIdentity(payload);
    const currentSession = String(
        eventData.sessionId || eventData.session_id || ''
    ).trim();
    const expectedSession = String(
        payload.sessionId || payload.session_id || ''
    ).trim();
    return Boolean(
        currentSession && expectedSession && expected.requestId && expected.behaviorId &&
        currentSession === expectedSession &&
        current.requestId === expected.requestId &&
        String(current.behaviorId || current.sequenceId || '') === expected.behaviorId
    );
}

function pruneCompletedEmotionIds(now = Date.now()) {
    completedEmotionIds.forEach((finishedAt, key) => {
        if (now - finishedAt > COMPLETED_EMOTION_TTL_MS) {
            completedEmotionIds.delete(key);
        }
    });
    while (completedEmotionIds.size > COMPLETED_EMOTION_MAX) {
        completedEmotionIds.delete(completedEmotionIds.keys().next().value);
    }
}

function rememberCompletedEmotion(identity) {
    if (!identity || !identity.key) return;
    completedEmotionIds.set(identity.key, Date.now());
    pruneCompletedEmotionIds();
}

function emitEmotionTerminal(eventData, status, reason = '') {
    if (!socket || !socket.connected || !eventData) return;
    const identity = eventData.identity || emotionIdentity(eventData);
    socket.emit('robot_emotion_ended', {
        status: status || 'ended',
        terminalStatus: status || 'ended',
        actualAtClientMs: Date.now(),
        protocolVersion: eventData.protocolVersion || '1',
        modality: 'expression',
        reason,
        emotionName: eventData.emotionName,
        sessionId: eventData.sessionId || eventData.session_id || undefined,
        trainingSessionId:
            eventData.trainingSessionId || eventData.training_session_id || undefined,
        questionId: eventData.questionId || eventData.question_id || undefined,
        behaviorId: identity.behaviorId || identity.sequenceId || undefined,
        requestId: identity.requestId || eventData.requestId || eventData.request_id || undefined,
        sequenceId: identity.sequenceId || undefined,
        speechId: identity.speechId || undefined,
    });
}

function emitEmotionStarted(eventData) {
    if (!socket || !socket.connected || !eventData) return;
    const identity = eventData.identity || emotionIdentity(eventData);
    socket.emit('robot_emotion_started', {
        protocolVersion: eventData.protocolVersion || '1',
        sessionId: eventData.sessionId || eventData.session_id || undefined,
        requestId: identity.requestId || eventData.requestId || eventData.request_id || undefined,
        behaviorId: identity.behaviorId || identity.sequenceId || undefined,
        modality: 'expression',
        status: 'started',
        actualAtClientMs: Date.now(),
        emotionName: eventData.emotionName,
    });
}

function emitEmotionReady(eventData) {
    if (!socket || !socket.connected || !eventData || eventData.readyEmitted) return;
    eventData.readyEmitted = true;
    const identity = eventData.identity || emotionIdentity(eventData);
    socket.emit('robot_emotion_ready', {
        protocolVersion: eventData.protocolVersion || '1',
        sessionId: eventData.sessionId || eventData.session_id || undefined,
        requestId: identity.requestId || eventData.requestId || eventData.request_id || undefined,
        behaviorId: identity.behaviorId || identity.sequenceId || undefined,
        modality: 'expression',
        status: 'ready',
        readyAtClientMs: Date.now(),
        emotionName: eventData.emotionName,
    });
}

function stageEmotionReady(eventData, emotionName) {
    if (isVideo(emotionName)) {
        const player = preloadVideoAsset(emotionName);
        if (player.readyState >= 2) {
            emitEmotionReady(eventData);
        } else {
            player.addEventListener('canplay', () => emitEmotionReady(eventData), { once: true });
        }
        return;
    }
    if (warmedImages.has(emotionName)) {
        emitEmotionReady(eventData);
        return;
    }
    const image = new Image();
    image.src = mediaUrl(emotionName);
    if (image.complete && image.naturalWidth > 0) {
        warmedImages.add(emotionName);
        emitEmotionReady(eventData);
    } else if (typeof image.decode === 'function') {
        image.decode().then(() => {
            warmedImages.add(emotionName);
            emitEmotionReady(eventData);
        }).catch(() => {});
    } else {
        image.addEventListener('load', () => {
            warmedImages.add(emotionName);
            emitEmotionReady(eventData);
        }, { once: true });
    }
}

function showGifWithoutFlash(url, generation, emotionName, style, onError) {
    // 保留当前帧，等新 img 解码完成再原位替换；每次使用新元素可让 GIF 从首帧重播，
    // 同时复用浏览器缓存，不再通过时间戳强制下载 8–13MB 文件。
    const next = new Image();
    next.id = 'emotion-gif';
    next.alt = 'Robot Emotion';
    next.hidden = true;
    next.onload = () => {
        if (
            generation !== renderGeneration
            || !isPlayingNonDefault
            || currentEmotion !== emotionName
        ) {
            console.log('[Emotion Display] 忽略已过期的 GIF 加载结果:', emotionName);
            return;
        }
        applyMediaStyle(next, emotionName, style);
        next.hidden = false;
        emotionImg.replaceWith(next);
        emotionImg = next;
    };
    next.onerror = () => {
        console.warn('[Emotion Display] GIF 加载失败:', url);
        if (generation === renderGeneration) onError?.('gif_load_failed');
    };
    next.src = url;
}

async function preloadEmotionAssets() {
    const assets = [...ALL_EMOTIONS];
    const failed = [];
    let completed = 0;
    reportPrewarmStatus('preparing', completed, assets.length);
    const scratchVideo = document.createElement('video');
    scratchVideo.preload = 'auto';
    scratchVideo.muted = true;
    scratchVideo.defaultMuted = true;
    scratchVideo.playsInline = true;

    for (const emotionName of assets) {
        reportPrewarmStatus('preparing', completed, assets.length, emotionName, failed);
        const ready = isVideo(emotionName)
            ? await warmVideoAsset(scratchVideo, emotionName)
            : await warmImageAsset(emotionName);
        if (!ready) {
            failed.push(emotionName);
        }
        completed += 1;
        reportPrewarmStatus('preparing', completed, assets.length, emotionName, failed);
    }
    scratchVideo.pause();
    scratchVideo.removeAttribute('src');
    scratchVideo.load();
    reportPrewarmStatus(failed.length ? 'failed' : 'ready', completed, assets.length, '', failed);
    return failed;
}

function warmImageAsset(emotionName) {
    return new Promise((resolve) => {
        const image = new Image();
        let settled = false;
        const finish = (ready) => {
            if (settled) return;
            settled = true;
            if (ready) warmedImages.add(emotionName);
            resolve(ready);
        };
        image.onload = () => {
            if (typeof image.decode === 'function') {
                image.decode().then(() => finish(true)).catch(() => finish(false));
            } else {
                finish(true);
            }
        };
        image.onerror = () => finish(false);
        image.src = mediaUrl(emotionName);
        if (image.complete && image.naturalWidth > 0) finish(true);
    });
}

function warmVideoAsset(player, emotionName) {
    return new Promise((resolve) => {
        let settled = false;
        const finish = (ready) => {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            player.pause();
            try { player.currentTime = 0; } catch (_) { /* best effort */ }
            resolve(ready);
        };
        player.oncanplay = async () => {
            try {
                await player.play();
                requestAnimationFrame(() => finish(true));
            } catch (_) {
                finish(player.readyState >= 2);
            }
        };
        player.onerror = () => finish(false);
        const timer = setTimeout(() => finish(player.readyState >= 2), 15000);
        player.src = mediaUrl(emotionName);
        player.load();
    });
}

async function preferLocalEmotionAssets() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 800);
    try {
        const response = await fetch(`${LOCAL_EMOTION_BASE}manifest.json`, {
            cache: 'no-store',
            signal: controller.signal,
        });
        if (!response.ok) return false;
        const payload = await response.json();
        const localNames = new Set(payload && Array.isArray(payload.emotions) ? payload.emotions : []);
        let localCount = 0;
        ALL_EMOTIONS.forEach((name) => {
            if (!localNames.has(name)) return;
            emotionUrls.set(name, `${LOCAL_EMOTION_BASE}${encodeURIComponent(name)}`);
            localCount += 1;
        });
        console.log(`[Emotion Display] local robot emotions: ${localCount}/${ALL_EMOTIONS.length}`);
        return localCount > 0;
    } catch (error) {
        console.warn('[Emotion Display] local emotions unavailable; using server URLs');
        return false;
    } finally {
        clearTimeout(timeout);
    }
}

function preloadVideoAsset(mediaId) {
    if (!mediaId) return emotionVideo;
    const url = mediaUrl(mediaId);
    if (emotionVideo.getAttribute('src') !== url) {
        emotionVideo.pause();
        emotionVideo.src = url;
        try { emotionVideo.load(); } catch (_) { /* best effort */ }
    }
    return emotionVideo;
}

function stopIdlePlayback() {
    if (idlePlayTimer) clearTimeout(idlePlayTimer);
    idlePlayTimer = null;
    idleVideo.pause();
}

function chooseIdleEmotion() {
    const candidates = IDLE_EMOTIONS.filter((name) => ALL_EMOTIONS.includes(name));
    if (!candidates.length) return DEFAULT_EMOTION;
    const alternatives = candidates.length > 1
        ? candidates.filter((name) => name !== lastIdleEmotion)
        : candidates;
    return alternatives[Math.floor(Math.random() * alternatives.length)];
}

function showIdleLayer() {
    emotionImg.hidden = true;
    emotionVideo.pause();
    emotionVideo.hidden = true;
    if (isVideo(DEFAULT_EMOTION)) {
        idleImg.hidden = true;
        idleVideo.hidden = false;
        applyMediaStyle(idleVideo, DEFAULT_EMOTION);
        idleVideo.play().catch((error) => {
            console.warn('[Emotion Display] 待机 MP4 自动播放失败:', error);
        });
    } else {
        idleVideo.pause();
        idleVideo.hidden = true;
        idleImg.hidden = false;
        applyMediaStyle(idleImg, DEFAULT_EMOTION);
    }
}

function loadIdleMedia(emotionName = DEFAULT_EMOTION) {
    if (!emotionName) return;
    DEFAULT_EMOTION = emotionName;
    const url = mediaUrl(emotionName);
    if (isVideo(DEFAULT_EMOTION)) {
        idleImg.hidden = true;
        idleImg.removeAttribute('src');
        idleVideo.src = url;
        idleVideo.loop = false;
        idleVideo.currentTime = 0;
        applyMediaStyle(idleVideo, DEFAULT_EMOTION);
    } else {
        idleVideo.pause();
        idleVideo.removeAttribute('src');
        idleVideo.hidden = true;
        idleImg.src = url;
        applyMediaStyle(idleImg, DEFAULT_EMOTION);
    }
}

async function loadEmotionCatalog() {
    try {
        const [listRes, defRes] = await Promise.all([
            fetch('/api/robot/emotions').then((r) => r.json()),
            fetch('/api/robot/emotions/default').then((r) => r.json()),
        ]);
        if (listRes && listRes.success) {
            const catalogItems = Array.isArray(listRes.items) ? listRes.items : [];
            ALL_EMOTIONS = catalogItems.length
                ? catalogItems
                    .slice()
                    .sort((a, b) => {
                        if (a.name === listRes.default) return -1;
                        if (b.name === listRes.default) return 1;
                        return Number(b.refCount || 0) - Number(a.refCount || 0);
                    })
                    .map((item) => item.name)
                : (listRes.emotions || []);
            emotionUrls.clear();
            (listRes.items || []).forEach((item) => {
                if (item && item.name && item.url) emotionUrls.set(item.name, item.url);
            });
            EMOTION_STYLES = Object.fromEntries(
                (listRes.items || []).map((item) => [item.name, normalizedStyle(item.style)])
            );
            applyGlobalFilter(listRes.globalFilter);
            if (listRes.default) DEFAULT_EMOTION = listRes.default;
            IDLE_EMOTIONS = Array.isArray(listRes.idlePool) && listRes.idlePool.length
                ? listRes.idlePool.filter((name) => ALL_EMOTIONS.includes(name))
                : (DEFAULT_EMOTION ? [DEFAULT_EMOTION] : []);
        }
        if (defRes && defRes.success && defRes.emotion) {
            DEFAULT_EMOTION = defRes.emotion;
        }
    } catch (e) {
        console.warn('[Emotion Display] 加载表情目录失败，使用回退:', e);
    }
    if (!ALL_EMOTIONS.length && DEFAULT_EMOTION) {
        ALL_EMOTIONS = [DEFAULT_EMOTION];
    }
    if (!DEFAULT_EMOTION && ALL_EMOTIONS.length) {
        DEFAULT_EMOTION = ALL_EMOTIONS.includes('v2_idle.mp4')
            ? 'v2_idle.mp4'
            : ALL_EMOTIONS.includes('v2_idle.gif')
            ? 'v2_idle.gif'
            : ALL_EMOTIONS[0];
    }
    if (!IDLE_EMOTIONS.length && DEFAULT_EMOTION) IDLE_EMOTIONS = [DEFAULT_EMOTION];
    currentEmotion = DEFAULT_EMOTION;
}

// ========== GIF 时长解析 ==========
/**
 * 解析GIF文件获取总播放时长
 * GIF格式：每个图形控制扩展块包含帧延迟（单位为1/100秒）
 */
async function parseGifDuration(url) {
    try {
        const response = await fetch(url);
        const buffer = await response.arrayBuffer();
        const bytes = new Uint8Array(buffer);
        
        let totalDelay = 0;
        let i = 0;
        
        // 跳过GIF头部（6字节：GIF89a 或 GIF87a）
        i += 6;
        
        // 跳过逻辑屏幕描述符（7字节）
        const flags = bytes[i + 4];
        const hasGlobalColorTable = (flags & 0x80) !== 0;
        const globalColorTableSize = 1 << ((flags & 0x07) + 1);
        i += 7;
        
        // 跳过全局颜色表
        if (hasGlobalColorTable) {
            i += globalColorTableSize * 3;
        }
        
        // 遍历数据块
        while (i < bytes.length) {
            const blockType = bytes[i];
            
            if (blockType === 0x21) {
                // 扩展块
                const extType = bytes[i + 1];
                
                if (extType === 0xF9) {
                    // 图形控制扩展 (Graphic Control Extension)
                    // 结构: 21 F9 04 [packed] [delay low] [delay high] [transparent index] 00
                    const delayLow = bytes[i + 4];
                    const delayHigh = bytes[i + 5];
                    const delay = (delayHigh << 8) | delayLow; // 单位：1/100秒
                    totalDelay += delay * 10; // 转换为毫秒
                    i += 8; // 跳过整个图形控制扩展块
                } else {
                    // 其他扩展块，跳过
                    i += 2;
                    while (bytes[i] !== 0 && i < bytes.length) {
                        i += bytes[i] + 1;
                    }
                    i++; // 跳过终止符 0x00
                }
            } else if (blockType === 0x2C) {
                // 图像描述符
                const imgFlags = bytes[i + 9];
                const hasLocalColorTable = (imgFlags & 0x80) !== 0;
                const localColorTableSize = 1 << ((imgFlags & 0x07) + 1);
                i += 10;
                
                // 跳过局部颜色表
                if (hasLocalColorTable) {
                    i += localColorTableSize * 3;
                }
                
                // 跳过LZW最小码长度
                i++;
                
                // 跳过图像数据子块
                while (bytes[i] !== 0 && i < bytes.length) {
                    i += bytes[i] + 1;
                }
                i++; // 跳过终止符
            } else if (blockType === 0x3B) {
                // GIF结束标记
                break;
            } else {
                // 未知块，尝试跳过
                i++;
            }
        }
        
        // 如果解析到的时长为0，使用默认值
        if (totalDelay === 0) {
            console.warn(`[GIF Parser] ${url} 解析到时长为0，使用默认值`);
            return DEFAULT_GIF_DURATION;
        }
        
        return totalDelay;
    } catch (error) {
        console.error(`[GIF Parser] 解析失败 ${url}:`, error);
        return DEFAULT_GIF_DURATION;
    }
}

// ========== 初始化 ==========
async function init() {
    console.log('[Emotion Display] 初始化...');

    // 从 API 拉取表情列表与默认表情
    await loadEmotionCatalog();
    await preferLocalEmotionAssets();

    // 待机层只加载一次并持续循环；行为层结束时直接露出它。
    loadIdleMedia();
    const failedAssets = await preloadEmotionAssets();
    emotionAssetsReady = failedAssets.length === 0;

    connectWebSocket();
    playDefaultEmotion();

    if (failedAssets.length) {
        console.warn('[Emotion Display] 表情预热失败:', failedAssets);
    }
    setInterval(() => {
        reportPrewarmStatus(
            emotionAssetsReady ? 'ready' : 'failed',
            ALL_EMOTIONS.length,
            ALL_EMOTIONS.length,
            '',
            failedAssets
        );
    }, 10000);
}

// ========== WebSocket 连接 ==========
function connectWebSocket() {
    console.log('[Emotion Display] 连接WebSocket...');
    
    socket = io.connect(location.protocol + '//' + document.domain + ':' + location.port);
    
    socket.on('connect', () => {
        console.log('[Emotion Display] ✓ WebSocket已连接');
        socket.emit('client_presence', {
            role: 'robot_display',
            ts: Date.now(),
            protocolVersion: '1',
            capabilities: { behaviorReady: true, emotionAssetsReady },
        });
    });
    
    socket.on('disconnect', () => {
        console.log('[Emotion Display] ✗ WebSocket已断开');
    });
    if (!socket.__robotDisplayPresenceTimer) {
        socket.__robotDisplayPresenceTimer = setInterval(() => {
            if (socket && socket.connected) {
                socket.emit('client_presence', {
                    role: 'robot_display',
                    ts: Date.now(),
                    protocolVersion: '1',
                    capabilities: { behaviorReady: true, emotionAssetsReady },
                });
            }
        }, 10000);
    }
    
    // 监听表情切换事件
    socket.on('robot_emotion_change', (data) => {
        console.log('[Emotion Display] 收到表情切换事件:', data);
        if (data && data.emotionName) {
            if (data.settingsOnly === true) {
                applySettingsUpdate(data);
                return;
            }
            queueEmotion(data);
        }
    });

    socket.on('robot_idle_pool_changed', (data) => {
        const nextPool = Array.isArray(data?.emotions)
            ? data.emotions.filter((name) => ALL_EMOTIONS.includes(name))
            : [];
        if (!nextPool.length) return;
        IDLE_EMOTIONS = nextPool;
        DEFAULT_EMOTION = data.default || nextPool[0];
        if (!isPlayingNonDefault) playDefaultEmotion();
    });

    socket.on('behavior_cancel', (data) => {
        for (let index = pendingEmotionEvents.length - 1; index >= 0; index -= 1) {
            if (!matchesExactEmotionEnvelope(pendingEmotionEvents[index], data)) continue;
            const cancelled = pendingEmotionEvents.splice(index, 1)[0];
            rememberCompletedEmotion(emotionIdentity(cancelled));
            emitEmotionTerminal(cancelled, 'stopped', 'behavior_cancelled_while_queued');
        }
        if (scheduledEmotionEvent && matchesExactEmotionEnvelope(scheduledEmotionEvent, data)) {
            const cancelled = scheduledEmotionEvent;
            if (scheduledEmotionTimer) clearTimeout(scheduledEmotionTimer);
            scheduledEmotionTimer = null;
            scheduledEmotionEvent = null;
            rememberCompletedEmotion(emotionIdentity(cancelled));
            emitEmotionTerminal(cancelled, 'stopped', 'behavior_cancelled_before_start');
            return;
        }
        if (activeEmotionEvent && matchesExactEmotionEnvelope(activeEmotionEvent, data)) {
            onEmotionPlayComplete('stopped', 'behavior_cancelled');
        }
    });
}

// ========== 表情切换互斥 ==========
function queueEmotion(payload) {
    const emotionName = typeof payload === 'string' ? payload : payload.emotionName;
    const eventData = typeof payload === 'string' ? { emotionName } : payload;
    const identity = emotionIdentity(payload);
    pruneCompletedEmotionIds();

    if (scheduledEmotionEvent) {
        const pendingIdentity = emotionIdentity(scheduledEmotionEvent);
        if (pendingIdentity.key && pendingIdentity.key === identity.key) {
            console.log('[Emotion Display] 忽略已排程行为的重复表情:', identity.key);
            return false;
        }
        const superseded = scheduledEmotionEvent;
        if (scheduledEmotionTimer) clearTimeout(scheduledEmotionTimer);
        scheduledEmotionTimer = null;
        scheduledEmotionEvent = null;
        rememberCompletedEmotion(emotionIdentity(superseded));
        emitEmotionTerminal(superseded, 'stopped', 'superseded_before_start');
    }

    if (identity.key && completedEmotionIds.has(identity.key)) {
        console.log('[Emotion Display] 忽略已完成行为的重复表情:', identity.key);
        emitEmotionTerminal(
            { ...(typeof payload === 'object' ? payload : { emotionName }), identity },
            'ended',
            'duplicate_ack'
        );
        return false;
    }

    // Game-style state machine: IDLE is interruptible; EVENT is atomic. A
    // defensive FIFO handles a command that reaches the display while another
    // formal expression is still finishing.
    if (isPlayingNonDefault) {
        const activeKey = activeEmotionEvent && activeEmotionEvent.identity &&
            activeEmotionEvent.identity.key;
        if (activeKey && identity.key && activeKey === identity.key) {
            console.log('[Emotion Display] 忽略当前行为的重复表情:', identity.key);
            return false;
        }
        pendingEmotionEvents.push(eventData);
        console.log('[Emotion Display] 正式表情播放中，新事件进入队列:', identity.key || emotionName);
        return true;
    }

    // Formal behavior transactions explicitly restart the same asset so every
    // state change gets one complete expression cycle. Settings/manual repeats
    // without restart remain idempotent.
    const restartRequested = typeof payload === 'object' && payload?.restart === true;
    if (isPlayingNonDefault && emotionName === currentEmotion && !restartRequested) {
        console.log('[Emotion Display] 表情未改变，跳过');
        emitEmotionTerminal(
            { ...(typeof payload === 'object' ? payload : { emotionName }), identity },
            'ended',
            'already_displayed'
        );
        rememberCompletedEmotion(identity);
        return false;
    }
    
    const relativeDelayMs = Number(eventData?.startDelayMs);
    const startAtEpochMs = Number(eventData?.startAtEpochMs || 0);
    const delayMs = Number.isFinite(relativeDelayMs)
        ? Math.max(0, relativeDelayMs)
        : Math.max(0, startAtEpochMs - Date.now());
    if (delayMs > 0 || (isVideo(emotionName) && emotionName !== DEFAULT_EMOTION)) {
        if (isVideo(emotionName) && emotionName !== DEFAULT_EMOTION) {
            const stagedUrl = mediaUrl(emotionName);
            const stagedPlayer = preloadVideoAsset(emotionName);
            stagedPlayer.pause();
            stagedPlayer.hidden = true;
            eventData.stagedVideoUrl = stagedUrl;
        } else if (!isVideo(emotionName) && !warmedImages.has(emotionName)) {
            const stagedImage = new Image();
            stagedImage.src = mediaUrl(emotionName);
            stagedImage.decode?.().then(() => warmedImages.add(emotionName)).catch(() => {});
        }
        stageEmotionReady(eventData, emotionName);
        scheduledEmotionEvent = eventData;
        scheduledEmotionTimer = setTimeout(() => {
            const scheduled = scheduledEmotionEvent;
            scheduledEmotionTimer = null;
            if (!scheduled) return;
            scheduledEmotionEvent = null;
            playEmotion(scheduled);
        }, delayMs);
    } else {
        stageEmotionReady(eventData, emotionName);
        playEmotion(eventData);
    }
    return true;
}

// ========== 播放表情 ==========
function playEmotion(payload) {
    const eventData = typeof payload === 'string' ? { emotionName: payload } : (payload || {});
    const emotionName = eventData.emotionName;
    if (eventData.style) EMOTION_STYLES[emotionName] = normalizedStyle(eventData.style);
    if (eventData.globalFilter) applyGlobalFilter(eventData.globalFilter);
    const style = normalizedStyle(eventData.style || EMOTION_STYLES[emotionName]);
    // 清除之前的播放定时器
    if (emotionPlayTimer) {
        clearTimeout(emotionPlayTimer);
        emotionPlayTimer = null;
    }
    
    console.log('[Emotion Display] 播放表情:', emotionName);
    currentEmotion = emotionName;
    const generation = ++renderGeneration;

    if (eventData.isIdle === true) {
        isPlayingNonDefault = false;
        activeEmotionEvent = null;
        showIdleLayer();
        console.log('[Emotion Display] 待机表情底层持续播放中');
        return;
    }

    stopIdlePlayback();

    const video = isVideo(emotionName);
    const newSrc = mediaUrl(emotionName);
    emotionImg.hidden = true;
    emotionVideo.hidden = !video;
    if (video) {
        emotionVideo.pause();
        emotionVideo.loop = false;
        applyMediaStyle(emotionVideo, emotionName, style);
        emotionVideo.onloadedmetadata = () => {
            if (
                generation !== renderGeneration
                || !isPlayingNonDefault
                || !Number.isFinite(emotionVideo.duration)
                || emotionVideo.duration <= 0
            ) return;
            if (emotionPlayTimer) clearTimeout(emotionPlayTimer);
            emotionPlayTimer = setTimeout(() => {
                onEmotionPlayComplete('error', 'video_ended_timeout');
            }, Math.ceil(emotionVideo.duration * 1000 / style.speedMultiplier) + 2000);
        };
        if (
            eventData.stagedVideoUrl !== newSrc
            || emotionVideo.getAttribute('src') !== newSrc
        ) {
            emotionVideo.src = newSrc;
        }
        emotionVideo.currentTime = 0;
        emotionVideo.play()
            .then(() => {
                if (generation !== renderGeneration) emotionVideo.pause();
                else emitEmotionStarted(activeEmotionEvent);
            })
            .catch((e) => {
                console.warn('[Emotion Display] 视频播放失败:', e);
                if (generation === renderGeneration) {
                    onEmotionPlayComplete(
                        'error',
                        e && e.name ? e.name : 'video_play_failed'
                    );
                }
            });
    } else {
        emotionVideo.pause();
        emotionVideo.removeAttribute('src');
        showGifWithoutFlash(newSrc, generation, emotionName, style, (reason) => {
            onEmotionPlayComplete('error', reason);
        });
    }

    // 非默认表情只播放一次；到点后隐藏上层，立即露出持续运行的待机层。
    isPlayingNonDefault = true;
    activeEmotionEvent = {
        ...eventData,
        identity: emotionIdentity(eventData),
    };
    if (!video) emitEmotionStarted(activeEmotionEvent);
    const requestedDuration = Number(eventData.durationMs || 0);
    const duration = requestedDuration > 0 ? requestedDuration : DEFAULT_GIF_DURATION;
    // MP4 以浏览器原生 ended 为准，计时器仅是损坏文件/浏览器异常时的看门狗，
    // 不会在视频自然结束前提前切回待机。GIF 继续按单次循环时长完成。
    // Keep the fallback bounded. A lost `ended` event must not hold the
    // teacher UI for minutes; the server can recover on the next command.
    const completionDelay = video ? Math.max(duration + 3000, 8000) : duration;
    console.log(`[Emotion Display] 行为表情单次播放，完成后露出待机层`);
    emotionPlayTimer = setTimeout(() => {
        onEmotionPlayComplete(video ? 'error' : 'ended', video ? 'video_ended_timeout' : '');
    }, completionDelay);
}

// ========== 表情播放完成回调 ==========
function onEmotionPlayComplete(status = 'ended', reason = '') {
    if (!activeEmotionEvent) return;
    console.log('[Emotion Display] 表情播放完成');
    const completedEvent = activeEmotionEvent;
    isPlayingNonDefault = false;
    if (emotionPlayTimer) clearTimeout(emotionPlayTimer);
    emotionPlayTimer = null;
    activeEmotionEvent = null;
    rememberCompletedEmotion(completedEvent && completedEvent.identity);
    emitEmotionTerminal(completedEvent, status, reason);

    const nextEvent = pendingEmotionEvents.shift();
    if (nextEvent) {
        queueEmotion(nextEvent);
    } else {
        playDefaultEmotion();
    }
}

// ========== 播放默认表情 ==========
function playDefaultEmotion() {
    const nextIdle = chooseIdleEmotion();
    if (!nextIdle) {
        console.warn('[Emotion Display] 默认表情尚未就绪');
        return;
    }
    lastIdleEmotion = nextIdle;
    console.log('[Emotion Display] 随机待机表情:', nextIdle);
    stopIdlePlayback();
    loadIdleMedia(nextIdle);
    playEmotion({ emotionName: nextIdle, isIdle: true });
    if (!isVideo(nextIdle)) {
        parseGifDuration(mediaUrl(nextIdle)).then((duration) => {
            if (!isPlayingNonDefault && currentEmotion === nextIdle) {
                idlePlayTimer = setTimeout(playDefaultEmotion, Math.max(500, duration));
            }
        });
    }
}

// 每次事件视频都 loop=false，并由原生 ended 精确完成一次。回调具备幂等保护。
emotionVideo.addEventListener('ended', () => onEmotionPlayComplete('ended', 'media_ended'));
idleVideo.addEventListener('ended', () => {
    if (!isPlayingNonDefault) playDefaultEmotion();
});


// ========== 页面加载完成后初始化 ==========
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

console.log('[Emotion Display] 脚本已加载');
