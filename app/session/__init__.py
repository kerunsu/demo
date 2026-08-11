"""
会话管理模块
管理训练会话的生命周期
"""
from app.session.session_manager import SessionManager, get_session_manager
from app.session.session_model import Session, SessionStatus

__all__ = ['SessionManager', 'get_session_manager', 'Session', 'SessionStatus']

