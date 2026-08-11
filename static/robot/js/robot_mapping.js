// ===== 映射配置管理器 V3.2 =====
// 采用左侧树形导航 + 右侧统一动作矩阵的设计
// API路径已更新为 /api/robot/...
// V3.2 新增：表情映射支持

// 标准四槽 + 社交课点四槽（全局通用配置）
const STANDARD_AUX_TYPES = ['praise', 'question', 'hint', 'silent'];
const SOCIAL_AUX_TYPES = [
  'social_greeting_intro',
  'social_greeting_play',
  'social_farewell_bye',
  'social_farewell_reply',
];
const ALL_AUX_TYPES = [...STANDARD_AUX_TYPES, ...SOCIAL_AUX_TYPES];
window.ALL_AUX_TYPES = ALL_AUX_TYPES;

// 全局状态（暴露到 window 供其他模块访问）
let mappingData = null;
let studentsData = [];
let coursesData = [];
let motionsData = [];
let motionMetadata = {};
let emotionsData = []; // NEW: 表情列表
let currentProfile = 'default'; // 'default' 或 studentId
let currentScope = { type: 'default', courseId: null, itemId: null }; // 当前选中的配置范围

// 暴露关键变量到 window（供 robot_emotion_mapping.js 访问）
window.mappingData = null;
window.currentScope = currentScope;
window.currentProfile = currentProfile;

// ===== 初始化入口 =====
async function initMappingView() {
    console.log('🎯 Initializing Mapping View V3.1...');
    
    try {
        // 并行加载所有数据
        const [mappingRes, studentsRes, coursesRes, motionsRes] = await Promise.all([
            fetch('/api/robot/mapping/full').then(r => r.json()),
            fetch('/api/robot/students').then(r => r.json()),
            fetch('/api/robot/courses').then(r => r.json()),
            fetch('/api/robot/motions').then(r => r.json())
        ]);

        mappingData = mappingRes.mapping || {}; // 提取 mapping 字段
        window.mappingData = mappingData; // 同步到 window
        studentsData = studentsRes.students || [];
        coursesData = coursesRes.courses || [];
        motionsData = motionsRes.motions ? motionsRes.motions.map(m => m.name) : [];
        motionMetadata = Object.fromEntries(
            (motionsRes.motions || []).map((m) => [m.name, m.metadata || {}])
        );
        window.motionMetadata = motionMetadata;

        console.log('✓ Data loaded:', { 
            students: studentsData.length, 
            courses: coursesData.length, 
            motions: motionsData.length,
            hasDefaults: !!mappingData.defaults,
            mappingKeys: Object.keys(mappingData)
        });

        // 初始化学生选择器
        initProfileSelector();
        
        // 构建配置树
        buildConfigTree();
        
        // 填充静态姿势下拉框
        populateIdleSelect();
        
        // 加载默认配置（全局通用）
        loadScope({ type: 'default' });
        
    } catch (error) {
        console.error('❌ Failed to initialize mapping view:', error);
        alert('加载配置失败: ' + error.message);
    }
}

// ===== 学生/档案选择器 =====
function initProfileSelector() {
    const select = document.getElementById('profile-select');
    if (!select) {
        console.error('❌ profile-select element not found!');
        return;
    }
    
    select.innerHTML = '<option value="default">通用档案</option>';
    
    console.log('👥 Populating student selector with', studentsData.length, 'students');
    
    studentsData.forEach(student => {
        const option = document.createElement('option');
        option.value = student.id;
        option.textContent = `${student.name} (ID: ${student.id})`;
        select.appendChild(option);
    });
    
    console.log('✅ Student selector populated');
}

function switchProfile() {
    const select = document.getElementById('profile-select');
    currentProfile = select.value;
    window.currentProfile = currentProfile; // 同步到 window
    
    console.log('📂 Switched profile to:', currentProfile);
    
    // 重建树（因为配置状态指示器会变化）
    buildConfigTree();
    
    // 重新加载当前范围的配置
    loadScope(currentScope);
}

