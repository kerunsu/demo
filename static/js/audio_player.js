/**
 * 儿童端音频播放器
 * 
 * 功能：
 * 1. 监听服务器发送的 play_audio 事件
 * 2. 实现播放队列管理（支持连续播放、优先级、中断）
 * 3. 预加载音频文件提升体验
 * 4. 发送播放状态回调到服务器
 * 5. 支持教师端停止播放
 */

class AudioPlayer {
    constructor(socket, sessionId) {
        this.socket = socket;
        this.sessionId = sessionId;
        
        // 播放状态
        this.currentAudio = null;          // 当前播放的 Audio 对象
        this.currentEntryId = null;        // 当前播放的语音条目ID
        this.currentFilePath = null;       // 当前播放的文件路径
        this.currentPlaybackIdentity = null; // speechId / behaviorId / sequenceId
        this.playQueue = [];               // 播放队列 [{entryId, filePath, priority, interrupt}]
        this.isPlaying = false;            // 是否正在播放
        this.isStopped = false;            // 是否被停止（用于跳过队列中剩余项）
        
        // 预加载缓存
        this.preloadedAudios = new Map();  // filePath -> ready Audio
        this.pendingPreloads = new Map();  // filePath -> { audio, promise, timer }
        this.maxPreloadSize = 10;
        this.preloadTimeoutMs = 5000;
        this.pendingDelayTimers = new Set(); // 行为绑定的语音延迟定时器
        this.pendingPlayback = null;       // 延迟中的唯一播放；不允许后续行为排队
        this.blockedPlayback = null;       // 被浏览器自动播放策略拦截的课程语音
        this.completedPlaybackIds = new Map();
        this.completedPlaybackTtlMs = 2 * 60 * 1000;
        this.completedPlaybackMax = 256;
        
        // 绑定事件监听器
        this._registerSocketEvents();
        
        console.log("[AudioPlayer] 初始化完成, sessionId:", sessionId);
    }
    
    /**
     * 注册 Socket.IO 事件监听器
     */
    _registerSocketEvents() {
        // 监听播放音频事件
        this.socket.on('play_audio', (data) => {
            console.log("[AudioPlayer] 收到 play_audio 事件:", data);
            this._handlePlayAudio(data);
        });
        
        // 监听停止播放事件
        this.socket.on('stop_audio', (data) => {
            console.log("[AudioPlayer] 收到 stop_audio 事件:", data);
            this._handleStopAudio(data);
        });

        this.socket.on('behavior_cancel', (data) => {
            this.cancelBehavior(data || {});
        });
        
        console.log("[AudioPlayer] Socket.IO 事件监听器已注册");
    }

    _identityFromData(data, entryId, filePath) {
        const speechId = String(data.speechId || data.speech_id || '').trim();
        const behaviorId = String(data.behaviorId || data.behavior_id || '').trim();
        const sequenceId = String(data.sequenceId || data.sequence_id || '').trim();
        const requestId = String(data.requestId || data.request_id || '').trim();
        const timestamp = data.timestamp == null ? '' : String(data.timestamp);
        return {
            speechId,
            behaviorId,
            sequenceId,
            requestId,
            key: speechId || behaviorId || sequenceId ||
                `${entryId || ''}|${filePath || ''}|${timestamp}`,
        };
    }

    _pruneCompletedPlaybackIds(now = Date.now()) {
        this.completedPlaybackIds.forEach((finishedAt, key) => {
            if (now - finishedAt > this.completedPlaybackTtlMs) {
                this.completedPlaybackIds.delete(key);
            }
        });
        while (this.completedPlaybackIds.size > this.completedPlaybackMax) {
            this.completedPlaybackIds.delete(this.completedPlaybackIds.keys().next().value);
        }
    }

    _rememberPlayback(identity) {
        if (!identity || !identity.key) return;
        this.completedPlaybackIds.set(identity.key, Date.now());
        this._pruneCompletedPlaybackIds();
    }

