from __future__ import annotations

from pathlib import Path

import numpy as np

from app.robot.mp4_validation import inspect_mp4
from app.robot.video_optimizer import optimize_mp4_upload, save_optimized_mp4


def _large_test_video(path: Path) -> bytes:
    import av

    container = av.open(str(path), mode="w", format="mp4")
    stream = container.add_stream("libx264", rate=24)
    stream.width = 1280
    stream.height = 720
    stream.pix_fmt = "yuv420p"
    stream.options = {"preset": "ultrafast", "crf": "12"}
    rng = np.random.default_rng(7)
    for _ in range(24):
        image = rng.integers(0, 256, (720, 1280, 3), dtype=np.uint8)
        frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()
    return path.read_bytes()


def test_emotion_upload_is_compressed_and_browser_compatible(tmp_path):
    source = _large_test_video(tmp_path / "source.mp4")

    result = optimize_mp4_upload(source, kind="emotion")
    metadata = inspect_mp4(result["data"])

    assert result["optimized"] is True
    assert result["sizeBytes"] < result["originalSizeBytes"]
    assert metadata["codec"] == "avc1"
    assert metadata["width"] <= 960
    assert metadata["height"] <= 720
    assert 900 <= metadata["durationMs"] <= 1100


def test_optimized_upload_is_published_atomically(tmp_path):
    source = _large_test_video(tmp_path / "source.mp4")
    library = tmp_path / "library"

    result = save_optimized_mp4(
        library,
        "praise.mp4",
        source,
        kind="animation",
    )

    assert result["name"] == "praise.mp4"
    assert (library / "praise.mp4").read_bytes()
    assert list(library.glob(".praise.mp4.*.tmp")) == []