// ===== 配置树构建 =====
function buildConfigTree() {
    const treeContainer = document.getElementById('config-tree');
    if (!treeContainer) {
        console.error('❌ config-tree element not found!');
        return;
    }
    
    treeContainer.innerHTML = '';

    console.log('🌳 Building config tree with', coursesData.length, 'courses');

    // 根节点：全局通用配置
    const globalNode = createTreeNode({
        label: '全局通用配置',
        scope: { type: 'default' },
        hasConfig: hasConfigAt('default')
    });
    treeContainer.appendChild(globalNode);

    // 课程节点
    coursesData.forEach(course => {
        console.log('  📚 Adding course:', course.title, 'with', course.items?.length || 0, 'items');
        const courseNode = createCourseNode(course);
        treeContainer.appendChild(courseNode);
    });
    
    console.log('✅ Config tree built');
}

function createCourseNode(course) {
    const container = document.createElement('div');
    container.className = 'tree-course';

    // 课程标题
    const header = document.createElement('div');
    header.className = 'tree-course-header';
    
    const toggle = document.createElement('span');
    toggle.className = 'tree-toggle';
    toggle.textContent = '▼';
    toggle.onclick = (e) => {
        e.stopPropagation();
        container.classList.toggle('collapsed');
        toggle.textContent = container.classList.contains('collapsed') ? '▶' : '▼';
    };

    const title = document.createElement('span');
    title.textContent = `${course.id}. ${course.title}`;
    
    header.appendChild(toggle);
    header.appendChild(title);
    container.appendChild(header);

    // 课程通用项
    const courseGeneral = createTreeNode({
        label: `${course.title}通用`,
        scope: { type: 'course', courseId: course.id },
        hasConfig: hasConfigAt('course', course.id),
        indent: true
    });
    container.appendChild(courseGeneral);

    // Item节点
    if (course.items && course.items.length > 0) {
        course.items.forEach(item => {
            const itemNode = createTreeNode({
                label: `Item ${item.id}: ${item.name || '无标题'}`,
                scope: { type: 'item', courseId: course.id, itemId: item.id },
                hasConfig: hasConfigAt('item', course.id, item.id),
                indent: true
            });
            container.appendChild(itemNode);
        });
    }

    return container;
}

function createTreeNode({ label, scope, hasConfig, indent = false }) {
    const node = document.createElement('div');
    node.className = 'tree-node' + (indent ? ' tree-node-indent' : '');
    
    // 配置状态指示器
    const indicator = document.createElement('span');
    indicator.className = `config-indicator ${hasConfig ? 'active' : ''}`;
    indicator.textContent = '●';
    
    const text = document.createElement('span');
    text.textContent = label;
    
    node.appendChild(indicator);
    node.appendChild(text);
    
    // 点击选中
    node.onclick = () => {
        // 移除其他选中状态
        document.querySelectorAll('.tree-node').forEach(n => n.classList.remove('selected'));
        node.classList.add('selected');
        
        // 加载配置
        loadScope(scope);
    };
    
    // 默认选中全局配置
    if (scope.type === 'default') {
        node.classList.add('selected');
    }
    
    return node;
}

