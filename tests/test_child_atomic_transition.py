from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_child_resource_transition_is_staged_and_acknowledged():
    child = _read("static/js/child.js")
    html = _read("templates/child.html")
    css = _read("static/css/child.css")

    assert 'id="image-staging"' in html
    assert 'id="video-staging"' in html
    assert 'id="interactive-staging"' in html
    assert 'socket.emit("resource_ready", terminal)' in child
    assert 'socket.emit("resource_transition_failed", terminal)' in child
    assert "await preloadStagingResource(spec, pair.staging, token)" in child
    assert "await delayMs(RESOURCE_CROSSFADE_MS)" in child
    assert "transition: opacity 320ms ease-in-out" in css
    assert "imageEl.onclick" not in child


def test_old_course_and_standby_survive_until_commit():
    child = _read("static/js/child.js")
    animation = child[child.index("function playBehaviorAnimation") :]

    assert 'hideStandbyImage();' in child
    assert child.count("hideStandbyImage();") == 1
    assert 'imageEl.style.display = "none"' not in animation
    assert 'interactiveEl.style.display = "none"' not in animation
    assert "showTransitionCover()" not in animation
    assert 'behaviorAnimationEl.style.opacity = "1"' in animation
    assert "freezeCommittedCourseFrame();" in animation
    assert 'socket.on("freeze_course_frame"' in child


def test_prepare_behavior_animation_does_not_start_playback():
    """prepare must decode only; early play races play_resource and skips 画面."""
    child = _read("static/js/child.js")
    prepare_handler = child[
        child.index('socket.on("prepare_behavior_animation"') :
        child.index('socket.on("joined_session"')
    ]
    assert "prepareBehaviorAnimation(" in prepare_handler
    assert "playBehaviorAnimation(" not in prepare_handler
    assert "function prepareBehaviorAnimation(" in child
    hold = child[
        child.index("function finishBehaviorAnimationPlayback") :
        child.index("function prepareBehaviorAnimation")
    ]
    assert 'status === "ended"' in hold
    assert "heldPraiseOverlay" in hold
    assert "holding frame" in hold
    assert "shouldHoldPraiseOverlay(" in hold
    assert "interactiveAutoPraise" in child
    assert "clearHeldPraiseOverlay(" in child
    assert 'clearHeldPraiseOverlay("content_committed")' in child
    transition = child[
        child.index("async function transitionCourseResource") :
        child.index("// 统一处理：播放资源")
    ]
    assert transition.index("currentVisibleCourseMedia =") < transition.index(
        'clearHeldPraiseOverlay("content_committed")'
    )
    template = _read("templates/child.html")
    assert 'child.js?v=20260820-interactive-praise-v3' in template
    handle_play = child[
        child.index("function handlePlayResource") :
        child.index('socket.on("play_resource"')
    ]
    praise_gate = handle_play[
        handle_play.index("const isInteractiveAutoPraise") :
        handle_play.index("const course = findCourseById")
    ]
    assert "playBehaviorAnimation(" in praise_gate
    assert "isAuxOperation || isInteractiveAutoPraise" in praise_gate


def test_interactive_questions_are_idempotent_and_answers_do_not_cut_speech():
    matching = _read("static/resources/interactive/matching.html")
    sequencing = _read("static/resources/interactive/sequencing.html")
    events = _read("app/sockets/events.py")

    matching_start = matching[
        matching.index("socket.on('matching_start'") :
        matching.index("socket.on('matching_set_difficulty'")
    ]
    ordering_start = sequencing[
        sequencing.index("socket.on('sequencing_start'") :
        sequencing.index("socket.on('sequencing_set_config'")
    ]
    assert "flushQuestionReady()" in matching_start
    assert "emitQuestionReady()" not in matching_start
    assert "flushQuestionReady()" in ordering_start
    assert "emitQuestionReady()" not in ordering_start
    assert "this._lastQuestionReadyKey === questionReadyKey" in matching
    assert "this._lastQuestionReadyKey === questionReadyKey" in sequencing

    matching_status = events[
        events.index("def handle_matching_status_update") :
        events.index("@socketio.on('matching_hint')")
    ]
    ordering_status = events[
        events.index("def handle_sequencing_status_update") :
        events.index("@socketio.on('sequencing_game_end')")
    ]
    assert "_interrupt_interactive_prompt" not in matching_status
    assert "_interrupt_interactive_prompt" not in ordering_status
    assert "_remember_pending_interactive_feedback" in events
    assert "_flush_pending_interactive_work" in events
    assert "maxMs = 20000" in matching
    assert "maxMs = 20000" in sequencing
    assert "maxMs: 2800" not in matching
    assert "maxMs: 2800" not in sequencing
    terminal_guard = "(data.status || data.terminalStatus || 'ended') !== 'ended'"
    assert terminal_guard in matching
    assert terminal_guard in sequencing
    assert "_preempt_busy_behavior_for_item_question" not in events
    assert "_pending_interactive_question_timers" in events
    assert "dimAllOptionCards()" in matching
    assert "waitForBehaviorAnimation" in matching
    assert "waitForBehaviorAnimation" in sequencing
    assert "waitAnimation: true" in matching
    assert "waitAnimation: !!isCorrect" in sequencing
    matching_select = matching[
        matching.index("selectOption(selectedOption") :
        matching.index("finishGame()")
    ]
    assert "correct-lvl3" not in matching_select
    assert "createExplosion" not in matching_select
    sequencing_feedback = sequencing[
        sequencing.index("showFeedback(selectedOption") :
        sequencing.index("showHint()")
    ]
    assert "correct-lvl3" not in sequencing_feedback
    assert "createExplosion" not in sequencing_feedback