    _hasCompletedPlayback(identity) {
        if (!identity || !identity.key) return false;
        this._pruneCompletedPlaybackIds();
        return this.completedPlaybackIds.has(identity.key);
    }

    _activePlaybackIdentity() {
        return this.currentPlaybackIdentity ||
            (this.pendingPlayback && this.pendingPlayback.identity) ||
            (this.blockedPlayback && this.blockedPlayback.identity) ||
            null;
    }

    _isCurrentSessionEvent(data) {
        const eventSessionId = data && (data.sessionId || data.session_id);
        const activeSessionId = this.sessionId;
        if (
            eventSessionId &&
            activeSessionId &&
            activeSessionId !== 'readiness' &&
            String(eventSessionId) !== String(activeSessionId)
        ) {
            console.warn(
                "[AudioPlayer] 忽略其他会话的音频事件:",
                eventSessionId,
                "active:",
                activeSessionId
            );
            return false;
        }
        return true;
    }

    _matchesBehaviorEnvelope(identity, data) {
        if (!identity || !data) return false;
        const sessionId = String(data.sessionId || data.session_id || '').trim();
        const requestId = String(data.requestId || data.request_id || '').trim();
        const behaviorId = String(data.behaviorId || data.behavior_id || '').trim();
        return Boolean(
            sessionId && requestId && behaviorId &&
            String(this.sessionId || '') === sessionId &&
            String(identity.requestId || '') === requestId &&
            String(identity.behaviorId || identity.sequenceId || '') === behaviorId
        );
    }

    cancelBehavior(data) {
        if (!this._isCurrentSessionEvent(data)) return false;
        let cancelled = false;
        const pending = this.pendingPlayback;
        if (pending && this._matchesBehaviorEnvelope(pending.identity, data)) {
            this.pendingDelayTimers.forEach((timer) => clearTimeout(timer));
            this.pendingDelayTimers.clear();
            this.pendingPlayback = null;
            this._sendStatus(
                'stopped', 0, 0, 'behavior_cancelled',
                pending.identity, pending.entryId, pending.filePath
            );
            this._rememberPlayback(pending.identity);
            cancelled = true;
        }
        if (
            this.currentAudio &&
            this._matchesBehaviorEnvelope(this.currentPlaybackIdentity, data)
        ) {
            this._stopCurrentAudio();
            cancelled = true;
        }
        if (
            this.blockedPlayback &&
            this._matchesBehaviorEnvelope(this.blockedPlayback.identity, data)
        ) {
            const blocked = this.blockedPlayback;
            this.blockedPlayback = null;
            this._sendStatus(
                'stopped', 0, 0, 'behavior_cancelled',
                blocked.identity, blocked.entryId, blocked.filePath
            );
            this._rememberPlayback(blocked.identity);
            cancelled = true;
        }
        if (cancelled) this.isStopped = true;
        return cancelled;
    }

    _sendBehaviorReady(identity, entryId) {
        if (!identity || !identity.behaviorId || !identity.requestId) return;
        this.socket.emit('behavior_modality_ready', {
            protocolVersion: '1',
            sessionId: this.sessionId,
            requestId: identity.requestId,
            behaviorId: identity.behaviorId || identity.sequenceId,
            speechId: identity.speechId || undefined,
            entryId: entryId || undefined,
            readinessKey: identity.speechId || entryId || identity.key,
            modality: 'speech',
            status: 'ready',
            readyAtClientMs: Date.now(),
        });
    }
    