// ===== 配置状态检查 =====
function hasConfigAt(type, courseId = null, itemId = null) {
    if (!mappingData) return false;

    if (currentProfile === 'default') {
        // 检查通用档案
        if (type === 'default') {
            // 检查defaults中是否有非空配置
            const d = mappingData.defaults || {};
            return ALL_AUX_TYPES.some((k) => {
                const v = d[k];
                if (Array.isArray(v)) return v.length > 0;
                if (v && typeof v === 'object' && Array.isArray(v.motions)) return v.motions.length > 0;
                return false;
            });
        } else if (type === 'course') {
            const c = mappingData.courses[courseId];
            return c && STANDARD_AUX_TYPES.some((k) => {
                const v = c[k];
                if (Array.isArray(v)) return v.length > 0;
                if (v && typeof v === 'object' && Array.isArray(v.motions)) return v.motions.length > 0;
                return false;
            });
        } else if (type === 'item') {
            // 在通用档案下，item级配置不存在
            return false;
        }
    } else {
        // 检查学生档案
        const studentConfig = mappingData.students[currentProfile];
        if (!studentConfig) return false;

        if (type === 'default') {
            // 学生级别：检查是否有任何课程配置
            return Object.keys(studentConfig).length > 0;
        } else if (type === 'course') {
            const c = studentConfig[courseId];
            return c && STANDARD_AUX_TYPES.some((k) => {
                const v = c[k];
                if (Array.isArray(v)) return v.length > 0;
                if (v && typeof v === 'object' && Array.isArray(v.motions)) return v.motions.length > 0;
                return false;
            });
        } else if (type === 'item') {
            const c = studentConfig[courseId];
            if (!c || !c.items) return false;
            const i = c.items[itemId];
            return i && STANDARD_AUX_TYPES.some((k) => {
                const v = i[k];
                if (Array.isArray(v)) return v.length > 0;
                if (v && typeof v === 'object' && Array.isArray(v.motions)) return v.motions.length > 0;
                return false;
            });
        }
    }
    
    return false;
}

// ===== 加载指定范围的配置 =====
function loadScope(scope) {
    currentScope = scope;
    window.currentScope = currentScope; // 同步到 window
    console.log('📖 Loading scope:', scope, 'Profile:', currentProfile);

    // 更新标题
    updateScopeTitle(scope);

    // 获取配置数据
    const config = getConfigForScope(scope);

    // 渲染到动作插槽
    renderActionSlots(config);
}

function updateScopeTitle(scope) {
    const titleEl = document.getElementById('current-scope-title');
    
    if (currentProfile === 'default') {
        if (scope.type === 'default') {
            titleEl.textContent = '全局通用配置';
        } else if (scope.type === 'course') {
            const course = coursesData.find(c => c.id == scope.courseId);
            titleEl.textContent = `${course?.title || '课程'} - 课程通用配置`;
        } else if (scope.type === 'item') {
            const course = coursesData.find(c => c.id == scope.courseId);
            const item = course?.items?.find(i => i.id == scope.itemId);
            titleEl.textContent = `${course?.title || '课程'} - Item ${scope.itemId}: ${item?.name || ''}`;
        }
    } else {
        const student = studentsData.find(s => s.id == currentProfile);
        const prefix = `[${student?.name || '学生'}] `;
        
        if (scope.type === 'default') {
            titleEl.textContent = prefix + '个人档案';
        } else if (scope.type === 'course') {
            const course = coursesData.find(c => c.id == scope.courseId);
            titleEl.textContent = prefix + `${course?.title || '课程'} - 课程通用`;
        } else if (scope.type === 'item') {
            const course = coursesData.find(c => c.id == scope.courseId);
            const item = course?.items?.find(i => i.id == scope.itemId);
            titleEl.textContent = prefix + `${course?.title || '课程'} - Item ${scope.itemId}`;
        }
    }
}

