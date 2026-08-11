import pytest

from app.robot.mp4_validation import inspect_mp4


def _box(kind: bytes, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def _video_mp4(*, duration_ms=2500, width=1280, height=720, codec=b"avc1"):
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isommp41")
    mvhd = _box(
        b"mvhd",
        b"\x00\x00\x00\x00"
        + (0).to_bytes(4, "big") * 2
        + (1000).to_bytes(4, "big")
        + int(duration_ms).to_bytes(4, "big"),
    )
    visual_entry = (
        (36).to_bytes(4, "big") + codec
        + b"\x00" * 24
        + int(width).to_bytes(2, "big")
        + int(height).to_bytes(2, "big")
    )
    stsd = _box(
        b"stsd", b"\x00\x00\x00\x00" + (1).to_bytes(4, "big") + visual_entry
    )
    hierarchy = _box(b"trak", _box(b"mdia", _box(b"minf", _box(b"stbl", stsd))))
    return ftyp + _box(b"moov", mvhd + hierarchy)


def test_mp4_validation_extracts_playback_metadata():
    result = inspect_mp4(_video_mp4())
    assert result == {
        "container": "mp4",
        "sizeBytes": len(_video_mp4()),
        "durationMs": 2500,
        "width": 1280,
        "height": 720,
        "codec": "avc1",
        "validationStatus": "compatible",
        "validationWarnings": [],
    }


def test_mp4_validation_ignores_audio_sample_entry_codec():
    video = _video_mp4()
    ftyp_size = int.from_bytes(video[:4], "big")
    ftyp, moov = video[:ftyp_size], video[ftyp_size:]
    audio_entry = (36).to_bytes(4, "big") + b"mp4a" + b"\x00" * 28
    audio_stsd = _box(
        b"stsd", b"\x00\x00\x00\x00" + (1).to_bytes(4, "big") + audio_entry
    )
    audio_track = _box(b"trak", _box(b"mdia", _box(b"minf", _box(b"stbl", audio_stsd))))
    payload = moov[8:] + audio_track
    result = inspect_mp4(ftyp + _box(b"moov", payload))
    assert result["codec"] == "avc1"
    assert result["validationStatus"] == "compatible"


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"duration_ms": 600_000}, "mp4_duration_too_long"),
        ({"width": 7680}, "mp4_resolution_unsupported"),
        ({"codec": b"zzzz"}, "mp4_codec_unsupported"),
    ],
)
def test_mp4_validation_rejects_unsafe_playback_properties(kwargs, error):
    with pytest.raises(ValueError, match=error):
        inspect_mp4(_video_mp4(**kwargs))
