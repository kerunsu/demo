from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_audio_prewarm_separates_pending_ready_and_has_timeout():
    source = (ROOT / "static/js/audio_player.js").read_text(encoding="utf-8")
    assert "this.pendingPreloads = new Map()" in source
    assert "preload_timeout:" in source
    assert "audio.onloadedmetadata = ready" in source
    assert "audio.oncanplay = ready" in source
    assert "oncanplaythrough" not in source
    assert "this.preloadedAudios.set(filePath, audio)" in source


def test_child_does_not_prewarm_audio_during_class_start():
    source = (ROOT / "static/js/child.js").read_text(encoding="utf-8")
    assert 'socket.on("readiness_prepare"' not in source
    assert "audioPlayer.preloadAudio(filePath)" not in source
    assert 'socket.on("readiness_complete"' in source
