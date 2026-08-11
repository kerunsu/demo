from app.sockets import events


class _Manager:
    def __init__(self):
        self.rooms = {}

    def get_participants(self, namespace, room):
        return iter((sid, sid) for sid in self.rooms.get(room, set()))


class _Server:
    def __init__(self):
        self.manager = _Manager()

    def enter_room(self, sid, room, namespace=None):
        self.manager.rooms.setdefault(room, set()).add(sid)

    def leave_room(self, sid, room, namespace=None):
        self.manager.rooms.setdefault(room, set()).discard(sid)


class _Socket:
    def __init__(self):
        self.server = _Server()
        self.emitted = []

    def emit(self, event, payload, to=None, room=None, **kwargs):
        self.emitted.append({
            "event": event,
            "payload": payload,
            "to": to,
            "room": room,
        })


def _reset_child_state(*request_ids):
    with events._presence_lock:
        events._presence_state["child"].clear()
        events._child_sid_bindings.clear()
        events._child_sid_capabilities.clear()
        events._child_sync_attempted_sids.clear()
        events._child_session_owners.clear()
    with events._play_request_lock:
        for request_id in request_ids:
            events._play_request_cache.pop(request_id, None)


def _cache_content(request_id, *, session_id, student_id, training_id):
    assert events._claim_play_request(request_id) is None
    payload = {
        "action": "play",
        "requestId": request_id,
        "studentId": student_id,
        "trainingSessionId": training_id,
        "sessionId": session_id,
    }
    events._update_play_request(
        request_id,
        ack={"accepted": True, "requestId": request_id},
        content_forward_data=payload,
        child_room=f"session_{session_id}_child",
        is_aux=False,
    )
    return payload


def test_child_sync_announces_binding_before_direct_content_replay(monkeypatch):
    monkeypatch.setattr(events, "_is_active_runtime_session", lambda _sid: True)
    monkeypatch.setattr(
        events,
        "_runtime_child_identity",
        lambda requested: (dict(requested), None),
    )
    request_id = "child-sync-content-1"
    _reset_child_state(request_id)
    _cache_content(
        request_id,
        session_id="runtime-sync-1",
        student_id=11,
        training_id="training-sync-1",
    )
    events._touch_presence("child", "child-new-sid")
    socket = _Socket()

    response = events._sync_child_sid(
        socket,
        "child-new-sid",
        {
            "sessionId": "runtime-sync-1",
            "studentId": 11,
            "trainingSessionId": "training-sync-1",
            "capabilities": {"resourceReady": 1},
        },
        force=True,
    )

    assert response["success"] is True
    assert response["resourceReadySupported"] is True
    assert [item["event"] for item in socket.emitted] == [
        "child_session_sync",
        "play_resource",
    ]
    assert all(item["to"] == "child-new-sid" for item in socket.emitted)
    assert all(item["room"] is None for item in socket.emitted)
    assert (
        events._child_sid_bindings["child-new-sid"]["sessionId"]
        == "runtime-sync-1"
    )
    assert "child-new-sid" in socket.server.manager.rooms[
        "session_runtime-sync-1_child"
    ]
    _reset_child_state(request_id)


def test_unbound_child_is_not_guessed_when_cached_content_is_ambiguous(monkeypatch):
    monkeypatch.setattr(events, "_is_active_runtime_session", lambda _sid: True)
    request_ids = ("child-sync-ambiguous-1", "child-sync-ambiguous-2")
    _reset_child_state(*request_ids)
    _cache_content(
        request_ids[0],
        session_id="runtime-a",
        student_id=21,
        training_id="training-a",
    )
    _cache_content(
        request_ids[1],
        session_id="runtime-b",
        student_id=22,
        training_id="training-b",
    )
    events._touch_presence("child", "child-unbound")
    socket = _Socket()

    response = events._sync_child_sid(
        socket,
        "child-unbound",
        {"capabilities": {"resourceReady": 1}},
        force=True,
    )

    assert response["success"] is False
    assert response["reason"] == "ambiguous_content"
    assert [item["event"] for item in socket.emitted] == [
        "child_session_sync"
    ]
    assert "child-unbound" not in events._child_sid_bindings
    _reset_child_state(*request_ids)


def test_empty_target_room_bootstraps_only_unique_unbound_child():
    _reset_child_state()
    events._touch_presence("child", "only-child")
    events._remember_child_capability(
        "only-child",
        {"capabilities": {"resourceReady": True}},
    )
    socket = _Socket()
    content = {
        "action": "play",
        "requestId": "bootstrap-play-1",
        "studentId": 31,
        "trainingSessionId": "training-bootstrap",
        "sessionId": "runtime-bootstrap",
    }

    target = events._announce_content_to_unique_unbound_child(
        socket,
        child_room="session_runtime-bootstrap_child",
        content=content,
    )

    assert target == "only-child"
    assert [item["event"] for item in socket.emitted] == [
        "child_session_sync",
        "play_resource",
    ]
    assert all(item["to"] == "only-child" for item in socket.emitted)
    assert (
        events._resource_ready_support_for_identity(content)
        is True
    )
    _reset_child_state()


