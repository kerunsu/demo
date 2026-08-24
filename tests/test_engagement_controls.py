from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_global_engagement_states_share_three_level_contract():
    from app.robot.behavior_events import is_aux_allowed

    for course_type in ("naming", "pairing", "ordering", "social"):
        assert is_aux_allowed(course_type, "attention")
        assert is_aux_allowed(course_type, "reward")

    mapping = (ROOT / "doll" / "data" / "course_map.json").read_text(encoding="utf-8")
    assert '"attention"' in mapping
    assert '"reward"' in mapping


def test_teacher_and_server_expose_attention_reward_configuration():
    teacher = (ROOT / "teacher_frontend" / "components" / "ControlPage.tsx").read_text(encoding="utf-8")
    server = (ROOT / "templates" / "server" / "config.html").read_text(encoding="utf-8")
    phrases = (ROOT / "config" / "dialogue_phrases.yaml").read_text(encoding="utf-8")

    assert "全局注意力支持" in teacher
    assert "maimai.reward-animation.${selectedStudent}" in teacher
    assert "behaviorAnimationOverride" in teacher
    assert 'id="slot-attention"' in server
    assert 'id="slot-reward"' in server
    assert 'id="animation-reward"' in server
    assert "attention:" in phrases and "reward:" in phrases


def test_interactive_prompts_focus_in_viewport_and_respect_reduced_motion():
    shared = (ROOT / "static" / "js" / "interactive_question_state.js").read_text(encoding="utf-8")
    matching = (ROOT / "static" / "resources" / "interactive" / "matching.html").read_text(encoding="utf-8")
    ordering = (ROOT / "static" / "resources" / "interactive" / "sequencing.html").read_text(encoding="utf-8")

    assert "getBoundingClientRect" in shared
    assert "global.innerWidth / 2" in shared
    assert "scale(1.58)" in matching
    assert "focusElement: '#targetFrame'" in matching
    assert "scale(1.52)" in ordering
    assert "focusElement: '.rule-text-wrapper'" in ordering
    assert "prefers-reduced-motion: reduce" in matching
    assert "prefers-reduced-motion: reduce" in ordering


def test_automatic_interactive_praise_prepares_same_animation_barrier():
    events = (ROOT / "app" / "sockets" / "events.py").read_text(encoding="utf-8")
    helper = events[events.index("def _play_interactive_course_audio") : events.index("def _dispatch_v2_speech_commands")]
    assert "resolve_encouragement_animation" in helper
    assert "prepare_behavior_animation" in helper
    assert "set_behavior_animation_expected" in helper


def test_adaptive_vad_and_child_cache_version_are_deployed_together():
    dialogue = (ROOT / "static" / "js" / "child_dialogue.js").read_text(encoding="utf-8")
    child_html = (ROOT / "templates" / "child.html").read_text(encoding="utf-8")
    assert "recentNoiseLevels" in dialogue
    assert "currentVadLevels" in dialogue
    assert "now - voiceStartedAt >= MIN_VOICE_MS" in dialogue
    assert "20260824-live-listen-v1" in child_html


def test_tts_keeps_capture_open_and_defers_the_answer_until_reading_ends():
    dialogue = (ROOT / "static" / "js" / "child_dialogue.js").read_text(encoding="utf-8")
    can_capture = dialogue[dialogue.index("function canCapture()") : dialogue.index("function clearPreroll()")]
    pause = dialogue[dialogue.index("function pauseAsrForTts()") : dialogue.index("function maybeResumeListening()")]

    assert "!asrPausedForTts" not in can_capture
    assert "pendingTtsTurn" in dialogue
    assert "capturedDuringTts" in dialogue
    assert "clearPreroll();" not in pause
    assert "朗读中，仍在聆听" in dialogue


def test_matching_cards_keep_stable_size_and_scroll_horizontally():
    matching = (ROOT / "static" / "resources" / "interactive" / "matching.html").read_text(encoding="utf-8")

    assert '<p class="speech-bubble">' not in matching
    assert 'width: min(44.4vh, 366px)' in matching
    assert 'flex: 0 0 min(36vh, 306px)' in matching
    assert "overflow-x: auto" in matching
    assert '.options-grid[data-count="4"] .option-card' not in matching


def test_engagement_actions_are_compact_sidebar_controls_with_modal_settings():
    teacher = (ROOT / "teacher_frontend" / "components" / "ControlPage.tsx").read_text(encoding="utf-8")

    quick_controls = teacher.index('aria-label="全局注意力支持"')
    dialogue_controls = teacher.index("儿童端智能体")
    assert quick_controls < dialogue_controls
    assert "setEngagementSettingsOpen(true)" in teacher
    assert 'aria-labelledby="engagement-settings-title"' in teacher
    assert "sticky top-0 z-20" not in teacher
