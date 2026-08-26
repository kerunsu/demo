from unittest.mock import patch

from app.dialogue.sockets import _handle_dialogue_utterance
from app.services import recording_timeline as timeline


def test_dialogue_timeline_is_saved_with_session_aligned_offsets(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    monkeypatch.setattr(timeline, "sessions_root", lambda: sessions)
    recording = timeline.begin_recording_session(
        media_session_id="media-dialogue-1",
        training_session_id="training-dialogue-1",
        student_id=7,
        human_dir_name="小雨-6-20260824-1",
        n=1,
    )
    offsets = iter((1.234, 2.5))
    monkeypatch.setattr(recording, "now_offset", lambda: next(offsets))

    try:
        first_path = timeline.append_dialogue_timeline_message(
            "media-dialogue-1",
            role="child",
            text="你好\n麦麦",
            request_id="dialogue-1",
        )
        second_path = timeline.append_dialogue_timeline_message(
            "media-dialogue-1",
            role="maimai",
            text="你好，我在这里 | 陪你聊天。",
            request_id="dialogue-1",
        )
    finally:
        timeline.unregister_recording_dir("media-dialogue-1")

    expected = sessions / "小雨-6-20260824-1" / "dialogue_timeline.txt"
    assert first_path == expected
    assert second_path == expected
    rows = [
        line
        for line in expected.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert len(rows) == 2
    assert rows[0].startswith(
        "000001 | "
    ) and " | T+00:00:01.234 | 儿童 | dialogue-1 | 你好\\n麦麦" in rows[0]
    assert rows[1].startswith(
        "000002 | "
    ) and " | T+00:00:02.500 | 麦麦 | dialogue-1 | " in rows[1]
    assert rows[1].endswith("你好，我在这里 \\| 陪你聊天。")
    assert not list(expected.parent.glob(".dialogue_timeline.txt.*.tmp"))
    assert not (sessions / "media-dialogue-1").exists()


def test_dialogue_handler_records_the_same_child_and_model_bubbles(monkeypatch):
    recorded = []

    class FakeDialogueService:
        def _sync_history_for_context(self, *_args, **_kwargs):
            return None

        def is_session_awake(self, *_args, **_kwargs):
            return True

        def generate_reply(self, text, **_kwargs):
            assert text == "今天玩什么？"
            return {
                "reply": "我们一起看图片吧。",
                "strategy": "llm",
                "provider": "test",
            }

    monkeypatch.setattr(
        "app.dialogue.sockets.get_dialogue_service", lambda: FakeDialogueService()
    )
    monkeypatch.setattr(
        "app.dialogue.sockets._try_keyword_auto_praise_from_dialogue",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(
        "app.dialogue.sockets._emit_speak", lambda **_kwargs: True
    )
    monkeypatch.setattr(
        "app.dialogue.sockets._record_visible_dialogue_message",
        lambda **kwargs: recorded.append(kwargs),
    )

    with patch("app.dialogue.sockets.emit") as emit:
        _handle_dialogue_utterance(
            session_id="media-dialogue-2",
            child_text="今天玩什么？",
            page_context={"courseType": "pairing"},
            room="session_media-dialogue-2_child",
            request_id="dialogue-2",
        )

    assert [(item["role"], item["text"]) for item in recorded] == [
        ("child", "今天玩什么？"),
        ("maimai", "我们一起看图片吧。"),
    ]
    result = [
        call.args[1]
        for call in emit.call_args_list
        if call.args and call.args[0] == "child_dialogue_result"
    ][-1]
    assert result["transcript"] == "今天玩什么？"
    assert result["reply"]["reply"] == "我们一起看图片吧。"
