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

    assert "新行为接管旧表情状态" in emotion
    assert "superseded_by_new_behavior" in emotion
    assert "emotion_busy" not in emotion
    assert "robot_emotion_ended" in emotion
    assert "pendingEmotions" not in emotion


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
