"""presence / client_presence 回归。"""
import app.sockets.events as events_mod


def test_client_presence_marks_teacher_and_child_online(monkeypatch):
    events_mod._presence_state['teacher'].clear()
    events_mod._presence_state['child'].clear()

    events_mod._touch_presence('teacher', 'sid-teacher')
    events_mod._touch_presence('child', 'sid-child')

    snap = events_mod.get_online_presence_snapshot()
    assert snap['teacherOnline'] >= 1
    assert snap['childOnline'] >= 1


def test_stale_presence_not_counted(monkeypatch):
    events_mod._presence_state['teacher'].clear()
    events_mod._presence_state['child'].clear()

    # 模拟超过 30s 的陈旧时间戳
    events_mod._presence_state['teacher']['old'] = events_mod._now_ms() - 60_000
    events_mod._presence_state['child']['old'] = events_mod._now_ms() - 60_000

    snap = events_mod.get_online_presence_snapshot()
    assert snap['teacherOnline'] == 0
    assert snap['childOnline'] == 0


def test_agent_heartbeat_also_touches_child(monkeypatch):
    events_mod._presence_state['child'].clear()
    events_mod._presence_state['child_agent'].clear()

    events_mod._touch_presence('child', 'sid-c')
    events_mod._touch_presence('child_agent', 'sid-c', online=True)

    snap = events_mod.get_online_presence_snapshot()
    assert snap['childOnline'] >= 1
    assert snap['childAgentOnline'] >= 1


def test_robot_control_surfaces_have_distinct_presence():
    events_mod._presence_state['robot_display'].clear()
    events_mod._presence_state['robot_control'].clear()

    events_mod._touch_presence('robot_display', 'sid-display')
    events_mod._touch_presence('robot_control', 'sid-control')

    snap = events_mod.get_online_presence_snapshot()
    assert snap['robotDisplayOnline'] == 1
    assert snap['robotControlOnline'] == 1
