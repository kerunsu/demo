import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_engagement_feedback_returns_to_current_question_after_animation():
    from app.sockets.events import _apply_aux_overlay_policy

    payload = {"aux": {"reward": True}}
    policy = _apply_aux_overlay_policy(payload, "pairing")

    assert policy["isEngagementFeedback"] is True
    assert payload["returnToCurrentQuestion"] is True
    assert payload["holdLastFrame"] is False


def test_global_engagement_states_share_two_course_contract():
    from app.robot.behavior_events import is_aux_allowed

    for course_type in ("pairing", "ordering"):
        assert is_aux_allowed(course_type, "attention")
        assert is_aux_allowed(course_type, "reward")

    mapping = (ROOT / "doll" / "data" / "course_map.json").read_text(encoding="utf-8")
    assert '"attention"' in mapping
    assert '"reward"' in mapping


def test_demo_praise_uses_reviewed_random_animation_pool_and_fixed_reward():
    mapping = json.loads(
        (ROOT / "doll" / "data" / "course_map.json").read_text(encoding="utf-8")
    )
    praise = mapping["defaults"]["praise"]
    assert praise["animation"] == "__random_praise_animation__"
    assert len(praise["animations"]) >= 2
    assert mapping["defaults"]["reward"]["animation"] == "勾勾.mp4"
    for name in praise["animations"]:
        assert (ROOT / "static" / "resources" / "Animations" / name).is_file()


def test_teacher_and_server_expose_attention_reward_configuration():
    teacher = (ROOT / "teacher_frontend" / "components" / "ControlPage.tsx").read_text(encoding="utf-8")
    server = (ROOT / "templates" / "server" / "config.html").read_text(encoding="utf-8")
    phrases = (ROOT / "config" / "dialogue_phrases.yaml").read_text(encoding="utf-8")

    assert "全局注意力支持" in teacher
    assert "maimai.reward-animation.${selectedStudent}" in teacher
    assert "behaviorAnimationOverride" in teacher
    assert 'id="page-animations"' in server
    assert 'id="animation-grid"' in server
    assert 'id="slot-attention"' not in server
    assert 'id="slot-reward"' not in server
    assert "attention:" in phrases and "reward:" in phrases


def test_interactive_prompts_alternate_sides_and_respect_reduced_motion():
    shared = (ROOT / "static" / "js" / "interactive_question_state.js").read_text(encoding="utf-8")
    matching = (ROOT / "static" / "resources" / "interactive" / "matching.html").read_text(encoding="utf-8")
    ordering = (ROOT / "static" / "resources" / "interactive" / "sequencing.html").read_text(encoding="utf-8")

    assert "getBoundingClientRect" in shared
    assert 'index % 2 === 1 ? "left" : "right"' in shared
    assert 'direction === "left"' in shared
    assert "sideMargin + scaledHalfWidth" in shared
    assert "question-focus-entering" in shared
    assert "scale(1.58)" in matching
    assert "focusElement: '#targetFrame'" in matching
    assert "focusScale: 1.58" in matching
    assert "pairing-question-enter" in matching
    assert "presentationDirection: pageContext.presentationDirection" in matching
    assert "scale(1.52)" in ordering
    assert "focusElement: '.rule-text-wrapper'" in ordering
    assert "focusScale: 1.52" in ordering
    assert "ordering-question-enter" in ordering
    assert "presentationDirection: pageContext.presentationDirection" in ordering
    assert "prefers-reduced-motion: reduce" in matching
    assert "prefers-reduced-motion: reduce" in ordering


def test_automatic_interactive_praise_prepares_same_animation_barrier():
    events = (ROOT / "app" / "sockets" / "events.py").read_text(encoding="utf-8")
    helper = events[events.index("def _play_interactive_course_audio") : events.index("def _dispatch_v2_speech_commands")]
    assert "resolve_encouragement_animation" in helper
    assert "prepare_behavior_animation" in helper
    assert "set_behavior_animation_expected" in helper


