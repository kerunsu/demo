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
    assert "transition: opacity 160ms cubic-bezier(0.77, 0, 0.175, 1)" in css
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
    assert 'params.set("_transition", transitionId)' not in helper
    assert 'params.set("mode", mode)' in helper


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
    assert "event.source === interactiveEl.contentWindow" in child
    assert "stagingInteractiveEl.__pendingPageContext = data.pageContext" in child
    assert "stagingInteractiveEl.__pendingQuestionReady" in child
    assert "relayInteractiveQuestionReady(promoted, stagedQuestionReady)" in child


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


def test_ordering_teacher_config_is_applied_atomically_on_the_next_question():
    control = _read("teacher_frontend/components/ControlPage.tsx")
    ordering = _read("static/resources/interactive/sequencing.html")

    config_handler = control[
        control.index("const handleSequencingConfigChange") :
        control.index("// 排序游戏：发送提示")
    ]
    assert "sequencingConfigRef.current = nextConfig" in config_handler
    assert "socketRef.current.emit('sequencing_set_config'" in config_handler
    assert "...nextConfig" in config_handler

    set_config = ordering[
        ordering.index("setConfig(config)") :
        ordering.index("async startGame()")
    ]
    generate = ordering[
        ordering.index("async generateQuestion()") :
        ordering.index("getRandomRule()")
    ]
    assert "this.pendingConfig = {" in set_config
    assert "await this.applyPendingConfig();" in generate
    assert generate.index("await this.applyPendingConfig();") < generate.index(
        "if (this.autoMode)"
    )
    assert "await this.loadImages();" in set_config

    question_ready = control[
        control.index("socket.on('sequencing_question_ready'") :
        control.index("socket.on('sequencing_game_end'")
    ]
    assert "sequencingActiveQuestionRef.current =" in question_ready
    assert "setSequencingStatus" in question_ready

    play = control[
        control.index("const playCurrentItem = useCallback") :
        control.index("const retryFailedPlayback")
    ]
    assert "!isContent" in play
    assert "sequencingActiveQuestionRef.current" in play
    assert "category: orderingQuestionConfig.category" in play
    assert "rule: orderingQuestionConfig.rule" in play
    assert "下一题类别" in control
    assert "下一题规则" in control


def test_interactive_controls_use_authorized_parent_socket_bridge():
    child = _read("static/js/child.js")
    matching = _read("static/resources/interactive/matching.html")
    sequencing = _read("static/resources/interactive/sequencing.html")
    template = _read("templates/child.html")
    events = _read("app/sockets/events.py")

    for event_name in (
        "matching_set_difficulty",
        "matching_hint",
        "sequencing_set_config",
        "sequencing_hint",
    ):
        assert f'"{event_name}"' in child
    assert 'type: "interactive_control"' in child
    assert "relayInteractiveControl(eventName" in child
    assert 'frame.dataset.pageContextActive !== "true"' in child
    assert "}, window.location.origin);" in child
    assert 'child.js?v=20260823-resource-latency-v1' in template

    for page, prefix, apply_name in (
        (matching, "matching_", "applyMatchingControl"),
        (sequencing, "sequencing_", "applySequencingControl"),
    ):
        assert "const isEmbeddedInteractiveFrame" in page
        assert "message.type !== 'interactive_control'" in page
        assert "event.origin !== window.location.origin" in page
        assert f"eventName.startsWith('{prefix}')" in page
        assert apply_name in page
        assert "sessionId && !isEmbeddedInteractiveFrame" in page
        assert "pendingInteractiveControls" in page

    matching_start = matching[
        matching.index("function applyMatchingControl") :
        matching.index("window.addEventListener('message'")
    ]
    ordering_start = sequencing[
        sequencing.index("function applySequencingControl") :
        sequencing.index("window.addEventListener('message'")
    ]
    assert "flushQuestionReady()" in matching_start
    assert "emitQuestionReady()" not in matching_start
    assert "flushQuestionReady()" in ordering_start
    assert "emitQuestionReady()" not in ordering_start

    # The bridge must not weaken the one-owner child session rule.
    assert "_claim_child_session_owner" in events


