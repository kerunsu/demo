"""行为观测持久化：内存索引 + JSON 文件。

新会话与 ``sessions`` 使用同一个易读目录名，例如
``static/recordings/behavior/姓名-年龄-YYYYMMDD-N/``。训练 UUID 仍然是文件内的
稳定主键；历史 ``behavior/{training_session_id}`` 目录继续按原路径读取。
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
        self._directories: Dict[str, Path] = {}

    @property
    def root(self) -> Path:
        return self._base

    @staticmethod
    def _validate_directory_name(value: Any) -> str:
        name = str(value or "").strip()
        if not name or name in {".", ".."} or Path(name).name != name:
            raise ValueError("behavior_directory_name_invalid")
        return name

    @staticmethod
    def _record_directory_name(record: TrainingSessionRecord) -> Optional[str]:
        metadata = record.metadata if isinstance(record.metadata, dict) else {}
        value = metadata.get("human_dir_name") or metadata.get("humanDirName")
        return str(value).strip() if value else None

    def _find_dir(self, training_session_id: str) -> Optional[Path]:
        """Resolve a training directory without creating filesystem state."""
        key = str(training_session_id or "").strip()
        if not key:
            return None
        cached = self._directories.get(key)
        if cached is not None:
            return cached

        # Historical layout: behavior/{training_session_id}/.
        legacy = self._base / key
        if legacy.is_dir():
            self._directories[key] = legacy
            return legacy

        # New layout: behavior/{human_dir_name}/, with the UUID in training.json.
        try:
            children = list(self._base.iterdir())
        except OSError:
            return None
        for child in children:
            training_path = child / "training.json"
            if not child.is_dir() or not training_path.is_file():
                continue
            try:
                data = json.loads(training_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if (
                isinstance(data, dict)
                and str(data.get("training_session_id") or "") == key
            ):
                self._directories[key] = child
                return child
        return None

    def _write_dir(self, training_session_id: str) -> Path:
        """Resolve the authoritative directory and create it only for a write."""
        key = str(training_session_id or "").strip()
        if not key:
            raise ValueError("training_session_id_required")
        existing = self._find_dir(key)
        if existing is not None:
            return existing
        record = self._trainings.get(key)
        preferred = self._record_directory_name(record) if record else None
        name = self._validate_directory_name(preferred or key)
        directory = self._base / name
        directory.mkdir(parents=True, exist_ok=True)
        self._directories[key] = directory
        return directory

    def bind_directory(self, training_session_id: str, human_dir_name: str) -> Path:
        """Bind behavior output to the readable media-session directory name.

        Binding itself does not create an empty directory. Existing historical
        UUID directories are retained in place; this method never migrates stored
        session data implicitly.
        """
        with self._lock:
            key = str(training_session_id or "").strip()
            if not key:
                raise ValueError("training_session_id_required")
            name = self._validate_directory_name(human_dir_name)
            target = self._base / name
            current = self._find_dir(key)
            if current is not None and current != target:
                logger.warning(
                    "保留历史 behavior 目录: training=%s current=%s requested=%s",
                    key, current, target,
                )
                return current
            if current is None and target.exists():
                owner = None
                training_path = target / "training.json"
                try:
                    data = json.loads(training_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        owner = str(data.get("training_session_id") or "") or None
                except (OSError, ValueError, TypeError):
                    pass
                if owner != key:
                    raise ValueError(f"behavior_directory_already_exists:{name}")
            self._directories[key] = target
            record = self._trainings.get(key)
            if record is not None:
                metadata = dict(record.metadata or {})
                metadata["human_dir_name"] = name
                metadata["directory_schema"] = "readable-session-v1"
                record.metadata = metadata
                self.save_training(record)
            return target

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
            path = self._write_dir(record.training_session_id) / "training.json"
            self._write_json(path, record.to_dict())

    def get_training(self, training_session_id: str) -> Optional[TrainingSessionRecord]:
        with self._lock:
            if training_session_id in self._trainings:
                return self._trainings[training_session_id]
            self._load_training_from_disk(training_session_id)
            return self._trainings.get(training_session_id)

    def _load_training_from_disk(self, training_session_id: str) -> None:
        """按需从磁盘回填 training / windows / 观测（服务重启后 refresh 依赖此路径）。"""
        d = self._find_dir(training_session_id)
        if d is None:
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

    def list_persisted_training_ids(self) -> List[str]:
        """List stored training IDs, independent of directory naming layout."""
        with self._lock:
            try:
                directories = sorted(
                    (item for item in self._base.iterdir() if item.is_dir()),
                    key=lambda item: item.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                return []
            result: List[str] = []
            seen = set()
            for directory in directories:
                training_id = None
                training_path = directory / "training.json"
                try:
                    data = json.loads(training_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and data.get("training_session_id"):
                        training_id = str(data["training_session_id"])
                except (OSError, ValueError, TypeError):
                    pass
                # Legacy directories used the training UUID as their name. A
                # report-only historical directory may not have training.json.
                training_id = training_id or directory.name
                if training_id in seen:
                    continue
                seen.add(training_id)
                self._directories.setdefault(training_id, directory)
                result.append(training_id)
            return result

    # ---- windows ----
    def save_window(self, window: QuestionWindow) -> None:
        with self._lock:
            self._windows.setdefault(window.training_session_id, {})[window.question_id] = window
            path = self._write_dir(window.training_session_id) / "windows" / f"{window.question_id}.json"
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
            path = self._write_dir(obs.training_session_id) / "attention.jsonl"
            self._append_jsonl(path, obs.to_dict())

    def add_language(self, obs: LanguageObservation) -> None:
        with self._lock:
            self._language.setdefault(obs.training_session_id, []).append(obs)
            path = self._write_dir(obs.training_session_id) / "language.jsonl"
            self._append_jsonl(path, obs.to_dict())

    def add_emotion(self, obs: EmotionObservation) -> None:
        with self._lock:
            self._emotion.setdefault(obs.training_session_id, []).append(obs)
            path = self._write_dir(obs.training_session_id) / "emotion.jsonl"
            self._append_jsonl(path, obs.to_dict())

    def add_interaction_event(self, event: InteractionEvent) -> None:
        with self._lock:
            self._interaction_events.setdefault(
                event.training_session_id, []
            ).append(event)
            path = self._write_dir(event.training_session_id) / "interaction_timeline.jsonl"
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
            path = self._write_dir(summary.training_session_id) / "session_summary.json"
            self._write_json(path, summary.to_dict())

    def get_summary(self, training_session_id: str) -> Optional[SessionBehaviorSummary]:
        with self._lock:
            if training_session_id in self._summaries:
                return self._summaries[training_session_id]
            directory = self._find_dir(training_session_id)
            if directory is None:
                return None
            path = directory / "session_summary.json"
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
        path = self._write_dir(training_session_id) / "report.json"
        self._write_json(path, report)
        return path

    def get_report(self, training_session_id: str) -> Optional[Dict[str, Any]]:
        directory = self._find_dir(training_session_id)
        if directory is None:
            return None
        path = directory / "report.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("读取 report 失败: %s", e)
            return None

    def save_manual_report(self, training_session_id: str, report: Dict[str, Any]) -> Path:
        path = self._write_dir(training_session_id) / "report.manual.json"
        self._write_json(path, report)
        return path

    def get_manual_report(self, training_session_id: str) -> Optional[Dict[str, Any]]:
        directory = self._find_dir(training_session_id)
        if directory is None:
            return None
        path = directory / "report.manual.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("读取 report.manual 失败: %s", e)
            return None

    def clear_manual_report(self, training_session_id: str) -> None:
        directory = self._find_dir(training_session_id)
        if directory is None:
            return
        path = directory / "report.manual.json"
        if path.exists():
            try:
                path.unlink()
            except Exception as e:
                logger.warning("删除 report.manual 失败: %s", e)

    def save_published_report(self, training_session_id: str, report: Dict[str, Any]) -> Path:
        path = self._write_dir(training_session_id) / "report.published.json"
        self._write_json(path, report)
        return path

    def get_published_report(self, training_session_id: str) -> Optional[Dict[str, Any]]:
        directory = self._find_dir(training_session_id)
        if directory is None:
            return None
        path = directory / "report.published.json"
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
