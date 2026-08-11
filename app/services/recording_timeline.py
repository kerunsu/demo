"""
整场连续录制：人类可读目录、timeline.csv、lookup 导出。

方案 B：一场一份 video/audio；切题只写时间轴标注，不启停媒体。
"""
from __future__ import annotations

import csv
import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import Config
from app.utils.logger import setup_logger

logger = setup_logger("recording_timeline")

TIMELINE_COLUMNS = [
    "seg_index",
    "seg_kind",
    "course_type_id",
    "course_item_id",
    "course_id",
    "question_id",
    "t_start_sec",
    "t_end_sec",
    "t_start_hms",
    "t_end_hms",
    "wall_start_iso",
    "wall_end_iso",
]

# media_session_id → 人类可读目录名（相对 sessions/）
_path_registry: Dict[str, str] = {}
_registry_lock = threading.RLock()
# media_session_id → 内存中的 RecordingSession
_active: Dict[str, "RecordingSession"] = {}


def sanitize_student_name(name: Optional[str], student_id: Optional[int] = None) -> str:
    raw = (name or "").strip()
    if not raw:
        return f"student{student_id}" if student_id is not None else "student"
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw)
    cleaned = cleaned.strip(" .")
    return cleaned or (f"student{student_id}" if student_id is not None else "student")


def format_age(age: Optional[int]) -> str:
    if age is None:
        return "NA"
    try:
        return str(int(age))
    except (TypeError, ValueError):
        return "NA"


def _sec_to_hms(sec: Optional[float]) -> str:
    if sec is None:
        return ""
    total = max(0, int(round(float(sec))))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def sessions_root() -> Path:
    root = Config.RECORDINGS_DIR / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def register_recording_dir(media_session_id: str, human_dir_name: str) -> Path:
    """登记 media_session_id → sessions/{human_dir_name}，并创建目录。"""
    with _registry_lock:
        _path_registry[media_session_id] = human_dir_name
    path = sessions_root() / human_dir_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def unregister_recording_dir(media_session_id: str) -> None:
    with _registry_lock:
        _path_registry.pop(media_session_id, None)
        _active.pop(media_session_id, None)


def resolve_recording_dir(media_session_id: str) -> Optional[Path]:
    with _registry_lock:
        name = _path_registry.get(media_session_id)
    if name:
        return sessions_root() / name

    # The in-memory registry is intentionally lightweight, but Runtime archive
    # retries can arrive after the Server has restarted.  Recover the mapping
    # from the authoritative per-session metadata and cache it for subsequent
    # requests instead of creating a second legacy directory named by UUID.
    wanted = str(media_session_id or "")
    if not wanted:
        return None
    root = sessions_root()
    try:
        children = list(root.iterdir())
    except OSError:
        return None
    for child in children:
        if not child.is_dir():
            continue
        for metadata_name, id_key in (
            ("session_meta.json", "mediaSessionId"),
            ("archive_meta.json", "sessionId"),
        ):
            metadata_path = child / metadata_name
            try:
                if not metadata_path.is_file():
                    continue
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(metadata, dict) and str(metadata.get(id_key) or "") == wanted:
                with _registry_lock:
                    _path_registry[wanted] = child.name
                return child
    return None


def allocate_human_dir_name(
    *,
    student_id: Optional[int],
    student_name: Optional[str],
    student_age: Optional[int],
    date_str: Optional[str] = None,
) -> Tuple[str, int]:
    """
    生成 {姓名}-{年龄}-{YYYYMMDD}-{N}，N 为同前缀已有目录最大序号 + 1。
    """
    name = sanitize_student_name(student_name, student_id)
    age = format_age(student_age)
    date_str = date_str or datetime.now().strftime("%Y%m%d")
    prefix = f"{name}-{age}-{date_str}-"
    root = sessions_root()
    max_n = 0
    pattern = re.compile(re.escape(prefix) + r"(\d+)$")
    try:
        for child in root.iterdir():
            if not child.is_dir():
                continue
            m = pattern.match(child.name)
            if m:
                max_n = max(max_n, int(m.group(1)))
    except FileNotFoundError:
        pass
    n = max_n + 1
    return f"{prefix}{n}", n


def load_student_label(student_id: Optional[int]) -> Tuple[Optional[str], Optional[int]]:
    if student_id is None:
        return None, None
    try:
        from database.models import Student

        student = Student.query.get(int(student_id))
        if not student:
            return None, None
        return student.name, student.age
    except Exception as e:
        logger.warning("读取学生信息失败: student_id=%s err=%s", student_id, e)
        return None, None