def test_interactive_question_state_separates_mode_gate_and_teacher_next():
    control = _read("teacher_frontend/components/ControlPage.tsx")
    app = _read("teacher_frontend/App.tsx")
    child = _read("static/js/child.js")
    gate = _read("static/js/interactive_question_state.js")
    matching = _read("static/resources/interactive/matching.html")
    sequencing = _read("static/resources/interactive/sequencing.html")
    events = _read("app/sockets/events.py")

    assert "mode={assessmentMode ? 'assessment' : 'training'}" in app
    assert "mode," in control
    assert "handleInteractiveNextQuestion" in control
    assert "source: 'teacher_next_question'" in control
    assert "interactiveNextPending ? '切题中…' : '下一题'" in control
    assert "下一题正在准备，请不要连续点击" in control
    assert 'params.set("mode", mode)' in child
    assert "class QuestionInputGate" in gate
    assert 'data.intent || ""' in gate
    assert "question-input-locked" in matching
    assert "question-input-locked" in sequencing
    assert "this.questionGate.lock" in matching
    assert "this.questionGate.lock" in sequencing
    assert "type: 'interactive_question_ready'" in matching
    assert "type: 'interactive_question_ready'" in sequencing
    assert "!isEmbeddedInteractiveFrame && socket && socket.connected" in matching
    assert "!isEmbeddedInteractiveFrame && socket && socket.connected" in sequencing
    assert "MODE_ASSESSMENT" in matching
    assert "MODE_ASSESSMENT" in sequencing
    assert "this.currentOptions.reverse()" in matching
    assert "this.options = [this.options[1], this.options[0]]" in sequencing
    assert events.count("_interrupt_interactive_prompt(session_id, data)") >= 4


def test_matching_teacher_difficulty_overrides_simplified_mode_on_next_question():
    control = _read("teacher_frontend/components/ControlPage.tsx")
    matching = _read("static/resources/interactive/matching.html")

    difficulty_handler = control[
        control.index("const handleSetMatchingDifficulty") :
        control.index("// 配对游戏：启动游戏")
    ]
    assert "matchingDifficultyRef.current = level" in difficulty_handler
    assert "socketRef.current.emit('matching_set_difficulty'" in difficulty_handler

    apply_difficulty = matching[
        matching.index("applyTeacherDifficulty()") :
        matching.index("async startGame()")
    ]
    next_question = matching[
        matching.index("      nextQuestion() {") :
        matching.index("      generateQuestion() {")
    ]
    assert "this.autoDifficulty = this.teacherDifficulty" in apply_difficulty
    assert "this.isSimplifiedMode = false" in apply_difficulty
    assert "this.questionsInCurrentLevel = 0" in apply_difficulty
    assert "this.applyTeacherDifficulty();" in next_question
    assert next_question.index("this.applyTeacherDifficulty();") < next_question.index(
        "this.generateQuestion();"
    )


def test_teacher_rating_opens_within_one_second_without_interrupting_praise():
    control = _read("teacher_frontend/components/ControlPage.tsx")

    ack_handler = control[
        control.index("socket.on('play_resource_ack'") :
        control.index("socket.on('audio_status_update'")
    ]
    assert "requestedAtMs: Date.now()" in control
    assert "courseType !== 'pairing' && courseType !== 'ordering'" in ack_handler
    assert "Math.max(0, 800 - elapsedMs)" in ack_handler
    assert "handleNextRef.current('praise_end')" in ack_handler

    request_advance = control[
        control.index("const requestAdvance") :
        control.index("useEffect(() => {\n    handleNextRef.current = requestAdvance")
    ]
    assert "source !== 'praise_end'" in request_advance

    animation_start = control.index("socket.on('behavior_animation_ended'")
    animation_end = control[animation_start : control.index("return socket;", animation_start)]
    assert "handleNextRef.current('praise_end')" not in animation_end
    assert "pendingPraiseAdvanceRef.current = praiseContext" not in animation_end

    busy_content = control[
        control.index("if (\n      playbackPhaseRef.current !== 'idle'") :
        control.index("// 验证studentId是否存在")
    ]
    assert "play-content-deferred" in busy_content
    assert "deferredContentRetryRef.current" in busy_content