function getConfigForScope(scope) {
    const empty = { praise: [], hint: [], question: [], silent: [], idle: null, __sequence: {}, __animation: {} };
    ALL_AUX_TYPES.forEach((k) => { empty[k] = []; });
    
    // 辅助函数：从新/旧格式中提取 motions 数组
    function extractMotions(data) {
        if (Array.isArray(data)) {
            return data;  // 旧格式：直接返回数组
        } else if (data && typeof data === 'object' && data.motions) {
            return data.motions;  // 新格式：返回 motions 字段
        }
        return [];
    }

    function pickAux(source, includeSocial) {
        const keys = includeSocial ? ALL_AUX_TYPES : STANDARD_AUX_TYPES;
        const out = { idle: null, __sequence: {}, __animation: {} };
        keys.forEach((k) => {
            const raw = source?.[k];
            out[k] = extractMotions(raw);
            out.__sequence[k] = raw && typeof raw === 'object' && !Array.isArray(raw)
                ? (raw.sequence || {}) : {};
            out.__animation[k] = raw && typeof raw === 'object' && !Array.isArray(raw)
                ? String(raw.animation || '') : '';
        });
        return out;
    }
    
    if (currentProfile === 'default') {
        if (scope.type === 'default') {
            const out = pickAux(mappingData.defaults, true);
            out.idle = mappingData.defaults?.idle || null;
            return out;
        } else if (scope.type === 'course') {
            const c = mappingData.courses?.[scope.courseId];
            return pickAux(c, false);
        } else if (scope.type === 'item') {
            // 通用档案下没有item级配置
            return empty;
        }
    } else {
        // 学生档案
        const studentConfig = mappingData.students?.[currentProfile] || {};
        
        if (scope.type === 'default') {
            // 学生根级别没有配置，显示为空
            return empty;
        } else if (scope.type === 'course') {
            const c = studentConfig[scope.courseId];
            return pickAux(c, false);
        } else if (scope.type === 'item') {
            const c = studentConfig[scope.courseId];
            const i = c?.items?.[scope.itemId];
            return pickAux(i, false);
        }
    }
    
    return empty;
}

function onAnimationChange() {
    const select = document.getElementById('animation-praise');
    if (!select || !currentScope) return;
    const value = String(select.value || '');
    let parent = null;
    if (currentProfile === 'default' && currentScope.type === 'default') {
        mappingData.defaults = mappingData.defaults || {};
        parent = mappingData.defaults;
    } else if (currentProfile === 'default' && currentScope.type === 'course') {
        mappingData.courses = mappingData.courses || {};
        parent = mappingData.courses[currentScope.courseId] = mappingData.courses[currentScope.courseId] || {};
    } else if (currentProfile !== 'default' && currentScope.type === 'course') {
        mappingData.students = mappingData.students || {};
        mappingData.students[currentProfile] = mappingData.students[currentProfile] || {};
        parent = mappingData.students[currentProfile][currentScope.courseId] = mappingData.students[currentProfile][currentScope.courseId] || {};
    } else if (currentProfile !== 'default' && currentScope.type === 'item') {
        mappingData.students = mappingData.students || {};
        mappingData.students[currentProfile] = mappingData.students[currentProfile] || {};
        const course = mappingData.students[currentProfile][currentScope.courseId] = mappingData.students[currentProfile][currentScope.courseId] || {};
        course.items = course.items || {};
        parent = course.items[currentScope.itemId] = course.items[currentScope.itemId] || {};
    }
    if (!parent) return;
    const existing = parent.praise;
    if (Array.isArray(existing)) {
        parent.praise = { motions: existing, emotion: '', sequence: {}, animation: value };
    } else {
        parent.praise = existing && typeof existing === 'object' ? existing : { motions: [] };
        parent.praise.animation = value;
    }
}

// ===== 渲染动作插槽 =====
function renderActionSlots(config) {
    // 渲染标准四槽 + 社交四槽（社交槽仅全局 defaults 有 DOM）
    ALL_AUX_TYPES.forEach(auxType => {
        const container = document.getElementById(`slot-${auxType}`);
        if (!container) return;
        container.innerHTML = '';
        
        const motions = config[auxType] || [];
        motions.forEach((motionName, index) => {
            const tag = createMotionTag(motionName, auxType, index);
            container.appendChild(tag);
        });
    });

    // 渲染静态姿势下拉框
    const idleSelect = document.getElementById('slot-idle');
    if (idleSelect) idleSelect.value = config.idle || '';
    if (typeof window.renderSequenceControls === 'function') {
        window.renderSequenceControls(config);
    }
    if (typeof window.renderAnimationBinding === 'function') {
        window.renderAnimationBinding(config.__animation?.praise || '');
    }
}

