import threading
from types import SimpleNamespace

from flask import Flask

from app.sockets import events


class _Robot:
    def __init__(self):
        self.calls = []

    def reserve_audio_only_behavior(self, **kwargs):
        self.calls.append(("reserve_audio", kwargs))
        return {"accepted": True, "behaviorId": kwargs["behavior_id"]}

    def reserve_behavior(self, **kwargs):
        self.calls.append(("reserve", kwargs))
        return {"accepted": True, "behaviorId": kwargs["behavior_id"]}

    def trigger_course_event(self, payload):
        self.calls.append(("trigger", payload))
        return {"success": True, "scheduledDelayMs": 0}

    def resolve_audio_offset_ms(self, payload):
        return 0

    def set_behavior_audio_expected(self, behavior_id, count, **kwargs):
        self.calls.append(("commit", behavior_id, count, kwargs))
        return True

    def abort_behavior(self, behavior_id):
        self.calls.append(("abort", behavior_id))
        return True


class _Audio:
    def __init__(self):
        self.calls = []

    def play_interactive_course_audio(self, **kwargs):
        self.calls.append(kwargs)
        return True


class _BusyRobot(_Robot):
    def reserve_behavior(self, **kwargs):
        self.calls.append(("reserve", kwargs))
        return {
            "accepted": False,
            "activeBehaviorId": "behavior-already-playing",
        }


class _BusyOnceRobot(_Robot):
    def __init__(self):
        super().__init__()
        self.reserve_count = 0

    def reserve_behavior(self, **kwargs):
        self.reserve_count += 1
        self.calls.append(("reserve", kwargs))
        if self.reserve_count == 1:
            return {
                "accepted": False,
                "activeBehaviorId": "behavior-already-playing",
            }
        return {"accepted": True, "behaviorId": kwargs["behavior_id"]}


class _OwnedTimer:
    instances = []

    def __init__(self, interval, callback, *args, **kwargs):
        self.interval = interval
        self.callback = callback
        self.daemon = False
        self.active = False
        self.__class__.instances.append(self)

    def start(self):
        self.active = True

    def cancel(self):
        self.active = False

    def is_alive(self):
        return self.active


def test_interactive_audio_uses_global_behavior_mutex():
    robot = _Robot()
    audio = _Audio()

    assert events._play_interactive_course_audio(
        "runtime-interactive",
        "pairing",
        "praise",
        robot_service=robot,
        audio_service=audio,
    )

    reserve = robot.calls[0][1]
    commit = next(call for call in robot.calls if call[0] == "commit")
    assert reserve["session_id"] == "runtime-interactive"
    assert audio.calls[0]["behavior_id"] == reserve["behavior_id"]
    assert audio.calls[0]["request_id"] == reserve["request_id"]
    assert commit[1] == reserve["behavior_id"]
    assert commit[2] == 1


def test_rule_aware_ordering_question_is_not_deferred():
    assert events._is_deferred_ordering_question({
        "courseType": "ordering",
        "aux": {"question": True},
    })
    assert not events._is_deferred_ordering_question({
        "courseType": "ordering",
        "category": "size",
        "rule": "bigger",
        "aux": {"question": True},
    })


def test_actual_ordering_question_commits_voice_and_visual_together():
    robot = _Robot()
    audio = _Audio()
    with events._deferred_question_lock:
        events._deferred_ordering_questions.clear()

    assert events._play_atomic_ordering_question(
        "runtime-ordering",
        "question_size_bigger",
        category="size",
        rule="bigger",
        text="选出更大的那张。",
        event_data={
            "courseId": 12,
            "studentId": 3,
            "questionId": "ordering-shell-q3",
        },
        robot_service=robot,
        audio_service=audio,
        runtime_session=SimpleNamespace(
            student_id=3,
            course_id=12,
            course_item_id=None,
            training_session_id="training-ordering",
        ),
    )

    reserve = next(call for call in robot.calls if call[0] == "reserve")[1]
    trigger = next(call for call in robot.calls if call[0] == "trigger")[1]
    commit = next(call for call in robot.calls if call[0] == "commit")
    assert trigger["behaviorId"] == reserve["behavior_id"]
    assert audio.calls[0]["behavior_id"] == reserve["behavior_id"]
    assert audio.calls[0]["request_id"] == reserve["request_id"]
    assert audio.calls[0]["question_id"] == "ordering-shell-q3"
    assert commit[1] == reserve["behavior_id"]
    assert commit[2] == 1


