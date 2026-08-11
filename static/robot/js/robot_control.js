// E.I.Art Doll Ctrl V3.0 - Robot Control System
// Integrated with Flask backend - API paths updated to /api/robot/...

// === 导航系统 ===
document.addEventListener('DOMContentLoaded', () => {
    const navTabs = document.querySelectorAll('.nav-tab');
    const views = document.querySelectorAll('.view');
    const importBtn = document.getElementById('btn-import-motion');
    const importInput = document.getElementById('motion-import-file');
    const BINDING_URL = '/server/config/content?view=binding';
    const MOTIONS_URL = '/server/config/content?view=motions';

    // F-IC1/IC2：映射与动作库已迁入配置中心
    const params = new URLSearchParams(window.location.search);
    const hash = (window.location.hash || '').replace(/^#/, '');
    if (params.get('view') === 'mapping' || hash === 'mapping') {
        window.location.replace(BINDING_URL);
        return;
    }
    if (params.get('view') === 'motions' || hash === 'motions') {
        window.location.replace(MOTIONS_URL);
        return;
    }
    
    navTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const viewName = tab.dataset.view;

            if (viewName === 'mapping') {
                window.location.href = BINDING_URL;
                return;
            }
            if (viewName === 'motions') {
                window.location.href = MOTIONS_URL;
                return;
            }
            
            // 更新标签状态
            navTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            // 切换视图
            views.forEach(v => v.classList.remove('active'));
            document.getElementById(`view-${viewName}`).classList.add('active');
        });
    });

    if (importBtn && importInput) {
        importBtn.addEventListener('click', () => importInput.click());
        importInput.addEventListener('change', async (e) => {
            const file = e.target.files && e.target.files[0];
            if (!file) return;
            await importMotionJsonFile(file);
            importInput.value = '';
        });
    }
});

// === 动作库加载 ===
async function loadMotionLibrary() {
    try {
        const response = await fetch('/api/robot/motions');
        const data = await response.json();
        
        if (data.success) {
            const container = document.getElementById('motion-library');
            if (data.motions.length === 0) {
                container.innerHTML = '<p style="color: var(--text-sub);">暂无录制的动作</p>';
                return;
            }
            
            container.innerHTML = data.motions.map(motion => `
                <div class="motion-card">
                    <div class="motion-card-header">${motion.name}</div>
                    <div class="motion-card-info">
                        ${motion.frameCount} 帧 | ${(motion.duration / 1000).toFixed(1)}秒
                    </div>
                    <div class="motion-card-actions">
                        <button class="btn-test" onclick="playMotion('${motion.name}')">播放</button>
                        <button class="btn-delete" onclick="deleteMotion('${motion.name}')">删除</button>
                    </div>
                </div>
            `).join('');
        }
    } catch (error) {
        console.error('Failed to load motion library:', error);
    }
}

async function playMotion(motionName) {
    try {
        const response = await fetch(`/api/robot/play/${motionName}`, { method: 'POST' });
        const data = await response.json();
        if (!data.success) {
            alert('播放失败: ' + data.error);
        }
    } catch (error) {
        console.error('Failed to play motion:', error);
    }
}

