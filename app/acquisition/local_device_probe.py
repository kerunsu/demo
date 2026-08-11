"""Bounded first-sample probes for devices physically attached to Server."""

from __future__ import annotations

from typing import Any, Mapping


def probe_local_device(kind: str, selector: Mapping[str, Any]) -> dict[str, Any]:
    raw_index = selector.get("index", selector.get("deviceIndex"))
    try:
        index = int(raw_index) if raw_index is not None else None
    except (TypeError, ValueError):
        return {"connected": False, "error": "device_index_invalid"}
    if kind == "video":
        return _probe_video(0 if index is None else index)
    if kind == "audio":
        return _probe_audio(index)
    return {"connected": False, "error": "unsupported_device_kind"}


def _probe_video(index: int) -> dict[str, Any]:
    cap = None
    try:
        import cv2

        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not cap or not cap.isOpened():
            if cap:
                cap.release()
            cap = cv2.VideoCapture(index)
        if not cap or not cap.isOpened():
            return {"connected": False, "error": f"camera_open_failed:{index}", "index": index}
        ok, frame = cap.read()
        return {
            "connected": bool(ok and frame is not None),
            "sample": "first_frame" if ok and frame is not None else None,
            "error": None if ok and frame is not None else f"camera_first_frame_failed:{index}",
            "index": index,
        }
    except Exception as exc:
        return {"connected": False, "error": str(exc), "index": index}
    finally:
        if cap:
            cap.release()


def _probe_audio(index: int | None) -> dict[str, Any]:
    pa = None
    stream = None
    try:
        import pyaudio

        pa = pyaudio.PyAudio()
        kwargs = {
            "format": pyaudio.paInt16,
            "channels": 1,
            "rate": 16000,
            "input": True,
            "frames_per_buffer": 1024,
        }
        if index is not None:
            kwargs["input_device_index"] = index
        stream = pa.open(**kwargs)
        sample = stream.read(1024, exception_on_overflow=False)
        return {
            "connected": bool(sample),
            "sample": "first_audio_chunk" if sample else None,
            "error": None if sample else "microphone_first_chunk_empty",
            "index": index,
        }
    except Exception as exc:
        return {"connected": False, "error": str(exc), "index": index}
    finally:
        try:
            if stream:
                stream.stop_stream()
                stream.close()
        finally:
            if pa:
                pa.terminate()


__all__ = ["probe_local_device"]