    /**
     * 处理播放音频事件
     * 
     * 事件数据格式:
     * {
     *   entry_id: string,      // 语音条目ID
     *   file_path: string,     // 文件路径
     *   priority: number,      // 优先级（可选，默认0，越大越优先）
     *   interrupt: boolean     // 是否中断当前播放（可选，默认false）
     * }
     */
    _handlePlayAudio(data) {
        if (!this._isCurrentSessionEvent(data)) return;
        const { entry_id, file_path, delay_ms = 0 } = data;
        const eventSessionId = data.sessionId || data.session_id;
        if (eventSessionId) this.sessionId = eventSessionId;
        
        if (!entry_id || !file_path) {
            console.warn("[AudioPlayer] play_audio 数据不完整:", data);
            return;
        }

        const identity = this._identityFromData(data, entry_id, file_path);
        if (this._hasCompletedPlayback(identity)) {
            console.log("[AudioPlayer] 忽略已完成行为的重复语音:", identity.key);
            return;
        }

        const browserSpeechIdentity =
            typeof window !== 'undefined' &&
            window.BrowserTts &&
            typeof window.BrowserTts.getActiveSpeechIdentity === 'function'
                ? window.BrowserTts.getActiveSpeechIdentity()
                : null;
        if (browserSpeechIdentity) {
            const browserKey = browserSpeechIdentity.speechId ||
                browserSpeechIdentity.behaviorId ||
                browserSpeechIdentity.sequenceId || '';
            if (browserKey && browserKey === identity.key) {
                console.log("[AudioPlayer] 同一行为已由浏览器 TTS 播放，忽略文件语音:", identity.key);
                return;
            }
            this._sendStatus(
                'dropped',
                0,
                0,
                '浏览器 TTS 正在播放，本次文件语音已丢弃',
                identity,
                entry_id,
                file_path
            );
            this._rememberPlayback(identity);
            return;
        }

        const activeIdentity = this._activePlaybackIdentity();
        if (activeIdentity) {
            if (activeIdentity.key === identity.key) {
                console.log("[AudioPlayer] 忽略当前行为的重复语音:", identity.key);
                return;
            }
            console.log("[AudioPlayer] 当前行为语音未结束，丢弃新语音:", identity.key);
            this._sendStatus(
                'dropped',
                0,
                0,
                '当前行为尚未结束，本次语音已丢弃',
                identity,
                entry_id,
                file_path
            );
            this._rememberPlayback(identity);
            return;
        }

        this.isStopped = false;

        // 延迟期间即占用语音通道；新行为直接丢弃，不排队。
        const delayMs = Math.max(0, Number(delay_ms) || 0);
        if (delayMs > 0 && !data._delay_applied) {
            console.log(`[AudioPlayer] 延迟 ${delayMs}ms 后播放课程语音:`, entry_id);
            const pending = { identity, entryId: entry_id, filePath: file_path };
            this.pendingPlayback = pending;
            this.preloadAudio(file_path).then(() => {
                if (this.pendingPlayback === pending) {
                    this._sendBehaviorReady(identity, entry_id);
                }
            }).catch((error) => {
                console.warn('[AudioPlayer] 行为语音预加载失败:', file_path, error);
            });
            const timer = setTimeout(() => {
                this.pendingDelayTimers.delete(timer);
                if (this.pendingPlayback !== pending) return;
                this.pendingPlayback = null;
                this._playAudio(entry_id, file_path, identity);
            }, delayMs);
            this.pendingDelayTimers.add(timer);
            return;
        }

        this._playAudio(entry_id, file_path, identity);
    }
    
    /**
     * 处理停止播放事件
     * 
     * 事件数据格式:
     * {
     *   immediate: boolean  // 是否立即停止（true）还是播放完当前后停止（false）
     * }
     */
    _handleStopAudio(data) {
        if (!this._isCurrentSessionEvent(data)) return;
        const { immediate = true } = data;
        const pending = this.pendingPlayback;
        this.pendingDelayTimers.forEach((timer) => clearTimeout(timer));
        this.pendingDelayTimers.clear();
        this.pendingPlayback = null;
        if (pending) {
            this._sendStatus(
                'stopped', 0, 0, '', pending.identity, pending.entryId, pending.filePath
            );
            this._rememberPlayback(pending.identity);
        }
        
        if (immediate) {
            // 立即停止当前播放并清空队列
            console.log("[AudioPlayer] 立即停止播放");
            this._stopCurrentAudio();
            if (this.blockedPlayback) {
                const blocked = this.blockedPlayback;
                this._sendStatus(
                    'stopped', 0, 0, '', blocked.identity, blocked.entryId, blocked.filePath
                );
                this._rememberPlayback(blocked.identity);
                this.blockedPlayback = null;
            }
            this.playQueue = [];
            this.isStopped = true;
        } else {
            // 播放完当前音频后停止（清空队列但不中断当前播放）
            console.log("[AudioPlayer] 播放完当前音频后停止");
            this.playQueue = [];
            this.isStopped = true;
        }
    }
    
