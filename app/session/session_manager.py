"""
会话管理器
管理训练会话的创建、查找、销毁等操作
"""
import threading
from typing import Dict, Optional, List
from datetime import datetime, timedelta
from app.session.session_model import Session, SessionStatus
from app.config import Config


class SessionManager:
    """
    会话管理器（线程安全）
    
    负责：
    - 创建新会话
    - 查找会话
    - 更新会话状态
    - 清理过期会话
    - 管理并发会话数量
    """
    
    def __init__(self):
        """初始化会话管理器"""
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.RLock()  # 可重入锁，支持嵌套调用
        self._max_sessions = Config.MAX_CONCURRENT_SESSIONS
        self._timeout = Config.SESSION_TIMEOUT
    
    def create_session(
        self,
        student_id: Optional[int] = None,
        course_id: Optional[int] = None,
        course_item_id: Optional[int] = None,
        metadata: Optional[Dict] = None,
        training_session_id: Optional[str] = None,
        question_id: Optional[str] = None,
        question_index: int = 0,
    ) -> Session:
        """
        创建新会话
        
        Args:
            student_id: 学生ID
            course_id: 课程ID
            course_item_id: 课程项ID（可选）
            metadata: 额外的元数据
            training_session_id: 整次训练会话ID
            question_id: 题目窗口ID
            question_index: 题目序号
            
        Returns:
            Session对象
            
        Raises:
            RuntimeError: 如果达到最大并发会话数
        """
        with self._lock:
            # 检查并发会话数限制
            active_count = len([s for s in self._sessions.values() if s.is_active()])
            if active_count >= self._max_sessions:
                raise RuntimeError(
                    f"已达到最大并发会话数限制: {self._max_sessions}"
                )
            
            # 创建新会话
            session = Session(
                student_id=student_id,
                course_id=course_id,
                course_item_id=course_item_id,
                training_session_id=training_session_id,
                question_id=question_id,
                question_index=question_index,
                metadata=metadata or {}
            )
            
            # 设置文件路径
            recording_dir = Config.get_recording_path(session.session_id)
            result_dir = Config.get_result_path(session.session_id)
            
            session.video_file_path = str(Config.get_video_file_path(session.session_id))
            session.audio_file_path = str(Config.get_audio_file_path(session.session_id))
            session.result_file_path = str(Config.get_result_file_path(session.session_id))
            
            # 存储会话
            self._sessions[session.session_id] = session
            
            return session
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """
        获取会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            Session对象，如果不存在则返回None
        """
        with self._lock:
            return self._sessions.get(session_id)
    
    def update_session(self, session: Session):
        """
        更新会话（如果会话已存在）
        
        Args:
            session: 要更新的会话对象
        """
        with self._lock:
            if session.session_id in self._sessions:
                self._sessions[session.session_id] = session
    
    def end_session(self, session_id: str, status: SessionStatus = SessionStatus.COMPLETED):
        """
        结束会话
        
        Args:
            session_id: 会话ID
            status: 结束状态（默认为COMPLETED）
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                if status == SessionStatus.COMPLETED:
                    session.stop()
                elif status == SessionStatus.FAILED:
                    session.fail()
                elif status == SessionStatus.CANCELLED:
                    session.cancel()
    
    def remove_session(self, session_id: str):
        """
        移除会话（从内存中删除）
        
        Args:
            session_id: 会话ID
        """
        with self._lock:
            self._sessions.pop(session_id, None)
    
    def list_active_sessions(self) -> List[Session]:
        """
        获取所有活动会话列表
        
        Returns:
            活动会话列表
        """
        with self._lock:
            return [s for s in self._sessions.values() if s.is_active()]
    
    def list_all_sessions(self) -> List[Session]:
        """
        获取所有会话列表
        
        Returns:
            所有会话列表
        """
        with self._lock:
            return list(self._sessions.values())
    
    def get_sessions_by_student(self, student_id: int) -> List[Session]:
        """
        获取指定学生的所有会话
        
        Args:
            student_id: 学生ID
            
        Returns:
            会话列表
        """
        with self._lock:
            return [
                s for s in self._sessions.values()
                if s.student_id == student_id
            ]
    
    def get_sessions_by_course(self, course_id: int) -> List[Session]:
        """
        获取指定课程的所有会话
        
        Args:
            course_id: 课程ID
            
        Returns:
            会话列表
        """
        with self._lock:
            return [
                s for s in self._sessions.values()
                if s.course_id == course_id
            ]
    
    def cleanup_expired_sessions(self):
        """
        清理过期会话
        
        移除超过超时时间且未活动的会话
        """
        with self._lock:
            now = datetime.utcnow()
            expired_sessions = []
            
            for session_id, session in self._sessions.items():
                # 检查超时
                if session.started_at:
                    elapsed = (now - session.started_at).total_seconds()
                    if elapsed > self._timeout and session.is_active():
                        # 超时且仍在活动，标记为失败
                        session.fail(f"会话超时（{self._timeout}秒）")
                        expired_sessions.append(session_id)
                elif session.created_at:
                    # 已创建但未开始，检查创建时间
                    elapsed = (now - session.created_at).total_seconds()
                    if elapsed > self._timeout:
                        expired_sessions.append(session_id)
            
            # 移除过期会话
            for session_id in expired_sessions:
                self._sessions.pop(session_id, None)
            
            return len(expired_sessions)
    
    def get_statistics(self) -> Dict:
        """
        获取会话统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            total = len(self._sessions)
            active = len([s for s in self._sessions.values() if s.is_active()])
            completed = len([s for s in self._sessions.values() if s.status == SessionStatus.COMPLETED])
            failed = len([s for s in self._sessions.values() if s.status == SessionStatus.FAILED])
            
            return {
                'total': total,
                'active': active,
                'completed': completed,
                'failed': failed,
                'max_concurrent': self._max_sessions
            }


# 全局会话管理器实例（单例模式）
_session_manager: Optional[SessionManager] = None
_manager_lock = threading.Lock()


def get_session_manager() -> SessionManager:
    """
    获取全局会话管理器实例（单例模式）
    
    Returns:
        SessionManager实例
    """
    global _session_manager
    if _session_manager is None:
        with _manager_lock:
            if _session_manager is None:
                _session_manager = SessionManager()
    return _session_manager

