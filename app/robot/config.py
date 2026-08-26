"""
机械臂系统配置
OSC 通信参数和数据文件路径
"""
import os

# OSC 配置（与 DollSer C++ 程序通信）
OSC_IP = os.environ.get('OSC_IP', '127.0.0.1')
OSC_PORT = int(os.environ.get('OSC_PORT', 12000))
SERVO_TIME = int(os.environ.get('SERVO_TIME', 100))  # 舵机移动时间参数

# 静态姿势回归缓冲（秒）。短暂保留普通动作的末姿态，再柔和进入“空动作”；
# 调度器会在新动作到达时立即取消这个计时，不会拖慢教师的下一次操作。
IDLE_POSE_DELAY = float(os.environ.get('IDLE_POSE_DELAY', 0.6))

# 机械臂控制模式
# - server_osc: 由服务端直接发送 OSC 到 DollSer（仅后端与 DollSer 同机）
# - child_agent: 由机器人端网页转发到本机 Agent，再发 OSC（兼容）
# - robot_runtime: 后端 HTTP 直连机器人端统一 Runtime（跨机推荐）
# 默认 robot_runtime；配置中心应用后写入 config/runtime_modes.yaml
ROBOT_CONTROL_MODE = os.environ.get('ROBOT_CONTROL_MODE', 'robot_runtime')

# child_agent 模式下，机器人动作事件广播目标房间（为空表示全局广播）
ROBOT_CHILD_ROOM = os.environ.get('ROBOT_CHILD_ROOM', '')

# robot_runtime 模式：与 Runtime 共享的密钥（请求头 X-Robot-Runtime-Key）
ROBOT_RUNTIME_KEY = os.environ.get(
    'ROBOT_RUNTIME_KEY',
    os.environ.get('CHILD_MEDIA_AGENT_KEY', ''),
)
ROBOT_RUNTIME_HTTP_TIMEOUT = float(os.environ.get('ROBOT_RUNTIME_HTTP_TIMEOUT', 5))

VALID_ROBOT_CONTROL_MODES = ('server_osc', 'child_agent', 'robot_runtime')

# 数据文件路径（相对于项目根目录）
ROBOT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'doll', 'data')
MOTIONS_FILE = os.path.join(ROBOT_DATA_DIR, 'motions.json')
COURSE_MAP_FILE = os.path.join(ROBOT_DATA_DIR, 'course_map.json')
STUDENTS_FILE = os.path.join(ROBOT_DATA_DIR, 'students.json')
COURSES_FILE = os.path.join(ROBOT_DATA_DIR, 'courses.json')


def ensure_data_files():
    """确保数据文件存在"""
    import json
    
    # 创建数据目录
    if not os.path.exists(ROBOT_DATA_DIR):
        os.makedirs(ROBOT_DATA_DIR, exist_ok=True)
    
    # 初始化 motions.json（新格式：version + motions）
    if not os.path.exists(MOTIONS_FILE):
        with open(MOTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'version': 1,
                'updatedAt': None,
                'motions': {}
            }, f, indent=2, ensure_ascii=False)
    
    # 初始化 course_map.json
    if not os.path.exists(COURSE_MAP_FILE):
        with open(COURSE_MAP_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'defaults': {},
                'courses': {},
                'students': {}
            }, f, indent=2)
    
    # 初始化 students.json
    if not os.path.exists(STUDENTS_FILE):
        with open(STUDENTS_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=2)
    
    # 初始化 courses.json
    if not os.path.exists(COURSES_FILE):
        with open(COURSES_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=2)

    # 初始化 emotions_meta.json（默认表情）
    from app.robot.emotion_assets import ensure_emotions_meta
    ensure_emotions_meta()
    from app.robot.animation_assets import ensure_animations_dir
    ensure_animations_dir()