    /**
     * 停止当前播放的音频
     */
    _stopCurrentAudio() {
        if (this.currentAudio) {
            const identity = this.currentPlaybackIdentity;
            const entryId = this.currentEntryId;
            const filePath = this.currentFilePath;
            this.currentAudio.pause();
            this.currentAudio.currentTime = 0;
            this._sendStatus(
                'stopped',
                0,
                this.currentAudio.duration || 0,
                '',
                identity,
                entryId,
                filePath
            );
            this._rememberPlayback(identity);
            
            this.currentAudio = null;
            this.currentEntryId = null;
            this.currentFilePath = null;
            this.currentPlaybackIdentity = null;
            this.isPlaying = false;
        }
    }
    
    /**
     * 播放队列中的下一个音频
     */
    _playNextInQueue() {
        // 如果被停止或队列为空，结束播放
        if (this.isStopped || this.playQueue.length === 0) {
            console.log("[AudioPlayer] 队列播放完成或已停止");
            this.isPlaying = false;
            return;
        }
        
        // 取出队列第一个
        const item = this.playQueue.shift();
        console.log("[AudioPlayer] 播放队列项:", item.entryId, item.filePath);
        
        // 播放音频
        this._playAudio(item.entryId, item.filePath);
    }
    
    /**
     * 播放指定音频文件
     * 
     * @param {string} entryId - 语音条目ID
     * @param {string} filePath - 文件路径（相对于 static/）
     */
    _playAudio(entryId, filePath, identity = null) {
        this.isPlaying = true;
        this.isStopped = false;
        this.currentEntryId = entryId;
        this.currentFilePath = filePath;
        this.currentPlaybackIdentity = identity ||
            this._identityFromData({}, entryId, filePath);
        
        // 检查是否已预加载
        let audio = this.preloadedAudios.get(filePath);
        
        if (!audio) {
            // 未预加载，创建新的 Audio 对象
            audio = new Audio(`/static/${filePath}`);
            console.log("[AudioPlayer] 创建新 Audio 对象:", filePath);
        } else {
            console.log("[AudioPlayer] 使用预加载的 Audio:", filePath);
            // 从缓存中移除（播放后需要重新预加载）
            // 预热时可能 muted/volume=0，播放前恢复
            audio.muted = false;
            audio.volume = 1;
            try {
                audio.currentTime = 0;
            } catch (_) { /* ignore */ }
        }
        
        this.currentAudio = audio;
        
        // 监听播放事件
        audio.onloadedmetadata = () => {
            console.log("[AudioPlayer] 音频元数据加载完成, 时长:", audio.duration);
        };
        
        audio.onplay = () => {
            if (this.currentAudio !== audio) return;
            console.log("[AudioPlayer] 开始播放");
            this._sendStatus('playing', audio.currentTime, audio.duration);
        };

        audio.oncanplay = () => {
            if (this.currentAudio === audio) {
                this._sendBehaviorReady(this.currentPlaybackIdentity, entryId);
            }
        };
        
        audio.ontimeupdate = () => {
            if (this.currentAudio !== audio) return;
            // 每秒发送一次进度更新（减少网络开销）
            const currentTime = audio.currentTime;
            if (Math.floor(currentTime) !== Math.floor(this._lastReportedTime || 0)) {
                this._sendStatus('playing', currentTime, audio.duration);
                this._lastReportedTime = currentTime;
            }
        };
        
        audio.onended = () => {
            if (this.currentAudio !== audio) return;
            audio.onended = null;
            audio.onerror = null;
            console.log("[AudioPlayer] 播放结束");
            const finishedIdentity = this.currentPlaybackIdentity;
            const finishedEntryId = this.currentEntryId;
            const finishedFilePath = this.currentFilePath;
            // 与服务端 AudioStatus.ENDED 对齐
            this._sendStatus(
                'ended',
                audio.duration,
                audio.duration,
                '',
                finishedIdentity,
                finishedEntryId,
                finishedFilePath
            );
            this._rememberPlayback(finishedIdentity);
            
            // 播放完成，清理当前状态
            this.currentAudio = null;
            this.currentEntryId = null;
            this.currentFilePath = null;
            this.currentPlaybackIdentity = null;
            this.isPlaying = false;
        };
        
        audio.onerror = (error) => {
            if (this.currentAudio !== audio) return;
            audio.onended = null;
            audio.onerror = null;
            console.error("[AudioPlayer] 播放错误:", error);
            const failedIdentity = this.currentPlaybackIdentity;
            const failedEntryId = this.currentEntryId;
            const failedFilePath = this.currentFilePath;
            if (this.preloadedAudios.get(filePath) === audio) {
                this.preloadedAudios.delete(filePath);
            }
            const mediaError = audio.error;
            const detail = mediaError
                ? `code=${mediaError.code}${mediaError.message ? `, ${mediaError.message}` : ''}`
                : 'unknown_media_error';
            this._sendStatus(
                'error',
                0,
                0,
                `加载失败: ${filePath} (${detail})`,
                failedIdentity,
                failedEntryId,
                failedFilePath
            );
            this._rememberPlayback(failedIdentity);
            
            // 错误后清理状态；新行为不会在当前行为后排队。
            this.currentAudio = null;
            this.currentEntryId = null;
            this.currentFilePath = null;
            this.currentPlaybackIdentity = null;
            this.isPlaying = false;
        };
        
        // 开始播放
        audio.play().catch(error => {
            if (this.currentAudio !== audio) return;
            audio.onended = null;
            audio.onerror = null;
            console.error("[AudioPlayer] 播放失败:", error);
            const errorName = error && error.name ? error.name : 'PlaybackError';
            const errorMessage = error && error.message ? error.message : String(error);

            // A runtime autoplay rejection is terminal for this behavior.
            // Replaying it after a later click would overlap a newer behavior.
            if (error && error.name === 'NotAllowedError' && filePath) {
                try {
                    audio.pause();
                } catch (_) { /* ignore */ }

                const blockedIdentity = this.currentPlaybackIdentity;
                this._sendStatus(
                    'error',
                    0,
                    0,
                    `播放被浏览器拦截，本次行为已安全丢弃: ${errorName}: ${errorMessage}`,
                    blockedIdentity,
                    entryId,
                    filePath
                );
                this._rememberPlayback(blockedIdentity);
                this.blockedPlayback = null;
                this.currentAudio = null;
                this.currentEntryId = null;
                this.currentFilePath = null;
                this.currentPlaybackIdentity = null;
                this.isPlaying = false;
                this._audioUnlocked = false;
                window.dispatchEvent(new CustomEvent('audio-playback-blocked', {
                    detail: { entryId, filePath, error: errorMessage }
                }));
                return;
            }

            const failedIdentity = this.currentPlaybackIdentity;
            this._sendStatus(
                'error',
                0,
                0,
                `播放失败: ${errorName}: ${errorMessage}`,
                failedIdentity,
                this.currentEntryId,
                this.currentFilePath
            );
            this._rememberPlayback(failedIdentity);
            this.currentAudio = null;
            this.currentEntryId = null;
            this.currentFilePath = null;
            this.currentPlaybackIdentity = null;
            this.isPlaying = false;
        });
    }

