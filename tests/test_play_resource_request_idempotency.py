from app.sockets import events


def test_completed_play_request_ack_is_replayed_from_ttl_cache():
    request_id = "request-idempotency-test"
    with events._play_request_lock:
        events._play_request_cache.pop(request_id, None)

    assert events._claim_play_request(
        request_id,
        requester_sid="teacher-sid",
    ) is None
    events._update_play_request(
        request_id,
        behavior_id="behavior-idempotency-test",
        ack={
            "accepted": True,
            "requestId": request_id,
            "behaviorId": "behavior-idempotency-test",
        },
    )

    duplicate = events._claim_play_request(request_id)
    assert duplicate["status"] == "completed"
    assert duplicate["requesterSid"] == "teacher-sid"
    assert duplicate["ack"]["accepted"] is True
    assert duplicate["ack"]["behaviorId"] == "behavior-idempotency-test"

    with events._play_request_lock:
        events._play_request_cache.pop(request_id, None)


def test_reconnect_retry_retargets_cached_content_but_never_aux():
    request_id = "request-reconnect-content"
    aux_request_id = "request-reconnect-aux"
    for key in (request_id, aux_request_id):
        with events._play_request_lock:
            events._play_request_cache.pop(key, None)
    with events._presence_lock:
        events._presence_state["child"].clear()
        events._child_sid_bindings.clear()
        events._child_session_owners.clear()
    events._touch_presence("child", "child-owner")
    events._store_child_binding(
        "child-owner",
        {
            "studentId": 1,
            "trainingSessionId": "training-content",
            "sessionId": "runtime-content",
        },
        source="test",
    )
    assert events._claim_child_session_owner("runtime-content", "child-owner")

    assert events._claim_play_request(
        request_id,
        requester_sid="teacher-old",
    ) is None
    events._update_play_request(
        request_id,
        behavior_id="behavior-content",
        ack={
            "accepted": True,
            "requestId": request_id,
            "behaviorId": "behavior-content",
            "isAux": False,
        },
        content_forward_data={
            "action": "play",
            "requestId": request_id,
            "sessionId": "runtime-content",
        },
        child_room="session_runtime-content_child",
        is_aux=False,
    )
    duplicate = events._claim_play_request(
        request_id,
        requester_sid="teacher-new",
    )

    class _Socket:
        def __init__(self):
            self.emitted = []

        def emit(self, event, payload, room=None, to=None):
            self.emitted.append((event, payload, room, to))

    socket = _Socket()
    assert events._replay_cached_content(socket, duplicate)
    assert socket.emitted == [(
        "play_resource",
        {
            "action": "play",
            "requestId": request_id,
            "sessionId": "runtime-content",
        },
        None,
        "child-owner",
    )]
    assert duplicate["requesterSid"] == "teacher-new"

    assert events._claim_play_request(
        aux_request_id,
        requester_sid="teacher-old",
    ) is None
    events._update_play_request(
        aux_request_id,
        behavior_id="behavior-aux",
        ack={
            "accepted": True,
            "requestId": aux_request_id,
            "behaviorId": "behavior-aux",
            "isAux": True,
        },
        content_forward_data={
            "action": "play",
            "requestId": aux_request_id,
            "aux": {"praise": True},
        },
        child_room="session_runtime-content_child",
        is_aux=True,
    )
    aux_duplicate = events._claim_play_request(
        aux_request_id,
        requester_sid="teacher-new",
    )
    assert not events._replay_cached_content(socket, aux_duplicate)
    assert len(socket.emitted) == 1

    for key in (request_id, aux_request_id):
        with events._play_request_lock:
            events._play_request_cache.pop(key, None)
    with events._presence_lock:
        events._presence_state["child"].clear()
        events._child_sid_bindings.clear()
        events._child_session_owners.clear()