def resolve_course_type_id(course_id: Optional[int]) -> Optional[int]:
    if not course_id:
        return None
    try:
        from database.models import Course

        course = Course.query.get(int(course_id))
        if course:
            return course.course_type_id
    except Exception as e:
        logger.warning("解析 course_type_id 失败: course_id=%s err=%s", course_id, e)
    return None


@dataclass
class TimelineSegment:
    seg_index: int
    seg_kind: str
    course_type_id: Optional[int] = None
    course_item_id: Optional[int] = None
    course_id: Optional[int] = None
    question_id: str = ""
    t_start_sec: float = 0.0
    t_end_sec: Optional[float] = None
    wall_start_iso: str = ""
    wall_end_iso: str = ""

    def to_row(self) -> Dict[str, Any]:
        return {
            "seg_index": self.seg_index,
            "seg_kind": self.seg_kind,
            "course_type_id": self.course_type_id if self.course_type_id is not None else "",
            "course_item_id": self.course_item_id if self.course_item_id is not None else "",
            "course_id": self.course_id if self.course_id is not None else "",
            "question_id": self.question_id or "",
            "t_start_sec": f"{self.t_start_sec:.3f}",
            "t_end_sec": "" if self.t_end_sec is None else f"{self.t_end_sec:.3f}",
            "t_start_hms": _sec_to_hms(self.t_start_sec),
            "t_end_hms": _sec_to_hms(self.t_end_sec),
            "wall_start_iso": self.wall_start_iso or "",
            "wall_end_iso": self.wall_end_iso or "",
        }


@dataclass
class RecordingSession:
    media_session_id: str
    training_session_id: str
    human_dir_name: str
    student_id: Optional[int]
    recording_started_at: float
    recording_started_iso: str
    status: str = "recording"  # recording | finalized | cancelled
    n: int = 1
    segments: List[TimelineSegment] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def dir_path(self) -> Path:
        return sessions_root() / self.human_dir_name

    def now_offset(self) -> float:
        return max(0.0, time.time() - self.recording_started_at)

    def append_segment(
        self,
        *,
        seg_kind: str,
        course_type_id: Optional[int] = None,
        course_item_id: Optional[int] = None,
        course_id: Optional[int] = None,
        question_id: str = "",
        t_start_sec: Optional[float] = None,
        wall_start_iso: Optional[str] = None,
    ) -> TimelineSegment:
        with self._lock:
            t0 = self.now_offset() if t_start_sec is None else float(t_start_sec)
            wall = wall_start_iso or datetime.now().isoformat(timespec="seconds")
            # 关闭上一未结束段
            if self.segments and self.segments[-1].t_end_sec is None:
                prev = self.segments[-1]
                prev.t_end_sec = t0
                prev.wall_end_iso = wall
            seg = TimelineSegment(
                seg_index=len(self.segments),
                seg_kind=seg_kind,
                course_type_id=course_type_id,
                course_item_id=course_item_id,
                course_id=course_id,
                question_id=question_id or "",
                t_start_sec=t0,
                wall_start_iso=wall,
            )
            self.segments.append(seg)
            self._flush_csv_unlocked()
            return seg

    def finalize(self, *, status: str = "finalized", duration_sec: Optional[float] = None) -> Path:
        with self._lock:
            end_t = float(duration_sec) if duration_sec is not None else self.now_offset()
            wall = datetime.now().isoformat(timespec="seconds")
            if self.segments and self.segments[-1].t_end_sec is None:
                self.segments[-1].t_end_sec = end_t
                self.segments[-1].wall_end_iso = wall
            self.status = status
            path = self._flush_csv_unlocked()
            self._write_meta_unlocked(duration_sec=end_t)
            return path

    def _flush_csv_unlocked(self) -> Path:
        path = self.dir_path / "timeline.csv"
        self.dir_path.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=TIMELINE_COLUMNS)
            writer.writeheader()
            for seg in self.segments:
                writer.writerow(seg.to_row())
        return path

    def _write_meta_unlocked(self, *, duration_sec: Optional[float] = None) -> Path:
        meta = {
            "mediaSessionId": self.media_session_id,
            "trainingSessionId": self.training_session_id,
            "humanDirName": self.human_dir_name,
            "studentId": self.student_id,
            "n": self.n,
            "status": self.status,
            "recordingStartedAt": self.recording_started_iso,
            "recordingStartedAtUnix": self.recording_started_at,
            "durationSec": duration_sec,
            "recordingMode": "continuous",
            "segCount": len(self.segments),
        }
        path = self.dir_path / "session_meta.json"
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def write_session_meta_skeleton(self) -> Path:
        with self._lock:
            return self._write_meta_unlocked()


