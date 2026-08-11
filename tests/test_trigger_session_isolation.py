"""自动检测触发器必须按 runtime session 隔离。"""

from app.core.actions import (
    ActionDefinition,
    ActionResult,
    ActionTarget,
    ActionType,
)
from app.core.trigger import (
    TriggerCondition,
    TriggerDefinition,
    TriggerSystem,
    TriggerType,
    TriggerFactory,
)


class _UnusedExecutor:
    def execute(self, action, session_id):  # pragma: no cover - 本测试不执行动作
        raise AssertionError("unexpected action execution")


def test_same_named_triggers_do_not_share_cooldown_between_sessions():
    system = TriggerSystem(action_executor=_UnusedExecutor())
    first = TriggerFactory.speech_match_success(cooldown=60.0)
    second = TriggerFactory.speech_match_success(cooldown=60.0)

    system.register_trigger(first, "runtime-a")
    system.register_trigger(second, "runtime-b")

    first_for_session = system.get_triggers_for_session("runtime-a")
    second_for_session = system.get_triggers_for_session("runtime-b")

    assert first_for_session == [first]
    assert second_for_session == [second]
    assert first_for_session[0] is not second_for_session[0]

    first.mark_triggered()
    assert first.can_trigger() is False
    assert second.can_trigger() is True


def test_clearing_one_session_keeps_other_same_named_trigger():
    system = TriggerSystem(action_executor=_UnusedExecutor())
    first = TriggerFactory.pose_match_success()
    second = TriggerFactory.pose_match_success()
    system.register_trigger(first, "runtime-a")
    system.register_trigger(second, "runtime-b")

    system.clear_session_triggers("runtime-a")

    assert system.get_triggers_for_session("runtime-a") == []
    assert system.get_triggers_for_session("runtime-b") == [second]


def test_behavior_busy_does_not_consume_automatic_trigger_cooldown():
    class _BusyExecutor:
        def execute(self, action, session_id):
            return ActionResult(
                success=False,
                action_type=action.action_type.value,
                target=action.target.value,
                error="behavior_busy",
            )

    trigger = TriggerDefinition(
        name="retry-after-busy",
        condition=TriggerCondition(
            trigger_type=TriggerType.CUSTOM,
            custom_condition=lambda _data: True,
        ),
        action=ActionDefinition(
            action_type=ActionType.PLAY_AUDIO,
            target=ActionTarget.CHILD,
        ),
        cooldown=60.0,
    )
    system = TriggerSystem(action_executor=_BusyExecutor())
    system.register_trigger(trigger, "runtime-busy")

    result = system.check_and_execute(object(), "runtime-busy")

    assert result[0].error == "behavior_busy"
    assert trigger.can_trigger() is True
    assert trigger.trigger_count == 0
