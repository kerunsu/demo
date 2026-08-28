"""Demo 课程输出兼容常量。

机械/Runtime 常量只供未激活的旧实现完成导入；有效控制模式永久为 disabled。
"""
import os

# OSC 配置（与 DollSer C++ 程序通信）
OSC_IP = os.environ.get('OSC_IP', '127.0.0.1')
OSC_PORT = int(os.environ.get('OSC_PORT', 12000))
SERVO_TIME = int(os.environ.get('SERVO_TIME', 100))  # 舵机移动时间参数

# 静态姿势回归缓冲（秒）。短暂保留普通动作的末姿态，再柔和进入“空动作”；
# 调度器会在新动作到达时立即取消这个计时，不会拖慢教师的下一次操作。
IDLE_POSE_DELAY = float(os.environ.get('IDLE_POSE_DELAY', 0.6))

# Demo 不允许任何机械控制模式。
ROBOT_CONTROL_MODE = 'disabled'

# child_agent 模式下，机器人动作事件广播目标房间（为空表示全局广播）
ROBOT_CHILD_ROOM = os.environ.get('ROBOT_CHILD_ROOM', '')

# robot_runtime 模式：与 Runtime 共享的密钥（请求头 X-Robot-Runtime-Key）
ROBOT_RUNTIME_KEY = os.environ.get(
    'ROBOT_RUNTIME_KEY',
    os.environ.get('CHILD_MEDIA_AGENT_KEY', ''),
)
ROBOT_RUNTIME_HTTP_TIMEOUT = float(os.environ.get('ROBOT_RUNTIME_HTTP_TIMEOUT', 5))

VALID_ROBOT_CONTROL_MODES = ('disabled',)

# 数据文件路径（相对于项目根目录）
ROBOT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'doll', 'data')
MOTIONS_FILE = os.path.join(ROBOT_DATA_DIR, 'motions.json')
COURSE_MAP_FILE = os.path.join(ROBOT_DATA_DIR, 'course_map.json')
STUDENTS_FILE = os.path.join(ROBOT_DATA_DIR, 'students.json')
COURSES_FILE = os.path.join(ROBOT_DATA_DIR, 'courses.json')

# 显式的表扬动画随机模式。空字符串仍表示继承/不播放，只有该值才
# 允许从经审核的 animations 池中随机选择；它不涉及任何机械动作。
PRAISE_RANDOM_ANIMATION = '__random_praise_animation__'


def ensure_data_files():
    """确保数据文件存在"""
    import json
    
    # 创建数据目录
    if not os.path.exists(ROBOT_DATA_DIR):
        os.makedirs(ROBOT_DATA_DIR, exist_ok=True)
    
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

    # Demo 仅使用儿童屏鼓励动画。机械动作与完整版机器人表情属于明确
    # 禁用能力，启动过程不能重新生成对应资源文件。
    from app.robot.animation_assets import ensure_animations_dir
    ensure_animations_dir()