def test_teacher_keyword_auto_praise_always_arms_scoring_fallback():
    control = _read("teacher_frontend/components/ControlPage.tsx")
    block = control[
        control.index("socket.on('keyword_auto_praise'") :
        control.index("socket.on('behavior_animation_ended'")
    ]
    assert "serverPlayed" in block
    assert "armPraiseRatingFallback(praiseContext" in block
    assert "data.hasAnimation ? 12000 : 3200" in block
    assert "if (!data.hasAnimation)" not in block


def test_teacher_praise_scoring_is_armed_before_emit_and_survives_degradation():
    control = _read("teacher_frontend/components/ControlPage.tsx")
    play = control[
        control.index("const playCurrentItem = useCallback") :
        control.index("const retryFailedPlayback")
    ]
    prearm = play.index("praiseRequestContextRef.current = praiseContext")
    emit = play.index('socketRef.current.emit("play_resource", playData)')
    assert prearm < emit
    assert "armPraiseRatingFallback(praiseContext, 15000)" in play

    completed = control[
        control.index("socket.on('behavior_completed'") :
        control.index("socket.on('analysis_result'")
    ]
    assert "matchesPraise" in completed
    assert "queuePraiseRating(" in completed

    animation = control[
        control.index("socket.on('behavior_animation_ended'") :
        control.index("return socket;")
    ]
    failed_branch = animation[
        animation.index("if (animationStatus !== 'ended')") :
        animation.index("const selected =")
    ]
    assert "queuePraiseRating(" in failed_branch

    ack = control[
        control.index("socket.on('play_resource_ack'") :
        control.index("socket.on('resource_ready'")
    ]
    assert "data?.animationExpected === true" in ack
    assert "armPraiseRatingFallback(" in ack


def test_behavior_media_are_correlated_and_expression_self_heals():
    browser_tts = _read("static/js/browser_tts.js")
    audio_player = _read("static/js/audio_player.js")
    emotion = _read("static/robot/js/emotion_display.js")

    assert "if (activeSpeech)" in browser_tts
    assert 'reason = sameSpeech(activeSpeech.identity, identity) ? "duplicate" : "busy"' in browser_tts
    assert "behaviorId: identity && (identity.behaviorId || identity.sequenceId)" in browser_tts

    assert "当前行为语音未结束，丢弃新语音" in audio_player
    assert "this.blockedPlayback = {" not in audio_player
    assert "this._rememberPlayback(blockedIdentity)" in audio_player
    assert "behaviorId: identity && (identity.behaviorId || identity.sequenceId)" in audio_player

    assert "正式表情播放中，新事件进入队列" in emotion
    assert "pendingEmotionEvents.push(eventData)" in emotion
    assert "superseded_by_dialogue_reply" in emotion
    assert "dialogueReply" in emotion
    assert "stopIdlePlayback();" in emotion
    assert "emotion_busy" not in emotion
    assert "robot_emotion_ended" in emotion


