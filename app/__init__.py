"""
应用主模块
初始化Flask应用和核心组件
"""
from flask import Flask
from flask_socketio import SocketIO

# 全局对象，将在app.py中初始化
app = None
socketio = None

def create_app(config=None):
    """创建并配置Flask应用"""
    global app, socketio
    
    app = Flask(__name__)
    
    # 加载配置
    if config:
        app.config.update(config)
    else:
        from app.config import Config
        app.config.from_object(Config)
    
    # 初始化SocketIO
    socketio = SocketIO(app, cors_allowed_origins="*")
    
    # 初始化数据库
    from database.models import db
    db.init_app(app)
    
    # 注册蓝图和路由（后续添加）
    # register_blueprints(app)
    
    return app, socketio

def get_app():
    """获取全局Flask应用实例"""
    return app

def get_socketio():
    """获取全局SocketIO实例"""
    return socketio

