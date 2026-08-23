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
    assert "20260823-adaptive-vad-v2" in child_html
