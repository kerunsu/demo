"""
行为观测持久化：内存索引 + JSON 文件
目录：static/recordings/behavior/{training_session_id}/
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import Config
from app.behavior.models import (
    AttentionObservation,
    EmotionObservation,
    InteractionEvent,
    LanguageObservation,
    QuestionWindow,
    SessionBehaviorSummary,
    TrainingSessionRecord,
)
from app.utils.logger import setup_logger

logger = setup_logger("behavior_store")


class BehaviorStore:
    def __init__(self, base_dir: Optional[Path] = None):
        self._base = Path(base_dir) if base_dir else (Config.RECORDINGS_DIR / "behavior")
        self._base.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._trainings: Dict[str, TrainingSessionRecord] = {}
        self._windows: Dict[str, Dict[str, QuestionWindow]] = {}  # ts_id -> qid -> window
        self._attention: Dict[str, List[AttentionObservation]] = {}
        self._language: Dict[str, List[LanguageObservation]] = {}
        self._emotion: Dict[str, List[EmotionObservation]] = {}
        self._interaction_events: Dict[str, List[InteractionEvent]] = {}
        self._summaries: Dict[str, SessionBehaviorSummary] = {}
        self._active_by_student: Dict[int, str] = {}  # student_id -> training_session_id

    @property
    def root(self) -> Path:
        return self._base

    def _dir(self, training_session_id: str) -> Path:
        d = self._base / training_session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_path, path)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _append_jsonl(self, path: Path, record: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    # ---- training ----
    def save_training(self, record: TrainingSessionRecord) -> None:
        with self._lock:
            self._trainings[record.training_session_id] = record
            if record.student_id is not None and record.status == "active":
                self._active_by_student[record.student_id] = record.training_session_id
            elif record.student_id is not None and record.status == "finalized":
                if self._active_by_student.get(record.student_id) == record.training_session_id:
                    self._active_by_student.pop(record.student_id, None)
            path = self._dir(record.training_session_id) / "training.json"
            self._write_json(path, record.to_dict())

    def get_training(self, training_session_id: str) -> Optional[TrainingSessionRecord]:
        with self._lock:
            if training_session_id in self._trainings:
                return self._trainings[training_session_id]
            self._load_training_from_disk(training_session_id)
            return self._trainings.get(training_session_id)

    def _load_training_from_disk(self, training_session_id: str) -> None:
        """按需从磁盘回填 training / windows / 观测（服务重启后 refresh 依赖此路径）。"""
        d = self._base / training_session_id
        if not d.exists():
            return
        try:
            tpath = d / "training.json"
            if tpath.exists() and training_session_id not in self._trainings:
                data = json.loads(tpath.read_text(encoding="utf-8"))
                fields = TrainingSessionRecord.__dataclass_fields__
                self._trainings[training_session_id] = TrainingSessionRecord(
                    **{k: data.get(k) for k in fields if k in data or k == "training_session_id"}
                )
            wdir = d / "windows"
            if wdir.exists() and training_session_id not in self._windows:
                bucket: Dict[str, QuestionWindow] = {}
                for wp in wdir.glob("*.json"):
                    try:
                        data = json.loads(wp.read_text(encoding="utf-8"))
                        fields = QuestionWindow.__dataclass_fields__
                        win = QuestionWindow(**{k: data.get(k) for k in fields if k in data})
                        bucket[win.question_id] = win
                    except Exception as e:
                        logger.warning("读取窗口失败 %s: %s", wp, e)
                self._windows[training_session_id] = bucket
            apath = d / "attention.jsonl"
            if apath.exists() and training_session_id not in self._attention:
                items: List[AttentionObservation] = []
                for line in apath.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        fields = AttentionObservation.__dataclass_fields__
                        items.append(AttentionObservation(**{k: data.get(k) for k in fields if k in data}))
                    except Exception:
                        continue
                self._attention[training_session_id] = items
            lpath = d / "language.jsonl"
            if lpath.exists() and training_session_id not in self._language:
                items_l: List[LanguageObservation] = []
                for line in lpath.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        fields = LanguageObservation.__dataclass_fields__
                        items_l.append(LanguageObservation(**{k: data.get(k) for k in fields if k in data}))
                    except Exception:
                        continue
                self._language[training_session_id] = items_l
            epath = d / "emotion.jsonl"
            if epath.exists() and training_session_id not in self._emotion:
                items_e: List[EmotionObservation] = []
                for line in epath.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        fields = EmotionObservation.__dataclass_fields__
                        items_e.append(EmotionObservation(**{k: data.get(k) for k in fields if k in data}))
                    except Exception:
                        continue
                self._emotion[training_session_id] = items_e
            ipath = d / "interaction_timeline.jsonl"
            if ipath.exists() and training_session_id not in self._interaction_events:
                events: List[InteractionEvent] = []
                for line in ipath.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        fields = InteractionEvent.__dataclass_fields__
                        events.append(InteractionEvent(**{
                            k: data.get(k) for k in fields if k in data
                        }))
                    except Exception:
                        continue
                self._interaction_events[training_session_id] = events
        except Exception as e:
            logger.warning("从磁盘加载 behavior 失败 training=%s: %s", training_session_id, e)

    def get_active_training_id(self, student_id: int) -> Optional[str]:
        with self._lock:
            return self._active_by_student.get(student_id)

    def list_active_training_ids(self) -> List[str]:
        """返回当前标记为 active 的训练会话 ID（按登记顺序）。"""
        with self._lock:
            seen = set()
            ids: List[str] = []
            for tid in self._active_by_student.values():
                if tid and tid not in seen:
                    seen.add(tid)
                    ids.append(tid)
            for tid, rec in self._trainings.items():
                if rec.status == "active" and tid not in seen:
                    seen.add(tid)
                    ids.append(tid)
            return ids

    # ---- windows ----
    def save_window(self, window: QuestionWindow) -> None:
        with self._lock:
            self._windows.setdefault(window.training_session_id, {})[window.question_id] = window
            path = self._dir(window.training_session_id) / "windows" / f"{window.question_id}.json"
            self._write_json(path, window.to_dict())

    def get_window(self, training_session_id: str, question_id: str) -> Optional[QuestionWindow]:
        with self._lock:
            if training_session_id not in self._windows:
                self._load_training_from_disk(training_session_id)
            return self._windows.get(training_session_id, {}).get(question_id)

    def list_windows(self, training_session_id: str) -> List[QuestionWindow]:
        with self._lock:
            if training_session_id not in self._windows:
                self._load_training_from_disk(training_session_id)
            windows = list(self._windows.get(training_session_id, {}).values())
            windows.sort(key=lambda w: w.question_index)
            return windows

    # ---- observations ----
    def add_attention(self, obs: AttentionObservation) -> None:
        with self._lock:
            self._attention.setdefault(obs.training_session_id, []).append(obs)
            path = self._dir(obs.training_session_id) / "attention.jsonl"
            self._append_jsonl(path, obs.to_dict())

    def add_language(self, obs: LanguageObservation) -> None:
        with self._lock:
            self._language.setdefault(obs.training_session_id, []).append(obs)
            path = self._dir(obs.training_session_id) / "language.jsonl"
            self._append_jsonl(path, obs.to_dict())

    def add_emotion(self, obs: EmotionObservation) -> None:
        with self._lock:
            self._emotion.setdefault(obs.training_session_id, []).append(obs)
            path = self._dir(obs.training_session_id) / "emotion.jsonl"
            self._append_jsonl(path, obs.to_dict())

    def add_interaction_event(self, event: InteractionEvent) -> None:
        with self._lock:
            self._interaction_events.setdefault(
                event.training_session_id, []
            ).append(event)
            path = self._dir(event.training_session_id) / "interaction_timeline.jsonl"
            self._append_jsonl(path, event.to_dict())

    def list_interaction_events(
        self,
        training_session_id: str,
        question_id: Optional[str] = None,
    ) -> List[InteractionEvent]:
        with self._lock:
            if training_session_id not in self._interaction_events:
                self._load_training_from_disk(training_session_id)
            events = self._interaction_events.get(training_session_id, [])
            if question_id:
                return [event for event in events if event.question_id == question_id]
            return list(events)

    def list_attention(
        self, training_session_id: str, question_id: Optional[str] = None
    ) -> List[AttentionObservation]:
        with self._lock:
            if training_session_id not in self._attention:
                self._load_training_from_disk(training_session_id)
            items = self._attention.get(training_session_id, [])
            if question_id:
                return [o for o in items if o.question_id == question_id]
            return list(items)

    def list_language(
        self, training_session_id: str, question_id: Optional[str] = None
    ) -> List[LanguageObservation]:
        with self._lock:
            if training_session_id not in self._language:
                self._load_training_from_disk(training_session_id)
            items = self._language.get(training_session_id, [])
            if question_id:
                return [o for o in items if o.question_id == question_id]
            return list(items)

    def list_emotion(
        self, training_session_id: str, question_id: Optional[str] = None
    ) -> List[EmotionObservation]:
        with self._lock:
            if training_session_id not in self._emotion:
                self._load_training_from_disk(training_session_id)
            items = self._emotion.get(training_session_id, [])
            if question_id:
                return [o for o in items if o.question_id == question_id]
            return list(items)

    # ---- summary / report ----
    def save_summary(self, summary: SessionBehaviorSummary) -> None:
        with self._lock:
            self._summaries[summary.training_session_id] = summary
            path = self._dir(summary.training_session_id) / "session_summary.json"
            self._write_json(path, summary.to_dict())

    def get_summary(self, training_session_id: str) -> Optional[SessionBehaviorSummary]:
        with self._lock:
            if training_session_id in self._summaries:
                return self._summaries[training_session_id]
            path = self._dir(training_session_id) / "session_summary.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    summary = SessionBehaviorSummary(**{
                        k: data.get(k) for k in SessionBehaviorSummary.__dataclass_fields__
                    })
                    self._summaries[training_session_id] = summary
                    return summary
                except Exception as e:
                    logger.warning("读取 session_summary 失败: %s", e)
            return None

    def save_report(self, training_session_id: str, report: Dict[str, Any]) -> Path:
        path = self._dir(training_session_id) / "report.json"
        self._write_json(path, report)
        return path

    def get_report(self, training_session_id: str) -> Optional[Dict[str, Any]]:
        path = self._dir(training_session_id) / "report.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("读取 report 失败: %s", e)
            return None

    def save_manual_report(self, training_session_id: str, report: Dict[str, Any]) -> Path:
        path = self._dir(training_session_id) / "report.manual.json"
        self._write_json(path, report)
        return path

    def get_manual_report(self, training_session_id: str) -> Optional[Dict[str, Any]]:
        path = self._dir(training_session_id) / "report.manual.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("读取 report.manual 失败: %s", e)
            return None

    def clear_manual_report(self, training_session_id: str) -> None:
        path = self._dir(training_session_id) / "report.manual.json"
        if path.exists():
            try:
                path.unlink()
            except Exception as e:
                logger.warning("删除 report.manual 失败: %s", e)

    def save_published_report(self, training_session_id: str, report: Dict[str, Any]) -> Path:
        path = self._dir(training_session_id) / "report.published.json"
        self._write_json(path, report)
        return path

    def get_published_report(self, training_session_id: str) -> Optional[Dict[str, Any]]:
        path = self._dir(training_session_id) / "report.published.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("读取 report.published 失败: %s", e)
            return None

    def get_publication_status(self, training_session_id: str) -> str:
        published = self.get_published_report(training_session_id)
        if published:
            return "published"
        report = self.get_report(training_session_id)
        if not report:
            return "none"
        status = report.get("publicationStatus")
        if status:
            return str(status)
        # 旧报告无审核字段：兼容为已对教师可见
        return "published"


_store: Optional[BehaviorStore] = None
_store_lock = threading.Lock()


def get_behavior_store() -> BehaviorStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = BehaviorStore()
    return _store