async function deleteMotion(motionName) {
    if (!confirm(`确定要删除动作 "${motionName}" 吗？`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/robot/motions/${motionName}`, { method: 'DELETE' });
        const data = await response.json();
        if (data.success) {
            loadMotionLibrary(); // 重新加载列表
        } else {
            alert('删除失败: ' + data.error);
        }
    } catch (error) {
        console.error('Failed to delete motion:', error);
    }
}

async function importMotionJsonFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/robot/motions/import', {
            method: 'POST',
            body: formData,
        });
        const data = await response.json();

        if (!response.ok || !data.success) {
            alert(`导入失败: ${data.error || '未知错误'}`);
            return;
        }

        alert(`导入成功: ${data.motionName}`);
        await loadMotionLibrary();
    } catch (error) {
        console.error('Failed to import motion JSON:', error);
        alert('导入失败: 网络或服务器错误');
    }
}

// E.I.Art Doll Ctrl V2.0 - Persistence Fixed & Ultra Smooth

class KeypointFilter {
    constructor(alpha = 0.3) {
        this.alpha = alpha;
        this.prevPoints = null;
    }
    filter(keypoints) {
        if (!keypoints) return null;
        if (!this.prevPoints) {
            this.prevPoints = keypoints.map(kp => ({ ...kp }));
            return keypoints;
        }
        return keypoints.map((kp, i) => {
            const prev = this.prevPoints[i];
            if (!kp || !prev || typeof kp.x !== 'number') return kp || prev;
            const x = kp.x * this.alpha + prev.x * (1 - this.alpha);
            const y = kp.y * this.alpha + prev.y * (1 - this.alpha);
            const z = (kp.z||0) * this.alpha + (prev.z||0) * (1 - this.alpha);
            return { x, y, z, score: kp.score || 1 };
        });
    }
}

// 二阶强力平滑器 (Double Exponential Moving Average)
class ValueSmoother {
    constructor() {
        this.val1 = null; 
        this.val2 = null; 
    }
    process(newVal, smoothFactor) {
        if (typeof newVal !== 'number' || isNaN(newVal)) return this.val2 || 0;

        if (this.val1 === null) {
            this.val1 = newVal;
            this.val2 = newVal;
            return newVal;
        }
        
        // 允许平滑值高达 0.999
        const alpha = Math.min(Math.max(smoothFactor, 0), 0.999);

        // 1阶平滑
        this.val1 = (this.val1 * alpha) + (newVal * (1 - alpha));
        // 2阶平滑
        this.val2 = (this.val2 * alpha) + (this.val1 * (1 - alpha));
        
        return this.val2;
    }
}

class DollController {
    constructor() {
        console.log('🔧 DollController constructor started...');
        
        // 检查必要的 DOM 元素
        this.video = document.getElementById('video');
        this.canvas = document.getElementById('output');
        
        if (!this.video) {
            console.error('❌ Video element not found!');
            throw new Error('Video element not found');
        }
        if (!this.canvas) {
            console.error('❌ Canvas element not found!');
            throw new Error('Canvas element not found');
        }
        
        this.ctx = this.canvas.getContext('2d');
        
        // 检查 Socket.io 是否可用
        if (typeof io === 'undefined') {
            console.error('❌ Socket.io not loaded!');
            throw new Error('Socket.io not loaded');
        }
        
        this.socket = io();
        console.log('✓ Socket.io connected');
        
        this.detector = null;
        this.filter = new KeypointFilter(0.3);
        
        this.smoothers = {
            pitch: new ValueSmoother(),
            yaw: new ValueSmoother(),
            armL: new ValueSmoother(),
            armR: new ValueSmoother()
        };

        this.isStreaming = false;
        this.calibRaw = { yaw: 0, pitch: 0, armL: 0, armR: 0 };
        this.isCalibrating = false;
        
        this.isOscActive = false;
        this.lastSendTime = 0;
        this.oscInterval = 1000 / 10; // Default 10Hz

        // 录制相关状态
        this.isRecording = false;
        this.recordedFrames = [];
        this.recordStartTime = null;

        // 1. 立即加载设置
        this.loadSettings();
        
        // 2. 绑定事件
        this.bindEvents();
        
        console.log('🔧 DollController constructor completed');
    }

    bindEvents() {
        console.log('bindEvents: Binding event listeners...');
        
        const btnStart = document.getElementById('btn-start');
        if (!btnStart) {
            console.error('❌ btn-start element not found!');
            return;
        }
        
        btnStart.addEventListener('click', () => {
            console.log('🚀 START SYSTEM button clicked!');
            this.init();
        });
        console.log('✓ btn-start event listener bound');

        
        window.addEventListener('keydown', (e) => {
            if (e.code === 'KeyT') {
                this.isCalibrating = true;
                console.log("--> Calibration Triggered");
            }
        });

        const rateInput = document.getElementById('osc-rate');
        rateInput.addEventListener('input', (e) => {
            const hz = parseInt(e.target.value);
            document.getElementById('hz-val').innerText = hz;
            this.oscInterval = 1000 / hz;
            this.saveSettings();
        });

        document.getElementById('osc-active').addEventListener('change', (e) => {
            this.isOscActive = e.target.checked;
        });

        // 录制控制按钮
        document.getElementById('btn-record').addEventListener('click', () => this.startRecording());
        document.getElementById('btn-stop-record').addEventListener('click', () => this.stopRecording());
        document.getElementById('btn-confirm-save').addEventListener('click', () => this.saveMotion());
        document.getElementById('btn-cancel-save').addEventListener('click', () => this.closeModal());

        // 模态框回车键保存
        document.getElementById('motion-name-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.saveMotion();
        });

        // 绑定所有输入框自动保存
        document.querySelectorAll('input').forEach(input => {
            input.addEventListener('change', () => this.saveSettings());
            if(input.type === 'range') input.addEventListener('input', () => this.saveSettings());
        });

        const announceRobotControl = () => {
            document.getElementById('socket-status').classList.add('active');
            this.socket.emit('client_presence', { role: 'robot_control', ts: Date.now() });
        };
        this.socket.on('connect', announceRobotControl);
        this.socket.on('disconnect', () => document.getElementById('socket-status').classList.remove('active'));
        if (this.socket.connected) announceRobotControl();
        if (!this.robotControlPresenceTimer) {
            this.robotControlPresenceTimer = setInterval(() => {
                if (this.socket.connected) {
                    this.socket.emit('client_presence', { role: 'robot_control', ts: Date.now() });
                }
            }, 10000);
        }

        // Socket 录制状态监听
        this.socket.on('robot_recording_status', (data) => {
            console.log('Recording status:', data);
            if (data.saved) {
                this.loadMotionLibrary();
            }
        });

        this.socket.on('robot_playback_status', (data) => {
            console.log('Playback status:', data);
        });

        // 初始化加载动作库
        this.loadMotionLibrary();
    }

    saveSettings() {
        const settings = this.getSettingsFromUI();
        const rate = document.getElementById('osc-rate').value;
        const data = { settings, rate };
        // 使用新版本 Key，避免旧数据干扰
        localStorage.setItem('eiart_doll_settings_v30', JSON.stringify(data));
        console.log("Settings Saved");
    }

    loadSettings() {
        const json = localStorage.getItem('eiart_doll_settings_v30');
        if (!json) {
            console.log("No saved settings found, using HTML defaults.");
            return; 
        }
        
        try {
            const data = JSON.parse(json);
            console.log("Settings Loaded:", data);

            if (data.rate) {
                document.getElementById('osc-rate').value = data.rate;
                document.getElementById('hz-val').innerText = data.rate;
                this.oscInterval = 1000 / data.rate;
            }
            if (data.settings) {
                ['pitch', 'yaw', 'arml', 'armr'].forEach(axis => {
                    if (data.settings[axis]) {
                        ['center', 'gain', 'offset', 'min', 'max', 'rev', 'smooth'].forEach(f => {
                            const el = document.getElementById(`${axis}-${f}`);
                            const val = data.settings[axis][f];
                            if (el && val !== undefined) {
                                if (f === 'rev') el.checked = val;
                                else el.value = val;
                            }
                        });
                    }
                });
            }
        } catch (e) {
            console.error("Load Settings Failed", e);
        }
    }

    getSettingsFromUI() {
        const getAxis = (name) => ({
            center: parseFloat(document.getElementById(`${name}-center`).value) || 0,
            gain: parseFloat(document.getElementById(`${name}-gain`).value) || 1,
            offset: parseFloat(document.getElementById(`${name}-offset`).value) || 0,
            smooth: parseFloat(document.getElementById(`${name}-smooth`).value) || 0,
            min: parseFloat(document.getElementById(`${name}-min`).value) || 0,
            max: parseFloat(document.getElementById(`${name}-max`).value) || 359,
            rev: document.getElementById(`${name}-rev`).checked
        });
        
        return { 
            pitch: getAxis('pitch'), 
            yaw: getAxis('yaw'), 
            arml: getAxis('arml'), 
            armr: getAxis('armr') 
        };
    }

    async init() {
        const btn = document.getElementById('btn-start');
        const loader = document.getElementById('loading-screen');
        btn.disabled = true;
        loader.style.display = 'flex';

        try {
            await tf.setBackend('webgl');
            const model = poseDetection.SupportedModels.BlazePose;
            this.detector = await poseDetection.createDetector(model, {
                runtime: 'tfjs', modelType: 'lite', enableSmoothing: true
            });

            const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
            this.video.srcObject = stream;
            
            this.video.onloadedmetadata = () => {
                this.video.width = this.video.videoWidth;
                this.video.height = this.video.videoHeight;
                this.canvas.width = this.video.videoWidth;
                this.canvas.height = this.video.videoHeight;
                this.video.play();
                
                loader.style.display = 'none';
                this.isStreaming = true;
                btn.innerText = "SYSTEM ACTIVE";
                this.loop();
            };
        } catch (err) {
            console.error(err);
            loader.innerText = "ERROR: " + err.message;
        }
    }

    async loop() {
        if (!this.isStreaming) return;

        let poses = null;
        try {
            poses = await this.detector.estimatePoses(this.video, { flipHorizontal: false });
        } catch (e) {}

        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.ctx.save();
        this.ctx.translate(this.canvas.width, 0);
        this.ctx.scale(-1, 1);
        this.ctx.drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height);

        if (poses && poses.length > 0) {
            const pose = poses[0];
            
            this.drawDebug(pose.keypoints, this.ctx);

            const kp2d = this.filter.filter(pose.keypoints); 
            const kp3d = pose.keypoints3D;

            if (kp2d && kp3d) {
                const result = this.processPose(kp2d, kp3d);
                this.updateUI(result.raw, result.out);

                const now = Date.now();
                if (this.isOscActive && (now - this.lastSendTime > this.oscInterval)) {
                    // 使用 robot_ 前缀的事件名
                    this.socket.emit('robot_pose_data', result.out);
                    this.lastSendTime = now;
                }

                // 录制功能：记录当前帧
                if (this.isRecording && result.out) {
                    const timestamp = Date.now() - this.recordStartTime;
                    this.recordedFrames.push({
                        time: timestamp,
                        pose: {
                            pitch: result.out.pitch,
                            yaw: result.out.yaw,
                            armL: result.out.armL,
                            armR: result.out.armR
                        }
                    });
                    document.getElementById('record-frame-count').innerText = `${this.recordedFrames.length} frames`;
                }
            }
        }

        this.ctx.restore();
        requestAnimationFrame(() => this.loop());
    }

    processPose(kp2d, kp3d) {
        const currentRaw = this.getPhysicalRaw(kp2d, kp3d);
        if (!currentRaw) return { raw: null, out: null };

        if (this.isCalibrating) {
            this.calibRaw = { ...currentRaw };
            this.isCalibrating = false;
        }

        const s = this.getSettingsFromUI();

        const calcAxis = (raw, calibRaw, settings, scaleFactor, smoother) => {
            if (!settings) return 0;

            let delta = (raw - calibRaw) * scaleFactor;
            let target = settings.center + (delta * settings.gain) + settings.offset;

            if (settings.rev) target = 360 - target;

            // 应用双重平滑 (使用 settings.smooth)
            let smoothed = smoother.process(target, settings.smooth);

            return Math.min(Math.max(smoothed, settings.min), settings.max);
        };

        const out = {
            pitch: calcAxis(currentRaw.pitch, this.calibRaw.pitch, s.pitch, 4.0, this.smoothers.pitch),
            yaw:   calcAxis(currentRaw.yaw,   this.calibRaw.yaw,   s.yaw,   4.0, this.smoothers.yaw),
            armL:  calcAxis(currentRaw.armL,  this.calibRaw.armL,  s.arml,  1.0, this.smoothers.armL),
            armR:  calcAxis(currentRaw.armR,  this.calibRaw.armR,  s.armr,  1.0, this.smoothers.armR)
        };

        return { raw: currentRaw, out: out };
    }

    getPhysicalRaw(kp2d, kp3d) {
        const nose = kp2d[0];
        const leftEar = kp2d[7];
        const rightEar = kp2d[8];
        const ls = kp3d[11];
        const rs = kp3d[12];
        const le = kp3d[13];
        const re = kp3d[14];

        if (!nose || !leftEar || !rightEar || !ls || !le) return null;

        const midEarX = (leftEar.x + rightEar.x) / 2;
        const midEarY = (leftEar.y + rightEar.y) / 2;

        const rawYaw = nose.x - midEarX; 
        const rawPitch = nose.y - midEarY;
        const rawArmL = this.getArmAngle(ls, le);
        const rawArmR = this.getArmAngle(rs, re);

        return { pitch: rawPitch, yaw: rawYaw, armL: rawArmL, armR: rawArmR };
    }

    getArmAngle(shoulder, elbow) {
        const dy = elbow.y - shoulder.y; 
        const dx = elbow.x - shoulder.x;
        const dz = elbow.z - shoulder.z;
        const dist = Math.sqrt(dx*dx + dy*dy + dz*dz);
        if (dist < 0.01) return 0;
        return Math.acos(dy / dist) * (180 / Math.PI);
    }

    updateUI(raw, out) {
        if (!out) return;
        document.getElementById('out-pitch').innerText = Math.round(out.pitch);
        document.getElementById('out-yaw').innerText = Math.round(out.yaw);
        document.getElementById('out-arml').innerText = Math.round(out.armL);
        document.getElementById('out-armr').innerText = Math.round(out.armR);

        if (raw) {
            document.getElementById('raw-pitch').innerText = raw.pitch.toFixed(1);
            document.getElementById('raw-yaw').innerText = raw.yaw.toFixed(1);
            document.getElementById('raw-arml').innerText = raw.armL.toFixed(1);
            document.getElementById('raw-armr').innerText = raw.armR.toFixed(1);
        }
    }

    drawDebug(keypoints, ctx) {
        ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
        ctx.strokeStyle = 'rgba(0, 243, 255, 0.5)';
        ctx.lineWidth = 2;

        const indices = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16];
        indices.forEach(idx => {
            const p = keypoints[idx];
            if (p && p.score > 0.3) {
                ctx.beginPath();
                ctx.arc(p.x, p.y, 3, 0, 2 * Math.PI);
                ctx.fill();
            }
        });

        const connections = [[11,12], [11,13], [13,15], [12,14], [14,16], [3,7], [6,8]];
        ctx.beginPath();
        connections.forEach(pair => {
            const p1 = keypoints[pair[0]];
            const p2 = keypoints[pair[1]];
            if (p1 && p2 && p1.score > 0.3 && p2.score > 0.3) {
                ctx.moveTo(p1.x, p1.y);
                ctx.lineTo(p2.x, p2.y);
            }
        });
        ctx.stroke();
    }

    // === 录制功能 ===
    startRecording() {
        if (!this.isStreaming) {
            alert('Please start the system first!');
            return;
        }
        
        this.isRecording = true;
        this.recordedFrames = [];
        this.recordStartTime = Date.now();
        
        document.getElementById('record-status').classList.add('recording');
        document.getElementById('record-dot').classList.add('active');
        document.getElementById('record-text').innerText = 'RECORDING...';
        document.getElementById('btn-record').style.display = 'none';
        document.getElementById('btn-stop-record').style.display = 'block';
        document.getElementById('record-frame-count').innerText = '0 frames';
        
        console.log('🔴 Recording started');
    }

    stopRecording() {
        this.isRecording = false;
        
        document.getElementById('record-status').classList.remove('recording');
        document.getElementById('record-dot').classList.remove('active');
        document.getElementById('record-text').innerText = 'RECORDING STOPPED';
        document.getElementById('btn-record').style.display = 'block';
        document.getElementById('btn-stop-record').style.display = 'none';
        
        console.log(`⏹️ Recording stopped. Captured ${this.recordedFrames.length} frames`);
        
        if (this.recordedFrames.length === 0) {
            alert('No frames recorded!');
            document.getElementById('record-text').innerText = 'READY TO RECORD';
            return;
        }
        
        // 显示保存对话框
        this.showSaveModal();
    }

    showSaveModal() {
        const modal = document.getElementById('save-modal');
        const input = document.getElementById('motion-name-input');
        input.value = `motion_${Date.now()}`;
        modal.style.display = 'block';
        input.focus();
        input.select();
    }

    closeModal() {
        document.getElementById('save-modal').style.display = 'none';
        document.getElementById('record-text').innerText = 'READY TO RECORD';
    }

    async saveMotion() {
        const motionName = document.getElementById('motion-name-input').value.trim();
        if (!motionName) {
            alert('Please enter a motion name!');
            return;
        }
        
        // 通过 HTTP API 保存
        try {
            const response = await fetch('/api/robot/motions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    name: motionName, 
                    frames: this.recordedFrames 
                })
            });
            
            if (response.ok) {
                console.log(`💾 Motion "${motionName}" saved`);
                this.closeModal();
                this.loadMotionLibrary();
            } else {
                alert('Failed to save motion!');
            }
        } catch (error) {
            console.error('Save error:', error);
            alert('Error saving motion!');
        }
    }

    // === 动作库管理 ===
    async loadMotionLibrary() {
        try {
            const response = await fetch('/api/robot/motions');
            const data = await response.json();
            
            if (data.success && data.motions) {
                this.renderMotionList(data.motions);
            }
        } catch (error) {
            console.error('Failed to load motion library:', error);
        }
    }

    renderMotionList(motions) {
        const container = document.getElementById('motion-list');
        if (!container) return;
        
        if (motions.length === 0) {
            container.innerHTML = '<div class="empty-state">No motions saved yet. Start recording to create your first motion.</div>';
            return;
        }
        
        container.innerHTML = motions.map(motion => `
            <div class="motion-item">
                <div class="motion-info">
                    <div class="motion-name">${motion.name}</div>
                    <div class="motion-meta">${motion.frameCount} frames · ${(motion.duration / 1000).toFixed(1)}s</div>
                </div>
                <div class="motion-actions">
                    <button class="btn-small play" onclick="controller.playMotion('${motion.name}')">PLAY</button>
                    <button class="btn-small delete" onclick="controller.deleteMotion('${motion.name}')">DELETE</button>
                </div>
            </div>
        `).join('');
    }

    async playMotion(motionName) {
        console.log(`▶️ Playing motion: ${motionName}`);
        this.socket.emit('robot_play_motion', { motionName });
        
        // 也可以通过 HTTP API
        try {
            await fetch(`/api/robot/play/${motionName}`, { method: 'POST' });
        } catch (error) {
            console.error('Play error:', error);
        }
    }

    async deleteMotion(motionName) {
        if (!confirm(`Delete motion "${motionName}"?`)) return;
        
        try {
            const response = await fetch(`/api/robot/motions/${motionName}`, { method: 'DELETE' });
            if (response.ok) {
                console.log(`✖️ Motion "${motionName}" deleted`);
                this.loadMotionLibrary();
            } else {
                alert('Failed to delete motion!');
            }
        } catch (error) {
            console.error('Delete error:', error);
            alert('Error deleting motion!');
        }
    }

    showToast(message) {
        // 简单的 toast 通知
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed;
            bottom: 30px;
            right: 30px;
            background: rgba(0, 255, 157, 0.9);
            color: #000;
            padding: 15px 25px;
            border-radius: 10px;
            font-weight: 600;
            font-size: 13px;
            z-index: 10000;
            box-shadow: 0 4px 20px rgba(0, 255, 157, 0.4);
            animation: slideIn 0.3s ease;
        `;
        toast.textContent = message;
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 2000);
    }
}

// 确保 DOM 加载完成后再初始化控制器
let controller = null;

function initDollController() {
    try {
        console.log('🎮 Initializing DollController...');
        controller = new DollController();
        console.log('✅ DollController initialized successfully');
    } catch (error) {
        console.error('❌ Failed to initialize DollController:', error);
    }
}

// 使用 DOMContentLoaded 确保 DOM 已加载
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDollController);
} else {
    // DOM 已经加载完成
    initDollController();
}
