// 通用功能：建立 Socket，并挂到 window 供模块脚本（如 child.js）使用
const socket = io();
if (typeof window !== 'undefined') {
    window.socket = socket;
}

/**
 * 向服务器登记本端角色，供 /server 与就绪门 presence 使用。
 * 需周期性调用（建议 ≤15s），因服务端 30s 无刷新视为离线。
 */
function emitClientPresence(role) {
    if (!socket || !role) return;
    socket.emit('client_presence', {
        role: role,
        ts: Date.now(),
    });
}

function startClientPresenceHeartbeat(role, intervalMs) {
    const ms = intervalMs || 10000;
    emitClientPresence(role);
    if (socket && !socket.__presenceBound) {
        socket.on('connect', function () {
            emitClientPresence(role);
        });
        socket.__presenceBound = true;
    }
    return setInterval(function () {
        emitClientPresence(role);
    }, ms);
}

if (typeof window !== 'undefined') {
    window.emitClientPresence = emitClientPresence;
    window.startClientPresenceHeartbeat = startClientPresenceHeartbeat;
}

// 路由功能
function renderRoute() {
    const route = location.hash || '#/login';
    const views = ['view-login', 'view-child', 'view-courses', 'view-control'];
    
    views.forEach(viewId => {
        const element = document.getElementById(viewId);
        if (element) {
            element.style.display = route === `#/${viewId.replace('view-', '')}` ? 'block' : 'none';
        }
    });
}

// 初始化路由
if (typeof window !== 'undefined') {
    window.addEventListener('hashchange', renderRoute);
    window.addEventListener('load', renderRoute);
}
