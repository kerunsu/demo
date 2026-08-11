"""Publish-time validation for InteractionProfileV2."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from .event_catalog import EventCatalog


_MODES = {"disabled", "inherit", "replace"}
_ASSET_FIELDS = ("motions", "motionAssets", "expressions", "expressionAssets")
_MAX_DECLARED_DURATION_MS = 120_000


def _iter_bindings_with_path(node: Any, path: str):
    if not isinstance(node, Mapping):
        return
    if any(key in node for key in ("mode", *_ASSET_FIELDS, "emotion", "speech", "sequence", "inherits")):
        yield path, node
    binding = node.get("binding")
    if isinstance(binding, Mapping):
        yield from _iter_bindings_with_path(binding, f"{path}/binding")
    for key in ("scenes", "lineBindings"):
        child = node.get(key)
        if isinstance(child, Mapping):
            for name, value in child.items():
                yield from _iter_bindings_with_path(value, f"{path}/{key}/{name}")


def _iter_bindings(node: Any):
    yield from (value for _, value in _iter_bindings_with_path(node, "event"))


def _asset_names(value: Any) -> list[tuple[str, bool]]:
    values = value if isinstance(value, list) else [value]
    result: list[tuple[str, bool]] = []
    for item in values:
        if isinstance(item, str) and item.strip():
            # Bare strings are the historical physical-name form and remain
            # compatible with the legacy library.
            result.append((item.strip(), False))
        elif isinstance(item, Mapping):
            name = item.get("assetId") or item.get("asset_id") or item.get("id") or item.get("name")
            if name:
                result.append((str(name).strip(), True))
    return result


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _duration_values(binding: Mapping[str, Any]) -> list[float]:
    values: list[float] = []
    for key in ("durationMs", "expressionDurationMs", "delayMs", "motionOffsetMs"):
        value = _number(binding.get(key))
        if value is not None:
            values.append(value)
    sequence = binding.get("sequence")
    if isinstance(sequence, Mapping):
        for key in ("durationMs", "expressionDurationMs", "delayMs", "motionOffsetMs"):
            value = _number(sequence.get(key))
            if value is not None:
                values.append(value)
    speech = binding.get("speech")
    if isinstance(speech, Mapping):
        speech = [speech]
    if isinstance(speech, list):
        for item in speech:
            if isinstance(item, Mapping):
                value = _number(item.get("durationMs"))
                if value is not None:
                    values.append(value)
    return values


def _check_reachability(profile: Mapping[str, Any], event_keys: set[str], errors: list[str], catalog: EventCatalog) -> None:
    transitions = profile.get("transitions") or profile.get("stateTransitions")
    if not isinstance(transitions, Mapping):
        return
    initial = str(profile.get("initialEvent") or profile.get("initialState") or "idle")
    edges: dict[str, set[str]] = {key: set() for key in event_keys}
    for current, previous in transitions.items():
        current = str(current)
        if current not in event_keys:
            errors.append(f"transition_event_not_declared:{current}")
            continue
        values = previous if isinstance(previous, list) else [previous]
        for item in values:
            source = str(item)
            if source not in event_keys and source != "*":
                errors.append(f"transition_source_not_declared:{source}")
            elif source != "*" and not catalog.validate_transition(source, current):
                errors.append(f"transition_not_allowed:{source}->{current}")
            if source != "*":
                edges.setdefault(source, set()).add(current)
    reachable = {initial, "*"}
    changed = True
    while changed:
        changed = False
        for source, destinations in edges.items():
            if source in reachable:
                before = len(reachable)
                reachable.update(destinations)
                changed = changed or len(reachable) != before
    for key in sorted(event_keys - {"idle"}):
        if key not in reachable:
            errors.append(f"event_unreachable:{key}")


def _check_inheritance(bindings: Mapping[str, Mapping[str, Any]], errors: list[str]) -> None:
    graph: dict[str, str] = {}
    for path, binding in bindings.items():
        target = binding.get("inherits")
        if target is None:
            continue
        raw = str(target).strip()
        candidates = [
            raw,
            raw.replace(".", "/"),
            f"{path.split('/')[0]}/{raw}",
        ]
        if raw == path.split('/')[0]:
            # Compact profiles commonly inherit their event's own fallback
            # binding by naming only the event key.
            candidates.append(path)
        resolved = next((item for item in candidates if item in bindings), None)
        if resolved is None:
            errors.append(f"binding_inheritance_target_missing:{path}:{raw}")
        else:
            graph[path] = resolved
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            errors.append(f"binding_inheritance_cycle:{node}")
            return
        if node in visited:
            return
        visiting.add(node)
        if node in graph:
            visit(graph[node])
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def validate_profile(
    profile: Mapping[str, Any],
    catalog: EventCatalog,
    *,
    asset_exists: Optional[Callable[[str, str], bool]] = None,
) -> tuple[str, ...]:
    """Return stable error codes; an empty tuple means publishable."""
    errors: list[str] = []
    course_id = str(profile.get("courseId") or profile.get("course_id") or "").strip()
    version = str(profile.get("version") or "").strip()
    events = profile.get("events")
    if not course_id:
        errors.append("profile_course_id_required")
    if not version:
        errors.append("profile_version_required")
    if not isinstance(events, Mapping):
        errors.append("profile_events_must_be_object")
        return tuple(errors)

    bindings: dict[str, Mapping[str, Any]] = {}
    line_ids: dict[str, str] = {}
    for event_key, event_data in events.items():
        event_key = str(event_key)
        if catalog.get(event_key) is None:
            errors.append(f"event_not_registered:{event_key}")
        if not isinstance(event_data, Mapping):
            errors.append(f"event_binding_must_be_object:{event_key}")
            continue
        event_bindings = list(_iter_bindings_with_path(event_data, event_key))
        for path, binding in event_bindings:
            bindings[path] = binding
            mode = str(binding.get("mode") or "inherit").lower()
            if mode not in _MODES:
                errors.append(f"binding_mode_invalid:{event_key}:{mode}")
            for field in _ASSET_FIELDS:
                for asset_id, logical in _asset_names(binding.get(field)):
                    if logical and asset_exists is not None and not asset_exists(field, asset_id):
                        errors.append(f"asset_not_found:{field}:{asset_id}")
            sequence = binding.get("sequence")
            if sequence is not None and not isinstance(sequence, Mapping):
                errors.append(f"sequence_must_be_object:{event_key}")
            speech = binding.get("speech")
            if isinstance(speech, Mapping):
                speech = [speech]
            if speech is not None and not isinstance(speech, list):
                errors.append(f"speech_must_be_array:{event_key}")
            for item in speech or []:
                if not isinstance(item, Mapping) or not str(item.get("text") or "").strip():
                    errors.append(f"speech_text_required:{path}")
                elif isinstance(item.get("audioAsset") or item.get("audio_asset"), Mapping):
                    audio = item.get("audioAsset") or item.get("audio_asset")
                    asset_id = audio.get("assetId") or audio.get("asset_id") or audio.get("id")
                    if asset_id and asset_exists is not None and not asset_exists("speech", str(asset_id)):
                        errors.append(f"asset_not_found:speech:{asset_id}")
            declared_durations = _duration_values(binding)
            for value in declared_durations:
                if value < 0:
                    errors.append(f"duration_negative:{path}")
                elif value > _MAX_DECLARED_DURATION_MS:
                    errors.append(f"duration_too_long:{path}")
            if sum(declared_durations) > _MAX_DECLARED_DURATION_MS:
                errors.append(f"duration_total_too_long:{path}")
            line_id = binding.get("lineId")
            if line_id:
                line_id = str(line_id)
                previous = line_ids.get(line_id)
                if previous and previous != path:
                    errors.append(f"line_id_duplicate:{line_id}")
                line_ids[line_id] = path
        line_bindings = event_data.get("lineBindings")
        if isinstance(line_bindings, Mapping):
            for line_id in line_bindings:
                line_id = str(line_id)
                previous = line_ids.get(line_id)
                if previous and not previous.startswith(event_key):
                    errors.append(f"line_id_duplicate:{line_id}")
                line_ids.setdefault(line_id, f"{event_key}/lineBindings/{line_id}")

    _check_inheritance(bindings, errors)
    _check_reachability(profile, set(str(key) for key in events), errors, catalog)

    required = profile.get("requiredEvents") or profile.get("required_events") or []
    fallbacks = profile.get("fallbacks") if isinstance(profile.get("fallbacks"), Mapping) else {}
    bound_event_keys = {path.split("/")[0] for path in bindings}
    for event_key in required if isinstance(required, list) else []:
        key = str(event_key)
        if key not in bound_event_keys and not fallbacks.get(key):
            errors.append(f"required_event_fallback_missing:{key}")
    return tuple(dict.fromkeys(errors))


__all__ = ["validate_profile"]