    /**
     * 必须由 pointer/click 等用户手势同步调用，恢复被自动播放策略拦截的语音。
     */
    retryBlockedPlayback() {
        if (!this.blockedPlayback || this.isPlaying) return false;
        const item = this.blockedPlayback;
        this.blockedPlayback = null;
        console.log("[AudioPlayer] 用户已点击，重试被拦截的课程语音:", item.entryId);
        this._playAudio(item.entryId, item.filePath, item.identity);
        return true;
    }
    
    /**
     * 用户手势内解锁并验证「真正能播出发声音频」。
     * 先 muted play 再 unmuted 短播，失败则返回 needGesture / NotAllowedError。
     * @param {string} filePath
     * @returns {Promise<{ok:boolean, detail:string, needGesture?:boolean}>}
     */
    async unlockAndVerifyPlayback(filePath) {
        if (!filePath) {
            return { ok: false, detail: "empty_file_path" };
        }
        try {
            await this.preloadAudio(filePath);
        } catch (err) {
            return { ok: false, detail: String(err && err.message || err) };
        }

        let audio = this.preloadedAudios.get(filePath);
        if (!audio) {
            audio = new Audio(`/static/${filePath}`);
            this.preloadedAudios.set(filePath, audio);
        }

        // 1) muted 播放（通常无需手势）
        try {
            audio.muted = true;
            audio.volume = 0;
            audio.currentTime = 0;
            await audio.play();
            audio.pause();
            audio.currentTime = 0;
        } catch (err) {
            return {
                ok: false,
                detail: `muted_play_failed:${err && err.message || err}`,
                needGesture: err && err.name === "NotAllowedError",
            };
        }

        // 2) unmuted 短播 —— 才算「能出声」
        try {
            audio.muted = false;
            audio.volume = 0.35;
            audio.currentTime = 0;
            await audio.play();
            await new Promise((r) => setTimeout(r, 280));
            audio.pause();
            audio.currentTime = 0;
            // 验完后恢复静音缓存，正式课点再 unmute
            audio.muted = true;
            audio.volume = 0;
            this._audioUnlocked = true;
            console.log("[AudioPlayer] 解锁并验证播放成功:", filePath);
            return { ok: true, detail: "playback_verified" };
        } catch (err) {
            audio.muted = true;
            audio.volume = 0;
            return {
                ok: false,
                detail: `unmuted_play_failed:${err && err.message || err}`,
                needGesture: !!(err && err.name === "NotAllowedError"),
            };
        }
    }