def begin_recording_session(
    *,
    media_session_id: str,
    training_session_id: str,
    student_id: Optional[int],
    human_dir_name: str,
    n: int,
) -> RecordingSession:
    started = time.time()
    iso = datetime.now().isoformat(timespec="seconds")
    register_recording_dir(media_session_id, human_dir_name)
    rs = RecordingSession(
        media_session_id=media_session_id,
        training_session_id=training_session_id,
        human_dir_name=human_dir_name,
        student_id=student_id,
        recording_started_at=started,
        recording_started_iso=iso,
        n=n,
    )
    rs.write_session_meta_skeleton()
    # warmup 从 t=0
    rs.append_segment(
        seg_kind="warmup",
        question_id=f"{training_session_id}_warmup",
        t_start_sec=0.0,
        wall_start_iso=iso,
    )
    with _registry_lock:
        _active[media_session_id] = rs
    logger.info(
        "开始连续录制会话: media=%s human=%s training=%s",
        media_session_id, human_dir_name, training_session_id,
    )
    return rs


def get_recording_session(media_session_id: str) -> Optional[RecordingSession]:
    with _registry_lock:
        return _active.get(media_session_id)


def get_recording_session_by_training(training_session_id: str) -> Optional[RecordingSession]:
    with _registry_lock:
        for rs in _active.values():
            if rs.training_session_id == training_session_id:
                return rs
    return None


def list_active_recording_sessions() -> List["RecordingSession"]:
    """返回当前内存中的活跃连续录制会话（方案 B）。"""
    with _registry_lock:
        return list(_active.values())


def mark_course_segment(
    media_session_id: str,
    *,
    course_id: Optional[int],
    course_item_id: Optional[int],
    course_type_id: Optional[int],
    question_id: str,
) -> Optional[TimelineSegment]:
    rs = get_recording_session(media_session_id)
    if not rs:
        logger.warning("mark_course_segment: 无活跃录制会话 media=%s", media_session_id)
        return None
    return rs.append_segment(
        seg_kind="course",
        course_type_id=course_type_id,
        course_item_id=course_item_id,
        course_id=course_id,
        question_id=question_id,
    )


def finalize_recording_session(
    media_session_id: str,
    *,
    status: str = "finalized",
    duration_sec: Optional[float] = None,
) -> Optional[Path]:
    rs = get_recording_session(media_session_id)
    if not rs:
        return None
    path = rs.finalize(status=status, duration_sec=duration_sec)
    with _registry_lock:
        _active.pop(media_session_id, None)
    logger.info(
        "结束连续录制: media=%s status=%s timeline=%s",
        media_session_id, status, path,
    )
    return path


# ---------------------------------------------------------------------------
# Lookup CSV
# ---------------------------------------------------------------------------

COURSE_TYPE_NAME_EN = {
    "命名": "naming",
    "拟声": "onomatopoeia",
    "模仿": "imitation",
    "配对": "pairing",
    "排序": "ordering",
}


def export_recording_lookups(target_dir: Optional[Path] = None) -> Dict[str, str]:
    """从 DB 导出 course_type_lookup.csv / course_item_lookup.csv 到录制根目录。"""
    out_dir = Path(target_dir) if target_dir else Config.RECORDINGS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    from database.models import CourseType, CourseItem, Course

    type_path = out_dir / "course_type_lookup.csv"
    item_path = out_dir / "course_item_lookup.csv"

    types = CourseType.query.order_by(CourseType.id).all()
    with type_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["course_type_id", "name", "name_en"])
        writer.writeheader()
        for ct in types:
            writer.writerow({
                "course_type_id": ct.id,
                "name": ct.name,
                "name_en": COURSE_TYPE_NAME_EN.get(ct.name, ""),
            })

    items = CourseItem.query.order_by(CourseItem.id).all()
    course_cache: Dict[int, Any] = {}
    with item_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["course_item_id", "course_id", "course_type_id", "name", "media_file"],
        )
        writer.writeheader()
        for it in items:
            course = course_cache.get(it.course_id)
            if course is None and it.course_id is not None:
                course = Course.query.get(it.course_id)
                course_cache[it.course_id] = course
            writer.writerow({
                "course_item_id": it.id,
                "course_id": it.course_id,
                "course_type_id": course.course_type_id if course else "",
                "name": it.name or "",
                "media_file": it.media_file or "",
            })

    logger.info("已导出 recording lookups: %s, %s", type_path, item_path)
    return {
        "course_type_lookup": str(type_path),
        "course_item_lookup": str(item_path),
    }