function createMotionTag(motionName, auxType, index) {
    const tag = document.createElement('div');
    tag.className = 'motion-tag';
    
    const name = document.createElement('span');
    name.textContent = motionName;
    
    const removeBtn = document.createElement('button');
    removeBtn.className = 'tag-remove';
    removeBtn.textContent = '×';
    removeBtn.onclick = () => removeMotionFromSlot(auxType, index);
    
    tag.appendChild(name);
    tag.appendChild(removeBtn);
    
    return tag;
}

// ===== 动作选择器 =====
let pendingMotionAdd = null; // { auxType }

function addMotionToSlot(auxType) {
    pendingMotionAdd = { auxType };
    
    // 填充动作列表
    const picker = document.getElementById('motion-picker');
    picker.innerHTML = '<option value="">-- 选择动作 --</option>';
    
    motionsData.forEach(name => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        picker.appendChild(option);
    });
    
    // 显示模态框
    document.getElementById('motion-select-modal').style.display = 'flex';
}

function closeMotionPicker() {
    document.getElementById('motion-select-modal').style.display = 'none';
    pendingMotionAdd = null;
}

function confirmMotionPick() {
    const picker = document.getElementById('motion-picker');
    const selectedMotion = picker.value;
    
    if (!selectedMotion) {
        alert('请选择一个动作');
        return;
    }
    
    if (!pendingMotionAdd) return;
    
    const { auxType } = pendingMotionAdd;
    
    // 添加到当前配置
    const config = getConfigForScope(currentScope);
    if (!config[auxType]) config[auxType] = [];
    config[auxType].push(selectedMotion);
    if (typeof window.applyImportedTimingDefaults === 'function') {
        window.applyImportedTimingDefaults(config, auxType, selectedMotion);
    }
    
    // 重新渲染
    renderActionSlots(config);
    
    closeMotionPicker();
    
    console.log(`➕ Added ${selectedMotion} to ${auxType}`);
}

function removeMotionFromSlot(auxType, index) {
    const config = getConfigForScope(currentScope);
    config[auxType].splice(index, 1);
    renderActionSlots(config);
    
    console.log(`➖ Removed motion from ${auxType} at index ${index}`);
}