def test_browser_only_speech_and_child_cache_version_are_deployed_together():
    dialogue = (ROOT / "static" / "js" / "child_dialogue.js").read_text(encoding="utf-8")
    child_html = (ROOT / "templates" / "child.html").read_text(encoding="utf-8")
    assert "startBrowserSpeechRecognition" in dialogue
    assert 'recognitionProvider ? { recognitionProvider }' in dialogue
    assert "child_dialogue_audio" not in dialogue
    assert 'child.css?v=20260826-child-surface-v2' in child_html
    assert 'child_dialogue.js?v=20260827-dialogue-runtime-v7' in child_html
    assert 'child.js?v=20260828-behavior-terminal-fix-v1' in child_html


def test_tts_defers_browser_transcript_until_reading_ends():
    dialogue = (ROOT / "static" / "js" / "child_dialogue.js").read_text(encoding="utf-8")
    pause = dialogue[dialogue.index("function pauseAsrForTts(") : dialogue.index("function maybeResumeListening()")]
    child = (ROOT / "static" / "js" / "child.js").read_text(encoding="utf-8")
    dialogue_sockets = (ROOT / "app" / "dialogue" / "sockets.py").read_text(encoding="utf-8")

    assert "pendingTtsTranscript" in dialogue
    assert "pendingTtsTranscriptReference" in dialogue
    assert "if (asrPausedForTts)" in dialogue
    assert "isLikelyTtsEcho" in pause
    assert "pauseAsrForTts?.(data.text)" in child
    assert "transcribe_audio_base64" not in dialogue_sockets
    assert '"browser_speech_required"' in dialogue_sockets
    assert "朗读中，仍在聆听" in dialogue


def test_matching_cards_keep_stable_size_and_scroll_horizontally():
    matching = (ROOT / "static" / "resources" / "interactive" / "matching.html").read_text(encoding="utf-8")

    assert '<p class="speech-bubble">' not in matching
    assert "选和上面一样的" not in matching
    assert "找出和这个一样的" in matching
    assert '--target-card-size: min(53.28vh, 439px)' in matching
    assert '--option-card-size: min(43.2vh, 367px)' in matching
    assert 'flex: 0 0 var(--option-card-size)' in matching
    assert "overflow-x: auto" in matching
    assert "contain: paint" in matching
    assert "cardElement.classList.add('correct-lvl3')" in matching
    assert "scrollIntoView({ behavior: 'smooth'" in matching
    assert '.options-grid[data-count="4"] .option-card' not in matching


def test_ordering_cards_keep_stable_size_and_use_warm_vertical_background():
    ordering = (ROOT / "static" / "resources" / "interactive" / "sequencing.html").read_text(encoding="utf-8")
    matching = (ROOT / "static" / "resources" / "interactive" / "matching.html").read_text(encoding="utf-8")

    assert "--ordering-card-size: min(52.8vh, 492px)" in ordering
    assert "flex: 0 0 var(--ordering-card-size)" in ordering
    assert "overflow-x: auto" in ordering
    assert "linear-gradient(180deg" in ordering
    assert "#ffe89a" in ordering
    assert "--bg-top: #ffe89a" in matching
    assert "--bg-bottom: #ffffff" in matching
    assert "--bg-gradient: linear-gradient(180deg, #ffe89a 0%, #fff4c8 42%, #ffffff 100%)" in matching
    assert "rgba(255, 232, 154, 0.97)" in matching
    assert "contain: paint" in ordering
    assert "card.classList.add('correct-lvl3')" in ordering


def test_engagement_actions_are_compact_sidebar_controls_with_modal_settings():
    teacher = (ROOT / "teacher_frontend" / "components" / "ControlPage.tsx").read_text(encoding="utf-8")

    quick_controls = teacher.index('aria-label="全局注意力支持"')
    dialogue_controls = teacher.index("儿童端智能体")
    assert quick_controls < dialogue_controls
    assert "setEngagementSettingsOpen(true)" in teacher
    assert 'aria-labelledby="engagement-settings-title"' in teacher
    assert "sticky top-0 z-20" not in teacher
