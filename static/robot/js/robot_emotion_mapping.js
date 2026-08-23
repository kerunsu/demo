// ===== 表情系统扩展 =====
// 这个文件包含了对 robot_mapping.js 的表情功能扩展
// 需要在 control.html 中在 robot_mapping.js 之后加载

// 扩展全局变量
window.emotionsData = [];
window.currentEmotions = {
    attention: '',
    reward: '',
    praise: '',
    question: '',
    hint: '',
    silent: '',
    social_greeting_intro: '',
    social_greeting_play: '',
    social_farewell_bye: '',
    social_farewell_reply: '',
};

function emotionAuxTypes() {
    return window.ALL_AUX_TYPES || ['praise', 'question', 'hint', 'silent'];
}

// ===== 加载表情列表 =====
async function loadEmotions() {
    try {
        const res = await fetch('/api/robot/emotions');
        const data = await res.json();
        if (data.success) {
            window.emotionsData = data.emotions || [];
            const fallback = data.default || (window.emotionsData && window.emotionsData[0]) || '';
            emotionAuxTypes().forEach((k) => {
                if (!window.currentEmotions[k]) window.currentEmotions[k] = fallback;
            });
            console.log(`✓ 加载了 ${window.emotionsData.length} 个表情`);
            populateEmotionSelects();
            
            // 填充完选择框后，立即从已保存的配置中加载表情
            // 等待 mappingData 可用
            const waitForMappingData = setInterval(() => {
                if (window.mappingData && window.currentScope) {
                    clearInterval(waitForMappingData);
                    console.log('📥 初始加载表情配置...');
                    loadEmotionsForScope(window.currentScope);
                }
            }, 100);
            
            // 最多等待3秒
            setTimeout(() => clearInterval(waitForMappingData), 3000);
        }
    } catch (error) {
        console.error('❌ 加载表情列表失败:', error);
    }
}

// ===== 填充表情选择框 =====
function populateEmotionSelects() {
    const auxTypes = emotionAuxTypes();
    
    auxTypes.forEach(type => {
        const select = document.getElementById(`emotion-${type}`);
        if (!select) {
            console.warn(`表情选择框不存在: emotion-${type}`);
            return;
        }
        
        select.innerHTML = '';
        
        window.emotionsData.forEach(emotion => {
            const option = document.createElement('option');
            option.value = emotion;
            option.textContent = emotion.replace('.gif', '').replace('_', ' ');
            select.appendChild(option);
        });
        
        // 设置默认值
        select.value = window.currentEmotions[type] || fallbackEmotion();
    });
    
    console.log('✓ 表情选择框已填充');
}

function fallbackEmotion() {
    return (window.emotionsData && window.emotionsData[0]) || '';
}

// ===== 表情改变回调 =====
function onEmotionChange(auxType) {
    const select = document.getElementById(`emotion-${auxType}`);
    if (select) {
        window.currentEmotions[auxType] = select.value;
        if (typeof window.markBehaviorDirty === 'function') window.markBehaviorDirty(auxType);
        console.log(`表情已更新: ${auxType} → ${select.value}`);
    }
}

// ===== 数据归一化 =====
function normalizeActionData(data) {
    const fb = fallbackEmotion();
    // 旧格式：数组 → 新格式：对象
    if (Array.isArray(data)) {
        return {
            motions: data,
            emotion: fb
        };
    }
    
    // 新格式：确保字段完整
    if (typeof data === 'object' && data !== null) {
        return {
            motions: data.motions || [],
            emotion: data.emotion || fb
        };
    }
    
    // 无效数据
    return {
        motions: [],
        emotion: fb
    };
}

// ===== 加载表情配置到UI =====
function loadEmotionsForScope(scope) {
    // 确保 mappingData 已加载
    if (!window.mappingData) {
        console.warn('mappingData 未加载，跳过表情配置加载');
        return;
    }
    
    console.log('📥 加载三级表情配置:', scope);
    
    const auxTypes = emotionAuxTypes();
    auxTypes.forEach(type => {
        const data = getConfigData(scope, type);
        const normalized = normalizeActionData(data);
        
        console.log(`  ${type}: 原始数据=`, data, '归一化=', normalized);
        
        const select = document.getElementById(`emotion-${type}`);
        if (select && window.emotionsData.length > 0) {
            select.value = normalized.emotion;
            window.currentEmotions[type] = normalized.emotion;
            console.log(`  ✓ 设置 emotion-${type} = ${normalized.emotion}`);
        }
    });
}

// ===== 辅助函数：获取配置数据 =====
function getConfigData(scope, auxType) {
    const data = window.mappingData;
    if (!data) return null;
    
    if (scope.type === 'default') {
        return data.defaults?.[auxType];
    } else if (scope.type === 'course') {
        return data.courses?.[scope.courseId]?.[auxType];
    } else if (scope.type === 'item') {
        return data.courses?.[scope.courseId]?.items?.[scope.itemId]?.[auxType];
    }
    
    return null;
}

// ===== 保存当前配置（包含表情） - 重写原始函数 =====
// 保存原始的 saveCurrentMapping 引用
let _originalSaveCurrentMapping = null;

function initEmotionSaveOverride() {
    if (typeof window.saveCurrentMapping === 'function' && !_originalSaveCurrentMapping) {
        _originalSaveCurrentMapping = window.saveCurrentMapping;
        
        window.saveCurrentMapping = async function() {
            console.log('💾 保存映射配置（包含表情）...');
            
            // 调用原始保存函数
            await _originalSaveCurrentMapping();
            
            // 表情数据会作为motions的一部分保存
            // 这里可以添加额外的表情保存逻辑
        };
        
        console.log('✓ saveCurrentMapping 已扩展以支持表情');
    }
}

// ===== 监听 loadScope 并加载表情 =====
function initEmotionLoadOverride() {
    // 等待原始 loadScope 函数定义
    const checkInterval = setInterval(() => {
        if (typeof window.loadScope === 'function') {
            clearInterval(checkInterval);
            
            const originalLoadScope = window.loadScope;
            window.loadScope = function(scope) {
                // 调用原始函数
                originalLoadScope(scope);
                
                // 延迟加载表情配置，确保 mappingData 已更新
                setTimeout(() => {
                    loadEmotionsForScope(scope);
                }, 100);
            };
            
            console.log('✓ loadScope 已扩展以支持表情');
        }
    }, 100);
    
    // 最多等待5秒
    setTimeout(() => clearInterval(checkInterval), 5000);
}

// ===== 页面加载完成后初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    // 延迟执行，确保 initMappingView 先完成
    setTimeout(() => {
        loadEmotions();
        initEmotionLoadOverride();
        initEmotionSaveOverride();
    }, 1000);
});

console.log('[Emotion Extension] 表情系统扩展已加载');