    isAudioUnlocked() {
        return !!this._audioUnlocked;
    }

    isBehaviorAudioBusy() {
        return !!this._activePlaybackIdentity();
    }

    getActivePlaybackIdentity() {
        const identity = this._activePlaybackIdentity();
        return identity ? { ...identity } : null;
    }
    
    /**
     * 发送播放状态到服务器
     * 
     * @param {string} status - 状态: 'playing' | 'paused' | 'stopped' | 'ended' | 'error'
     * @param {number} currentTime - 当前播放时间（秒）
     * @param {number} duration - 总时长（秒）
     * @param {string} errorMessage - 错误消息（可选）
     */
    _sendStatus(
        status,
        currentTime,
        duration,
        errorMessage = '',
        identity = this.currentPlaybackIdentity,
        entryId = this.currentEntryId,
        filePath = this.currentFilePath
    ) {
        const statusData = {
            session_id: this.sessionId,
            status: status,
            terminalStatus: status,
            actualAtClientMs: Date.now(),
            protocolVersion: '1',
            modality: 'speech',
            entry_id: entryId,
            file_path: filePath,
            current_time: currentTime,
            duration: duration,
            speechId: identity && identity.speechId || undefined,
            behaviorId: identity && (identity.behaviorId || identity.sequenceId) || undefined,
            sequenceId: identity && identity.sequenceId || undefined,
            requestId: identity && identity.requestId || undefined,
            speech_id: identity && identity.speechId || undefined,
            behavior_id: identity && (identity.behaviorId || identity.sequenceId) || undefined,
            sequence_id: identity && identity.sequenceId || undefined,
        };
        
        if (errorMessage) {
            statusData.error_message = errorMessage;
        }
        
        console.log("[AudioPlayer] 发送状态:", statusData);
        this.socket.emit('audio_status', statusData);
    }
    
