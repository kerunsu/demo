"""行为必须原子互斥：busy 请求不能留下单独的语音副作用。"""
from app.sockets.events import (
    should_process_play_audio,
    should_reject_atomic_audio,
)


def test_busy_content_switch_skips_empty_audio():
    assert (
        should_process_play_audio(
            audio_pending=True,
            skip_robot_due_to_busy=True,
            wants_aux=False,
            is_aux_op=False,
        )
        is False
    )


def test_busy_aux_question_is_rejected_with_the_whole_behavior():
    """动作/表情忙碌时，aux 语音也必须一起拒绝。"""
    assert (
        should_process_play_audio(
            audio_pending=True,
            skip_robot_due_to_busy=True,
            wants_aux=True,
            is_aux_op=True,
        )
        is False
    )


def test_idle_always_processes_pending_audio():
    assert (
        should_process_play_audio(
            audio_pending=True,
            skip_robot_due_to_busy=False,
            wants_aux=False,
            is_aux_op=False,
        )
        is True
    )


def test_no_pending_audio_never_processes():
    assert (
        should_process_play_audio(
            audio_pending=False,
            skip_robot_due_to_busy=True,
            wants_aux=True,
            is_aux_op=True,
        )
        is False
    )


def test_required_aux_dispatch_failure_rejects_whole_behavior():
    assert should_reject_atomic_audio(
        wants_aux=True,
        audio_details={
            "triggered": False,
            "dispatchCount": 0,
            "deferred": False,
        },
    )


def test_explicit_interactive_deferred_audio_is_not_dispatch_failure():
    assert not should_reject_atomic_audio(
        wants_aux=True,
        audio_details={
            "triggered": False,
            "dispatchCount": 0,
            "deferred": True,
        },
    )
