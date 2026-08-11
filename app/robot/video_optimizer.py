"""Upload-time MP4 optimization for latency-sensitive robot visuals."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict

from app.robot.mp4_validation import inspect_mp4


UPLOAD_MAX_BYTES = 100 * 1024 * 1024
OPTIMIZE_MIN_BYTES = 512 * 1024


@dataclass(frozen=True)
class VideoProfile:
    max_width: int
    max_height: int
    bitrate: int


PROFILES = {
    "emotion": VideoProfile(max_width=960, max_height=720, bitrate=550_000),
    "animation": VideoProfile(max_width=1280, max_height=720, bitrate=800_000),
}


def _target_dimensions(width: int, height: int, profile: VideoProfile) -> tuple[int, int]:
    scale = min(1.0, profile.max_width / width, profile.max_height / height)
    target_width = max(2, int(width * scale) // 2 * 2)
    target_height = max(2, int(height * scale) // 2 * 2)
    return target_width, target_height


def _needs_optimization(info: Dict[str, Any], profile: VideoProfile) -> bool:
    width = int(info.get("width") or 0)
    height = int(info.get("height") or 0)
    duration_ms = int(info.get("durationMs") or 0)
    average_bitrate = (
        int(info.get("sizeBytes") or 0) * 8_000 // duration_ms
        if duration_ms > 0
        else 0
    )
    return bool(
        int(info.get("sizeBytes") or 0) >= OPTIMIZE_MIN_BYTES
        or width > profile.max_width
        or height > profile.max_height
        or average_bitrate > profile.bitrate * 6 // 5
    )


def _transcode_h264(source: bytes, profile: VideoProfile) -> bytes:
    try:
        import av
    except ImportError as exc:
        raise RuntimeError("video_optimizer_unavailable: install PyAV") from exc

    with tempfile.TemporaryDirectory(prefix="eiart-video-") as temporary:
        input_path = Path(temporary) / "input.mp4"
        output_path = Path(temporary) / "output.mp4"
        input_path.write_bytes(source)

        input_container = av.open(str(input_path), mode="r")
        try:
            input_stream = next(iter(input_container.streams.video), None)
            if input_stream is None:
                raise ValueError("mp4_video_track_missing")
            width = int(input_stream.codec_context.width or 0)
            height = int(input_stream.codec_context.height or 0)
            if width <= 0 or height <= 0:
                raise ValueError("mp4_resolution_unknown")
            target_width, target_height = _target_dimensions(width, height, profile)
            source_rate = input_stream.average_rate or input_stream.base_rate or Fraction(24, 1)
            normalized_rate = min(30, max(12, int(round(float(source_rate or 24)))))
            rate = Fraction(normalized_rate, 1)

            output_container = av.open(
                str(output_path),
                mode="w",
                format="mp4",
                options={"movflags": "+faststart"},
            )
            try:
                output_stream = output_container.add_stream("libx264", rate=rate)
                output_stream.width = target_width
                output_stream.height = target_height
                output_stream.pix_fmt = "yuv420p"
                output_stream.bit_rate = profile.bitrate
                output_stream.options = {
                    "preset": "fast",
                    "profile": "main",
                    "maxrate": str(profile.bitrate),
                    "bufsize": str(profile.bitrate * 2),
                }
                for frame_index, frame in enumerate(input_container.decode(input_stream)):
                    converted = frame.reformat(
                        width=target_width,
                        height=target_height,
                        format="yuv420p",
                    )
                    # Uploaded clips commonly carry imprecise VFR time bases.
                    # Rebuild a stable CFR timeline instead of forwarding them.
                    converted.pts = frame_index
                    converted.time_base = Fraction(1, normalized_rate)
                    for packet in output_stream.encode(converted):
                        output_container.mux(packet)
                for packet in output_stream.encode():
                    output_container.mux(packet)
            finally:
                output_container.close()
        finally:
            input_container.close()

        return output_path.read_bytes()


def optimize_mp4_upload(file_bytes: bytes, *, kind: str) -> Dict[str, Any]:
    """Validate and, when useful, produce a smaller browser-safe MP4."""
    profile = PROFILES.get(kind)
    if profile is None:
        raise ValueError(f"video_profile_unknown: {kind}")
    source_info = inspect_mp4(file_bytes, max_bytes=UPLOAD_MAX_BYTES)
    optimized = False
    result = file_bytes
    if _needs_optimization(source_info, profile):
        candidate = _transcode_h264(file_bytes, profile)
        candidate_info = inspect_mp4(candidate, max_bytes=UPLOAD_MAX_BYTES)
        if len(candidate) < len(file_bytes):
            result = candidate
            optimized = True
            output_info = candidate_info
        else:
            output_info = source_info
    else:
        output_info = source_info
    return {
        "data": result,
        "optimized": optimized,
        "originalSizeBytes": len(file_bytes),
        "sizeBytes": len(result),
        "savedBytes": len(file_bytes) - len(result),
        "width": output_info.get("width"),
        "height": output_info.get("height"),
        "durationMs": output_info.get("durationMs"),
        "codec": output_info.get("codec"),
        "validationStatus": output_info.get("validationStatus"),
        "validationWarnings": output_info.get("validationWarnings") or [],
    }


def save_optimized_mp4(
    directory: Path | str,
    name: str,
    file_bytes: bytes,
    *,
    kind: str,
) -> Dict[str, Any]:
    """Optimize and atomically publish one new MP4 without partial files."""
    destination_dir = Path(directory)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / name
    if destination.exists():
        raise FileExistsError(f"Video already exists: {name}")
    result = optimize_mp4_upload(file_bytes, kind=kind)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{name}.", suffix=".tmp", dir=str(destination_dir)
    )
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(result["data"])
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    details = {key: value for key, value in result.items() if key != "data"}
    return {"name": name, **details}


def optimize_existing_mp4(path: Path | str, *, kind: str) -> Dict[str, Any]:
    """Optimize one existing MP4 and atomically replace it only when smaller."""
    source_path = Path(path)
    if not source_path.is_file() or source_path.suffix.lower() != ".mp4":
        raise FileNotFoundError(f"MP4 does not exist: {source_path}")
    result = optimize_mp4_upload(source_path.read_bytes(), kind=kind)
    if result["optimized"]:
        fd, temporary = tempfile.mkstemp(
            prefix=f".{source_path.name}.", suffix=".tmp", dir=str(source_path.parent)
        )
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(result["data"])
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, source_path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
    details = {key: value for key, value in result.items() if key != "data"}
    return {"name": source_path.name, "path": str(source_path), **details}