    /**
     * 预加载音频文件
     * 
     * @param {string} filePath - 文件路径
     */
    /**
     * 静默预加载音频（不出声）。元数据或可播放即完成；超时会明确失败。
     * @param {string} filePath - 相对于 static/ 的路径
     * @returns {Promise<string>}
     */
    preloadAudio(filePath) {
        if (!filePath) {
            return Promise.reject(new Error("empty_file_path"));
        }

        // Only ready media lives in preloadedAudios.
        if (this.preloadedAudios.has(filePath)) {
            console.log("[AudioPlayer] 音频已预加载:", filePath);
            return Promise.resolve(filePath);
        }

        // All callers share the same bounded in-flight load.
        const existing = this.pendingPreloads.get(filePath);
        if (existing) return existing.promise;

        // Evict only ready media; an in-flight item must not be mistaken for it.
        if (this.preloadedAudios.size >= this.maxPreloadSize) {
            const firstKey = Array.from(this.preloadedAudios.keys()).find(
                (key) => this.preloadedAudios.get(key) !== this.currentAudio
            );
            const old = this.preloadedAudios.get(firstKey);
            if (old) {
                try {
                    old.src = "";
                } catch (_) { /* ignore */ }
            }
            if (firstKey !== undefined) {
                this.preloadedAudios.delete(firstKey);
                console.log("[AudioPlayer] 缓存已满，移除:", firstKey);
            }
        }

        let resolvePromise;
        let rejectPromise;
        const promise = new Promise((resolve, reject) => {
            resolvePromise = resolve;
            rejectPromise = reject;
        });
        const audio = new Audio(`/static/${filePath}`);
        audio.preload = "auto";
        audio.volume = 0;
        audio.muted = true;
        let settled = false;

        const cleanupListeners = () => {
            audio.onloadedmetadata = null;
            audio.oncanplay = null;
            audio.onerror = null;
        };
        const finish = (error) => {
            if (settled) return;
            settled = true;
            const current = this.pendingPreloads.get(filePath);
            if (current && current.timer) clearTimeout(current.timer);
            this.pendingPreloads.delete(filePath);
            cleanupListeners();
            if (error) {
                try { audio.src = ""; } catch (_) { /* ignore */ }
                rejectPromise(error);
                return;
            }
            this.preloadedAudios.set(filePath, audio);
            resolvePromise(filePath);
        };
        const ready = () => {
            console.log("[AudioPlayer] 预加载完成:", filePath);
            finish();
        };

        audio.onloadedmetadata = ready;
        audio.oncanplay = ready;
        audio.onerror = () => {
            console.warn("[AudioPlayer] 预加载失败:", filePath);
            finish(new Error(`preload_failed:${filePath}`));
        };
        const timer = setTimeout(() => {
            finish(new Error(`preload_timeout:${filePath}`));
        }, this.preloadTimeoutMs);
        this.pendingPreloads.set(filePath, { audio, promise, timer });
        try {
            audio.load();
            if (Number(audio.readyState || 0) >= 1) ready();
        } catch (err) {
            finish(err);
        }
        return promise;
    }
    
    /**
     * 清理资源
     */
    destroy() {
        console.log("[AudioPlayer] 清理资源");
        
        // 停止当前播放
        this._stopCurrentAudio();
        
        // 清空队列
        this.playQueue = [];
        this.blockedPlayback = null;
        this.pendingPlayback = null;
        this.pendingDelayTimers.forEach((timer) => clearTimeout(timer));
        this.pendingDelayTimers.clear();
        this.completedPlaybackIds.clear();
        
        // 清理预加载缓存
        this.preloadedAudios.forEach((audio, filePath) => {
            audio.src = '';  // 释放资源
        });
        this.preloadedAudios.clear();
        this.pendingPreloads.forEach((entry) => {
            if (entry.timer) clearTimeout(entry.timer);
            try { entry.audio.src = ''; } catch (_) { /* ignore */ }
        });
        this.pendingPreloads.clear();
        
        // 移除事件监听器
        this.socket.off('play_audio');
        this.socket.off('stop_audio');
    }
}

// 导出为全局变量（供 child.js 使用）
window.AudioPlayer = AudioPlayer;