def test_explicit_old_child_capability_is_reported_as_unsupported():
    _reset_child_state()
    events._touch_presence("child", "old-child")
    events._remember_child_capability(
        "old-child",
        {"capabilities": {"resourceReady": 0}},
    )
    events._store_child_binding(
        "old-child",
        {
            "studentId": 41,
            "trainingSessionId": "training-old-child",
            "sessionId": "runtime-old-child",
        },
        source="test",
    )

    assert events._resource_ready_support_for_identity({
        "studentId": 41,
        "trainingSessionId": "training-old-child",
    }) is False
    _reset_child_state()


def test_disconnect_clears_child_binding_and_capability():
    _reset_child_state()
    events._touch_presence("child", "disconnect-child")
    events._remember_child_capability(
        "disconnect-child",
        {"capabilities": {"resourceReady": 1}},
    )
    events._store_child_binding(
        "disconnect-child",
        {
            "studentId": 51,
            "trainingSessionId": "training-disconnect",
            "sessionId": "runtime-disconnect",
        },
        source="test",
    )

    events._remove_sid_presence("disconnect-child")

    assert "disconnect-child" not in events._presence_state["child"]
    assert "disconnect-child" not in events._child_sid_bindings
    assert "disconnect-child" not in events._child_sid_capabilities


def test_online_child_without_ready_capability_is_unsupported():
    _reset_child_state()
    events._touch_presence("child", "legacy-child")
    events._remember_child_capability("legacy-child", {})
    events._store_child_binding(
        "legacy-child",
        {
            "studentId": 61,
            "trainingSessionId": "training-legacy",
            "sessionId": "runtime-legacy",
        },
        source="test",
    )

    assert events._resource_ready_support_for_identity({
        "studentId": 61,
        "trainingSessionId": "training-legacy",
    }) is False
    _reset_child_state()


def test_only_session_owner_can_ack_correlated_resource():
    request_id = "owner-ready-1"
    _reset_child_state(request_id)
    for sid in ("owner-child", "other-child"):
        events._touch_presence("child", sid)
        events._remember_child_capability(
            sid,
            {"capabilities": {"resourceReady": 1}},
        )
        events._store_child_binding(
            sid,
            {
                "studentId": 71 if sid == "owner-child" else 72,
                "trainingSessionId": "training-owner",
                "sessionId": "runtime-owner",
            },
            source="test",
        )
    assert events._claim_child_session_owner("runtime-owner", "owner-child")
    _cache_content(
        request_id,
        session_id="runtime-owner",
        student_id=71,
        training_id="training-owner",
    )
    ready = {
        "sessionId": "runtime-owner",
        "requestId": request_id,
    }

    assert events._is_authorized_child_sender(
        "owner-child", ready, require_cached_request=True
    )
    assert not events._is_authorized_child_sender(
        "other-child", ready, require_cached_request=True
    )
    _reset_child_state(request_id)


def test_inactive_cached_content_is_never_a_sync_candidate(monkeypatch):
    request_id = "inactive-content-1"
    _reset_child_state(request_id)
    _cache_content(
        request_id,
        session_id="runtime-ended",
        student_id=81,
        training_id="training-ended",
    )
    monkeypatch.setattr(events, "_is_active_runtime_session", lambda _sid: False)

    assert events._latest_cached_content_candidates({}) == []
    _reset_child_state(request_id)


def test_assignment_selects_matching_student_among_multiple_children():
    _reset_child_state()


def test_readiness_emit_binds_unique_late_child_before_direct_delivery():
    _reset_child_state()
    socket = _Socket()
    events._touch_presence("child", "late-child")
    events._remember_child_capability(
        "late-child",
        {"capabilities": {"resourceReady": 1}},
    )
    payload = {
        "studentId": 101,
        "trainingSessionId": "training-late",
        "sessionId": "runtime-late",
        "captureStart": True,
    }

    delivered, error = events._emit_readiness_to_child(
        socket,
        "readiness_complete",
        payload,
    )

    assert delivered is True
    assert error is None
    assert socket.emitted == [{
        "event": "readiness_complete",
        "payload": payload,
        "to": "late-child",
        "room": None,
    }]
    assert "late-child" in socket.server.manager.rooms[
        "session_runtime-late_child"
    ]
    assert events._child_session_owners["runtime-late"] == "late-child"
    _reset_child_state()
    socket = _Socket()
    for sid, student_id in (("child-a", 91), ("child-b", 92)):
        events._touch_presence("child", sid)
        events._remember_child_capability(
            sid,
            {"capabilities": {"resourceReady": 1}},
        )
        events._store_child_binding(
            sid,
            {
                "studentId": student_id,
                "trainingSessionId": None,
                "sessionId": None,
            },
            source="student_hint",
        )

    sid, error = events._assign_child_for_identity(
        socket,
        {
            "studentId": 92,
            "trainingSessionId": "training-92",
            "sessionId": "runtime-92",
        },
        source="test_prepare",
    )

    assert error is None
    assert sid == "child-b"
    assert events._child_session_owners["runtime-92"] == "child-b"
    assert "child-a" not in socket.server.manager.rooms.get(
        "session_runtime-92_child", set()
    )
    _reset_child_state()
