"""Bounded ISO-BMFF metadata inspection for uploaded robot video assets."""
from __future__ import annotations

from typing import Any, Dict, Iterator, Optional, Tuple


CONTAINER_BOXES = {b"moov", b"trak", b"mdia", b"minf", b"stbl"}
BROWSER_CODECS = {"avc1", "avc3", "hvc1", "hev1", "mp4v"}


def _boxes(
    data: bytes, start: int = 0, end: Optional[int] = None
) -> Iterator[Tuple[bytes, int, int, int]]:
    cursor = start
    limit = len(data) if end is None else min(end, len(data))
    while cursor + 8 <= limit:
        box_start = cursor
        size = int.from_bytes(data[cursor:cursor + 4], "big")
        kind = data[cursor + 4:cursor + 8]
        header = 8
        if size == 1:
            if cursor + 16 > limit:
                raise ValueError("mp4_truncated_extended_box")
            size = int.from_bytes(data[cursor + 8:cursor + 16], "big")
            header = 16
        elif size == 0:
            size = limit - cursor
        if size < header or cursor + size > limit:
            raise ValueError("mp4_invalid_box_size")
        yield kind, cursor + header, cursor + size, box_start
        cursor += size
    if cursor != limit:
        raise ValueError("mp4_trailing_partial_box")


def _walk(data: bytes, start: int, end: int):
    for item in _boxes(data, start, end):
        yield item
        kind, payload, box_end, _ = item
        if kind in CONTAINER_BOXES:
            yield from _walk(data, payload, box_end)


def inspect_mp4(
    data: bytes,
    *,
    max_bytes: int = 50 * 1024 * 1024,
    max_duration_ms: int = 5 * 60 * 1000,
) -> Dict[str, Any]:
    if not data:
        raise ValueError("mp4_empty")
    if len(data) > max_bytes:
        raise ValueError("mp4_too_large")
    top = list(_boxes(data))
    if not top or top[0][0] != b"ftyp":
        raise ValueError("mp4_ftyp_missing")

    duration_ms = 0
    codec = None
    width = None
    height = None
    has_moov = any(kind == b"moov" for kind, *_ in top)
    for kind, payload, box_end, _box_start in _walk(data, 0, len(data)):
        if kind == b"mvhd" and payload + 20 <= box_end:
            version = data[payload]
            if version == 0:
                timescale_pos, duration_pos, duration_size = payload + 12, payload + 16, 4
            elif version == 1 and payload + 32 <= box_end:
                timescale_pos, duration_pos, duration_size = payload + 20, payload + 24, 8
            else:
                continue
            timescale = int.from_bytes(data[timescale_pos:timescale_pos + 4], "big")
            duration = int.from_bytes(data[duration_pos:duration_pos + duration_size], "big")
            if timescale > 0:
                duration_ms = int(round(duration * 1000 / timescale))
        elif kind == b"stsd" and payload + 16 <= box_end:
            entry_count = int.from_bytes(data[payload + 4:payload + 8], "big")
            if entry_count:
                entry_start = payload + 8
                entry_size = int.from_bytes(data[entry_start:entry_start + 4], "big")
                if entry_size >= 36 and entry_start + entry_size <= box_end:
                    candidate_codec = data[entry_start + 4:entry_start + 8].decode("ascii", "replace")
                    candidate_width = int.from_bytes(data[entry_start + 32:entry_start + 34], "big")
                    candidate_height = int.from_bytes(data[entry_start + 34:entry_start + 36], "big")
                    # Audio sample entries (for example mp4a) also live in
                    # stsd, but do not have visual dimensions. Never let an
                    # audio codec overwrite the video codec used for browser
                    # playback validation.
                    if candidate_width > 0 and candidate_height > 0:
                        codec = candidate_codec
                        width = candidate_width
                        height = candidate_height

    warnings = []
    if not has_moov:
        warnings.append("mp4_moov_missing")
    if duration_ms <= 0:
        warnings.append("mp4_duration_unknown")
    elif duration_ms > max_duration_ms:
        raise ValueError("mp4_duration_too_long")
    if not width or not height:
        warnings.append("mp4_resolution_unknown")
    elif width > 3840 or height > 2160 or width < 16 or height < 16:
        raise ValueError("mp4_resolution_unsupported")
    if not codec:
        warnings.append("mp4_codec_unknown")
    elif codec.lower() not in BROWSER_CODECS:
        raise ValueError("mp4_codec_unsupported")

    return {
        "container": "mp4",
        "sizeBytes": len(data),
        "durationMs": duration_ms or None,
        "width": width,
        "height": height,
        "codec": codec,
        "validationStatus": "compatible" if not warnings else "degraded",
        "validationWarnings": warnings,
    }