def test_browser_tts_delay_does_not_start_watchdog_before_speak():
    browser_tts = _read("static/js/browser_tts.js")
    attempt = browser_tts[
        browser_tts.index("const attemptSpeak = (attempt) =>") :
        browser_tts.index("attemptSpeak(0);")
    ]

    assert "attemptToken: 0" in browser_tts
    assert "const attemptToken = ++operation.attemptToken" in attempt
    assert "operation.attemptToken !== scheduledToken" in attempt
    assert "const isCurrentAttempt = () =>" in attempt

    speak_call = attempt.index("synth.speak(utterance);")
    watchdog_arm = attempt.index("startWatchdog = setTimeout", speak_call)
    assert speak_call < watchdog_arm
    assert "kickTimer = window.setTimeout" in attempt
    assert "clearKickTimer();" in attempt


def test_class_start_has_no_resource_prewarm_and_behavior_uses_shared_start():
    child = _read("static/js/child.js")
    animation = child[child.index("function playBehaviorAnimation") :]
    emotion = _read("static/robot/js/emotion_display.js")

    assert 'socket.on("readiness_prepare"' not in child
    assert "handleReadinessPrepare" not in child
    assert "preloadAssetUrl" not in child
    assert 'socket.on("readiness_complete"' in child
    assert "behaviorStartDelayMs" in animation
    assert "startScheduled" in animation
    assert "startDelayMs" in emotion
    assert "restartRequested" in emotion


def test_interactive_shell_prefers_course_entry_file():
    child = _read("static/js/child.js")
    helper = child[
        child.index("function interactiveResourceUrl") :
        child.index("function buildResourceSpec")
    ]
    assert helper.index("course && course.file") < helper.index("item && item.file")
    assert 'params.set("_transition", transitionId)' in helper


def test_logical_context_and_video_start_commit_with_the_staged_frame():
    child = _read("static/js/child.js")
    transition = child[
        child.index("async function transitionCourseResource") :
        child.index("// 统一处理：播放资源")
    ]
    preload = child[
        child.index("async function preloadStagingResource") :
        child.index("function promoteStagingResource")
    ]

    assert transition.index("promoteStagingResource") < transition.index(
        "commitCourseLogicalContext"
    )
    assert transition.index("commitCourseLogicalContext") < transition.index(
        "emitResourceReady"
    )
    assert "await staging.play()" not in preload
    assert "try { staging.pause(); }" in preload
    assert "await pair.staging.play()" in transition
    assert "event.source !== interactiveEl.contentWindow" in child
    assert "stagingInteractiveEl.__pendingPageContext = data.pageContext" in child


def test_child_rejects_old_session_media_and_praise_is_request_correlated():
    child = _read("static/js/child.js")
    audio_player = _read("static/js/audio_player.js")

    assert 'socket.emit("leave_session", {' in child
    assert "if (!isEventForActiveChildSession(payload))" in child
    assert "if (!isEventForActiveChildSession(data))" in child
    assert "if (!this._isCurrentSessionEvent(data)) return;" in audio_player
    assert "CHILD_SESSION_BINDING_KEY" in child
    assert 'socket.emit("child_sync_request"' in child
    assert 'socket.on("child_session_sync"' in child
    assert "resourceReady: 1" in child
    assert "recordingStartPromise" in child
    sync_block = child[
        child.index("function emitChildPresenceAndSync") :
        child.index("// 页面加载时拉取运行时配置")
    ]
    assert sync_block.index('socket.emit("child_sync_request"') < sync_block.index(
        '} else {'
    ) < sync_block.index('socket.emit("client_presence", binding);')
    assert "clearChildSessionBinding();" in child

    animation_payload = child[
        child.index("function behaviorAnimationTerminalPayload") :
        child.index("function pruneCompletedBehaviorAnimationPlaybacks")
    ]
    assert "payload && payload.requestId" in animation_payload
    assert "requestId:" in animation_payload


def test_teacher_waits_for_correlated_resource_ready_and_replays_after_reconnect():
    control = _read("teacher_frontend/components/ControlPage.tsx")

    assert "armContentResourceWait(" in control
    assert "clearContentResourceWait(requestId);" in control
    assert "retryControlsLocked || hasFailedPlayback" in control
    assert "pendingGame.fallbackTimerId = scheduleTimeout" not in control
    assert "socket.emit('play_resource', pending.payload)" in control
    assert "socket.emit('play_resource', known.payload)" in control
    assert "!eventRequestId ||" in control
    assert "socketRef.current.emit('freeze_course_frame'" in control
    assert "!socketRef.current?.connected ||" in control
    assert "scheduleTimeout(flushDeferredAutoQuestion, 0);" in control