// ===== 测试动作 =====
function testAction(auxType, triggerButton = null) {
    const config = getConfigForScope(currentScope);

    if (typeof window.testBehaviorSequence === 'function') {
        window.testBehaviorSequence(auxType, config, triggerButton);
        return;
    }
    
    let motionToTest = null;
    
    if (auxType === 'idle') {
        motionToTest = document.getElementById('slot-idle').value;
    } else {
        const motions = config[auxType] || [];
        if (motions.length === 0) {
            alert(`${auxType} 动作列表为空`);
            return;
        }
        // 随机选择一个
        motionToTest = motions[Math.floor(Math.random() * motions.length)];
    }
    
    if (!motionToTest) {
        alert('未配置动作');
        return;
    }
    
    console.log(`▶️ Testing motion: ${motionToTest}`);
    
    fetch(`/api/robot/play/${motionToTest}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                console.log('✓ Test playback started');
            } else {
                alert('播放失败: ' + data.error);
            }
        })
        .catch(err => {
            console.error('❌ Test failed:', err);
            alert('测试失败: ' + err.message);
        });
}

// ===== 保存配置 =====
async function saveCurrentMapping() {
    const config = getConfigForScope(currentScope);
    
    // 获取当前静态姿势选择
    const idleValue = document.getElementById('slot-idle').value;
    config.idle = idleValue || null;
    
    // 获取当前表情选择（从 robot_emotion_mapping.js 扩展）
    const emotions = window.currentEmotions || {};
    ALL_AUX_TYPES.forEach((k) => {
        if (!emotions[k]) emotions[k] = (window.emotionsData && window.emotionsData[0]) || '';
    });
    
    console.log('💾 Saving config:', currentScope, config, 'emotions:', emotions);
    
    try {
        if (currentProfile === 'default') {
            // 保存到通用档案
            if (currentScope.type === 'default') {
                // 保存defaults（包含表情 + 社交四槽）
                await Promise.all([
                    saveDefaultMapping('idle', config.idle),
                    ...ALL_AUX_TYPES.map((k) =>
                        saveDefaultMapping(k, config[k] || [], emotions[k], config.__sequence?.[k] || {}, config.__animation?.[k] || '')
                    ),
                ]);
            } else if (currentScope.type === 'course') {
                // 保存课程级（包含表情）
                await Promise.all(
                    STANDARD_AUX_TYPES.map((k) =>
                        saveCourseMapping(currentScope.courseId, k, config[k] || [], emotions[k], config.__sequence?.[k] || {}, config.__animation?.[k] || '')
                    )
                );
            }
        } else {
            // 保存到学生档案
            if (currentScope.type === 'course') {
                await Promise.all(
                    STANDARD_AUX_TYPES.map((k) =>
                        saveStudentCourseMapping(currentProfile, currentScope.courseId, k, config[k] || [], emotions[k], config.__sequence?.[k] || {}, config.__animation?.[k] || '')
                    )
                );
            } else if (currentScope.type === 'item') {
                await Promise.all(
                    STANDARD_AUX_TYPES.map((k) =>
                        saveItemMapping(currentProfile, currentScope.courseId, currentScope.itemId, k, config[k] || [], emotions[k], config.__sequence?.[k] || {}, config.__animation?.[k] || '')
                    )
                );
            }
        }
        
        // 重新加载映射数据
        const mappingRes = await fetch('/api/robot/mapping/full').then(r => r.json());
        mappingData = mappingRes.mapping || {};
        window.mappingData = mappingData; // 同步到 window
        
        // 重建树（更新配置指示器）
        buildConfigTree();
        
        // 重新选中当前节点
        loadScope(currentScope);
        
        alert('✓ 配置已保存');
        
    } catch (error) {
        console.error('❌ Save failed:', error);
        alert('保存失败: ' + error.message);
    }
}

// ===== API调用包装 =====
async function saveDefaultMapping(auxType, value, emotion, sequence = {}, animation = '') {
    if (auxType === 'idle') {
        return fetch('/api/robot/mapping/idle', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ motionName: value })
        }).then(r => r.json());
    } else {
        // 包含表情数据
        return fetch(`/api/robot/mapping/defaults/${auxType}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ motions: value, emotion: emotion, sequence, animation })
        }).then(r => r.json());
    }
}

async function saveCourseMapping(courseId, auxType, motions, emotion, sequence = {}, animation = '') {
    return fetch(`/api/robot/mapping/course/${courseId}/${auxType}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ motions, emotion, sequence, animation })
    }).then(r => r.json());
}

async function saveStudentCourseMapping(studentId, courseId, auxType, motions, emotion, sequence = {}, animation = '') {
    return fetch(`/api/robot/mapping/student/${studentId}/course/${courseId}/${auxType}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ motions, emotion, sequence, animation })
    }).then(r => r.json());
}

async function saveItemMapping(studentId, courseId, itemId, auxType, motions, emotion, sequence = {}, animation = '') {
    return fetch(`/api/robot/mapping/item/${studentId}/${courseId}/${itemId}/${auxType}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ motions, emotion, sequence, animation })
    }).then(r => r.json());
}

// ===== 静态姿势下拉框填充 =====
function populateIdleSelect() {
    const select = document.getElementById('slot-idle');
    select.innerHTML = '<option value="">-- 未设置 --</option>';
    
    motionsData.forEach(name => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        select.appendChild(option);
    });
}

