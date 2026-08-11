from types import SimpleNamespace

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
        event_data={"courseId": 12, "studentId": 3},
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