def test_manual_ordering_question_dispatches_rule_phrase(monkeypatch):
    from app.audio.service import AudioService
    import app.robot

    service = AudioService()
    dispatched = []
    monkeypatch.setattr(
        app.robot,
        "get_robot_service",
        lambda: SimpleNamespace(resolve_audio_offset_ms=lambda _data: 0),
    )
    monkeypatch.setattr(
        service,
        "play_interactive_course_audio",
        lambda **kwargs: dispatched.append(kwargs) or True,
    )

    details = service.process_play_resource(
        "runtime-manual-ordering",
        {
            "courseType": "ordering",
            "category": "count",
            "rule": "more",
            "aux": {"question": True},
        },
        behavior_id="behavior-manual-ordering",
        request_id="request-manual-ordering",
        return_details=True,
    )

    assert details["triggered"] is True
    assert details["deferred"] is False
    assert dispatched[0]["category"] == "count"
    assert dispatched[0]["rule"] == "more"
    assert dispatched[0]["behavior_id"] == "behavior-manual-ordering"
    assert dispatched[0]["request_id"] == "request-manual-ordering"


def test_item_question_busy_retry_has_one_session_owned_timer(monkeypatch):
    _OwnedTimer.instances.clear()
    monkeypatch.setattr(events.threading, "Timer", _OwnedTimer)
    robot = _BusyRobot()
    audio = _Audio()
    generation = events._remember_pending_item_question(
        "runtime-single-owner",
        kind="pairing",
        payload={},
    )
    question = {
        "questionId": "pairing-q1",
        "_askGeneration": generation,
    }
    with events._deferred_question_lock:
        pending = events._pending_interactive_questions["runtime-single-owner"]
        pending["payload"] = {
            "course_type": "pairing",
            "question_data": question,
        }

    assert not events._play_interactive_course_audio(
        "runtime-single-owner",
        "pairing",
        "question",
        question_data=question,
        robot_service=robot,
        audio_service=audio,
    )
    assert len(_OwnedTimer.instances) == 1
    assert events._flush_pending_item_question("runtime-single-owner")
    assert len(_OwnedTimer.instances) == 1

    events._clear_pending_item_question(
        "runtime-single-owner",
        generation=generation,
    )
    assert not _OwnedTimer.instances[0].is_alive()


def test_item_question_retry_reenters_the_captured_flask_context(monkeypatch):
    import app.audio
    import app.robot

    flask_app = Flask(__name__)
    robot = _BusyOnceRobot()
    audio = _Audio()
    monkeypatch.setattr(app.robot, "get_robot_service", lambda: robot)
    monkeypatch.setattr(app.audio, "get_audio_service", lambda: audio)
    with flask_app.app_context():
        generation = events._remember_pending_item_question(
            "runtime-context-retry",
            kind="pairing",
            payload={},
        )
        question = {
            "questionId": "pairing-q-context",
            "_askGeneration": generation,
        }
        with events._deferred_question_lock:
            pending = events._pending_interactive_questions["runtime-context-retry"]
            pending["payload"] = {
                "course_type": "pairing",
                "question_data": question,
            }
        assert not events._play_interactive_course_audio(
            "runtime-context-retry",
            "pairing",
            "question",
            question_data=question,
            robot_service=robot,
            audio_service=audio,
        )

    deadline = threading.Event()
    for _ in range(20):
        if audio.calls:
            break
        deadline.wait(0.025)
    assert len(audio.calls) == 1
    assert robot.reserve_count == 2
    assert events._pending_item_question_generation("runtime-context-retry") is None
