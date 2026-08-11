"""Download the local FunASR model set into the project's runtime cache."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = REPO_ROOT / ".runtime" / "models" / "voice"
MANIFEST_PATH = RUNTIME_ROOT / "model_paths.json"
LOCK_PATH = RUNTIME_ROOT / ".download.lock"
MODEL_REPOSITORIES = {
    "VOICE_SERVICE_FUNASR_MODEL": "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "VOICE_SERVICE_FUNASR_VAD_MODEL": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "VOICE_SERVICE_FUNASR_PUNC_MODEL": "iic/punc_ct-transformer_cn-en-common-vocab471067-large",
}
MODEL_ALIASES = {
    "paraformer-zh": MODEL_REPOSITORIES["VOICE_SERVICE_FUNASR_MODEL"],
    "fsmn-vad": MODEL_REPOSITORIES["VOICE_SERVICE_FUNASR_VAD_MODEL"],
    "ct-punc": MODEL_REPOSITORIES["VOICE_SERVICE_FUNASR_PUNC_MODEL"],
}
REQUIRED_MODEL_KEYS = set(MODEL_REPOSITORIES)


def _model_references() -> dict[str, str]:
    references = {}
    for variable, repository in MODEL_REPOSITORIES.items():
        references[variable] = os.environ.get(variable, "").strip() or next(
            alias for alias, target in MODEL_ALIASES.items() if target == repository
        )
    return references


def _valid_manifest(expected_references: dict[str, str] | None = None) -> dict[str, str] | None:
    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        paths = payload.get("paths") if isinstance(payload, dict) else None
        references = payload.get("references") if isinstance(payload, dict) else None
        if (
            isinstance(paths, dict)
            and REQUIRED_MODEL_KEYS.issubset(paths)
            and all(Path(paths[key]).is_dir() for key in REQUIRED_MODEL_KEYS)
            and (expected_references is None or references == expected_references)
        ):
            return {str(key): str(value) for key, value in paths.items()}
    except (OSError, ValueError, TypeError):
        pass
    return None


def _acquire_lock(references: dict[str, str], timeout_s: int = 1800) -> int:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            return os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            manifest = _valid_manifest(references)
            if manifest:
                return -1
            try:
                if time.time() - LOCK_PATH.stat().st_mtime > timeout_s:
                    LOCK_PATH.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for model download lock: {LOCK_PATH}")
            time.sleep(1)


def _download_model(reference: str, default_repository: str, cache_dir: Path) -> str:
    candidate = Path(reference).expanduser()
    if candidate.is_dir():
        return str(candidate.resolve())
    repository = MODEL_ALIASES.get(reference, reference if "/" in reference else default_repository)
    from modelscope import snapshot_download
    path = Path(snapshot_download(repository, cache_dir=str(cache_dir))).resolve()
    if not path.is_dir():
        raise RuntimeError(f"Model download returned a missing directory: {path}")
    return str(path)


def prepare_models() -> dict[str, str]:
    references = _model_references()
    existing = _valid_manifest(references)
    if existing:
        return existing
    descriptor = _acquire_lock(
        references,
        int(os.environ.get("VOICE_SERVICE_MODEL_DOWNLOAD_TIMEOUT", "1800")),
    )
    if descriptor == -1:
        ready = _valid_manifest(references)
        if ready:
            return ready
        raise RuntimeError("Model download lock released without a valid manifest")
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        cache_dir = RUNTIME_ROOT / "modelscope"
        cache_dir.mkdir(parents=True, exist_ok=True)
        paths = {}
        for variable, repository in MODEL_REPOSITORIES.items():
            reference = references[variable]
            paths[variable] = _download_model(reference, repository, cache_dir)
        temp_path = MANIFEST_PATH.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(
                {"schemaVersion": 1, "references": references, "paths": paths},
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(temp_path, MANIFEST_PATH)
        return paths
    finally:
        os.close(descriptor)
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    try:
        paths = prepare_models()
        print(json.dumps({"success": True, "paths": paths}, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
