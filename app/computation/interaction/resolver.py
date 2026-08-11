"""InteractionProfileV2 双读解析器和 legacy 兼容适配器。"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from typing import Any, Mapping, Optional

from app.contracts.models import BehaviorPlan, InteractionContext, SpeechCommand
from app.contracts.ports import InteractionProfileStore

from .event_catalog import EventCatalog, infer_event_key
from .deployment import compare_plans


class LegacyInteractionAdapter:
    """把现有 MappingResolver 包进端口，不把旧实现带进 V2 配置层。"""

    def __init__(self, resolver: Any):
        self.resolver = resolver

    def normalize_event(self, context: InteractionContext, aux: Optional[dict] = None) -> Optional[str]:
        if context.event_key:
            return context.event_key
        return infer_event_key(context.course_type, aux)

    def resolve(self, context: InteractionContext, aux: Optional[dict] = None) -> dict[str, Any]:
        aux = aux or {}
        parse_aux = getattr(self.resolver, "parse_aux_type", None)
        aux_type = parse_aux(aux) if callable(parse_aux) else "silent"
        mapping = self.resolver.find_mapping(
            _as_int(context.student_id),
            _as_int(context.course_id),
            _as_int(context.item_id),
            aux_type,
        )
        mapping = copy.deepcopy(mapping if isinstance(mapping, dict) else {})
        return {
            "motions": list(mapping.get("motions") or []),
            "emotion": mapping.get("emotion"),
            "sequence": dict(mapping.get("sequence") or {}),
            "auxType": aux_type,
            "source": "legacy",
            "lineId": context.line_id or f"legacy.{aux_type}",
        }


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _as_commands(value: Any, *, key: str) -> tuple[dict[str, Any], ...]:
    if isinstance(value, str) and value.strip():
        value = [value]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return ()
    output = []
    for item in value:
        if isinstance(item, str) and item.strip():
            output.append({"assetId": item.strip(), "legacyName": item.strip()})
        elif isinstance(item, dict):
            command = copy.deepcopy(item)
            if command.get("assetId") or command.get("id") or command.get("name"):
                command.setdefault("assetId", command.get("id") or command.get("name"))
                output.append(command)
    return tuple(output)


class InteractionResolver:
    def __init__(
        self,
        *,
        store: InteractionProfileStore,
        legacy: LegacyInteractionAdapter,
        catalog: Optional[EventCatalog] = None,
    ) -> None:
        self.store = store
        self.legacy = legacy
        self.catalog = catalog or EventCatalog()

    @staticmethod
    def _canary_selected(profile: Mapping[str, Any], context: InteractionContext) -> bool:
        deployment = profile.get("deployment") if isinstance(profile.get("deployment"), Mapping) else {}
        stage = str(deployment.get("stage") or "published").lower()
        if stage == "published":
            return True
        if stage != "published_canary":
            return False
        try:
            percent = max(0.0, min(100.0, float(deployment.get("canaryPercent", 0))))
        except (TypeError, ValueError):
            percent = 0.0
        if percent <= 0:
            return False
        identity = (
            context.capabilities.get("sessionId")
            or context.capabilities.get("trainingSessionId")
            or context.course_id
            or "preview"
        )
        bucket = int(hashlib.sha256(str(identity).encode("utf-8")).hexdigest()[:8], 16) % 10000
        return bucket < int(percent * 100)

    @classmethod
    def _profile_allowed(cls, profile: Mapping[str, Any], context: InteractionContext) -> bool:
        statuses = {"published", "archived"} if context.profile_version else {"published"}
        if profile.get("status") not in statuses:
            return False
        # An explicit version is the server-frozen historical choice. It must
        # remain resolvable even after the profile is archived or its current
        # deployment stage changes.
        if context.profile_version:
            return True
        return cls._canary_selected(profile, context)

    def _profiles(self, context: InteractionContext) -> list[Mapping[str, Any]]:
        profiles = []
        all_profiles = list(self.store.list())
        if context.course_id:
            profile = self.store.get(str(context.course_id), context.profile_version)
            # A frozen session may continue using a previously published
            # version after it is archived by a later publication. Drafts are
            # never eligible for runtime resolution.
            if profile and self._profile_allowed(profile, context):
                profiles.append(profile)
        if context.profile_version:
            # A frozen version may belong to the course-type/global scope when
            # no course-specific profile existed at session start.
            all_profiles = [
                p for p in all_profiles
                if str(p.get("version")) == str(context.profile_version)
                and self._profile_allowed(p, context)
            ]
        if context.course_type:
            profiles.extend(
                p for p in all_profiles
                if self._profile_allowed(p, context)
                and str(p.get("courseType") or "").lower() == str(context.course_type).lower()
                and p not in profiles
            )
        profiles.extend(
            p for p in all_profiles
            if self._profile_allowed(p, context)
            and str(p.get("courseId")) in {"*", "global"}
            and p not in profiles
        )
        return profiles

    def active_profile_version(self, context: InteractionContext) -> Optional[str]:
        """Return the highest-precedence published profile to freeze at course start."""
        profiles = self._profiles(replace(context, profile_version=None))
        if not profiles:
            return None
        version = str(profiles[0].get("version") or "").strip()
        return version or None

    def resolve_shadow(self, context: InteractionContext, *, aux: Optional[dict] = None) -> BehaviorPlan:
        """Resolve a published candidate from a shadow stage without executing it."""
        class ShadowStore:
            def __init__(self, base):
                self.base = base

            @staticmethod
            def _shadow(profile):
                cloned = copy.deepcopy(dict(profile))
                deployment = dict(cloned.get("deployment") or {})
                deployment["stage"] = "published"
                cloned["deployment"] = deployment
                return cloned

            def list(self, course_id=None):
                values = self.base.list(course_id)
                return tuple(self._shadow(item) for item in values if item.get("status") in {"published", "archived"})

            def get(self, course_id, version=None):
                item = self.base.get(course_id, version)
                return self._shadow(item) if item and item.get("status") in {"published", "archived"} else None

        shadow_resolver = InteractionResolver(
            store=ShadowStore(self.store), legacy=self.legacy, catalog=self.catalog
        )
        return shadow_resolver.resolve(context, aux=aux)

    def resolve_with_shadow(self, context: InteractionContext, *, aux: Optional[dict] = None):
        active = self.resolve(context, aux=aux)
        shadow_profiles = []
        try:
            shadow_profiles = [
                p for p in self.store.list()
                if isinstance(p.get("deployment"), Mapping)
                and str(p["deployment"].get("stage") or "").lower() == "shadow"
                and p.get("status") == "published"
                and (
                    str(p.get("courseId")) in {str(context.course_id), "*", "global"}
                    or (
                        context.course_type
                        and str(p.get("courseType") or "").lower() == str(context.course_type).lower()
                    )
                )
            ]
        except Exception:
            shadow_profiles = []
        if not shadow_profiles:
            return active, None
        candidate = self.resolve_shadow(replace(context, profile_version=None), aux=aux)
        legacy_data = self.legacy.resolve(context, aux)
        legacy = self._plan(
            replace(context, event_key=candidate.context.event_key or active.context.event_key),
            legacy_data,
            source="legacy",
            trace=("shadow:legacy",),
        )
        return active, compare_plans(legacy, candidate)

    @staticmethod
    def _find_in_profile(profile: Mapping[str, Any], event: str, scene: Optional[str], line: Optional[str]) -> tuple[Optional[dict], str]:
        events = profile.get("events") if isinstance(profile.get("events"), dict) else {}
        event_data = events.get(event)
        if not isinstance(event_data, dict):
            return None, "event_missing"

        scenes = event_data.get("scenes") if isinstance(event_data.get("scenes"), dict) else {}
        if scene and isinstance(scenes.get(scene), dict):
            scene_data = scenes[scene]
            bindings = scene_data.get("lineBindings") if isinstance(scene_data.get("lineBindings"), dict) else {}
            if line and isinstance(bindings.get(line), dict):
                return copy.deepcopy(bindings[line]), f"event={event}/scene={scene}/line={line}"
            if isinstance(scene_data.get("binding"), dict):
                return copy.deepcopy(scene_data["binding"]), f"event={event}/scene={scene}"
        bindings = event_data.get("lineBindings") if isinstance(event_data.get("lineBindings"), dict) else {}
        if line and isinstance(bindings.get(line), dict):
            return copy.deepcopy(bindings[line]), f"event={event}/line={line}"
        if isinstance(event_data.get("binding"), dict):
            return copy.deepcopy(event_data["binding"]), f"event={event}"
        # A compact event entry with motions/emotion is accepted as event fallback.
        if any(key in event_data for key in ("motions", "motionAssets", "expressions", "emotion", "speech")):
            return copy.deepcopy(event_data), f"event={event}"
        return None, "binding_missing"

    @staticmethod
    def _merge_legacy(legacy: Mapping[str, Any], binding: Mapping[str, Any], mode: str) -> dict[str, Any]:
        if mode == "disabled":
            return copy.deepcopy(dict(legacy))
        if mode == "replace":
            result: dict[str, Any] = {}
        else:
            result = copy.deepcopy(dict(legacy))
        for key in (
            "motions", "motionAssets", "expressions", "expressionAssets", "emotion",
            "speech", "visual", "courseCommands", "sequence", "audioOffsetMs",
        ):
            if key in binding:
                result[key] = copy.deepcopy(binding[key])
        return result

    def resolve(self, context: InteractionContext, *, aux: Optional[dict] = None) -> BehaviorPlan:
        legacy = self.legacy.resolve(context, aux)
        event = self.legacy.normalize_event(context, aux)
        if not event or self.catalog.get(event) is None:
            return self._plan(context, legacy, source="legacy", trace=("legacy:event_unresolved",))
        effective_context = replace(context, event_key=event)
        trace: list[str] = []
        chosen = None
        chosen_profile = None
        for profile in self._profiles(effective_context):
            binding, path = self._find_in_profile(
                profile,
                event,
                effective_context.scene_key,
                effective_context.line_id,
            )
            trace.append(f"profile={profile.get('courseId')}:{profile.get('version')}:{path}")
            if binding is not None:
                chosen, chosen_profile = binding, profile
                break
        if chosen is None:
            return self._plan(effective_context, legacy, source="legacy", trace=tuple(trace + ["legacy:fallback"]))
        mode = str(chosen.get("mode") or "inherit").lower()
        if mode not in {"disabled", "inherit", "replace"}:
            return self._plan(effective_context, legacy, source="legacy", trace=tuple(trace + ["v2:invalid_mode", "legacy:fallback"]))
        merged = self._merge_legacy(legacy, chosen, mode)
        source = "legacy" if mode == "disabled" else f"v2.{mode}"
        return self._plan(
            replace(effective_context, profile_version=str(chosen_profile.get("version")) if chosen_profile else None),
            merged,
            source=source,
            trace=tuple(trace + [f"v2:{mode}"]),
        )

    def _plan(self, context: InteractionContext, data: Mapping[str, Any], *, source: str, trace: tuple[str, ...]) -> BehaviorPlan:
        behavior_id = context.behavior_id or f"behavior:{context.course_id or 'none'}:{context.event_key or 'none'}:{context.line_id or 'default'}"
        request_id = context.request_id
        sequence = data.get("sequence") if isinstance(data.get("sequence"), dict) else {}
        motion_offset = sequence.get("motionOffsetMs", 0)
        motions = list(_as_commands(data.get("motionAssets") or data.get("motions"), key="motion"))
        for command in motions:
            command.setdefault("offsetMs", motion_offset)
        expression_value = data.get("expressionAssets") or data.get("expressions")
        expressions = list(_as_commands(expression_value, key="expression"))
        if not expressions and data.get("emotion"):
            expressions = [{"assetId": data.get("emotion"), "legacyName": data.get("emotion")}]
        speech_values = data.get("speech")
        if isinstance(speech_values, dict):
            speech_values = [speech_values]
        speech = []
        for index, item in enumerate(speech_values or []):
            if isinstance(item, str):
                item = {"text": item}
            if not isinstance(item, dict):
                continue
            speech.append(SpeechCommand(
                command_id=f"{behavior_id}:speech:{index}",
                text=item.get("text"),
                line_id=item.get("lineId") or context.line_id,
                behavior_id=behavior_id,
                context=context,
                pause_asr=bool(item.get("pauseAsr", True)),
                metadata={
                    "source": source,
                    "delayMs": item.get("delayMs", 0),
                    "durationMs": item.get("durationMs"),
                    "intent": item.get("intent"),
                    "ttsMode": item.get("ttsMode"),
                    "audioAsset": item.get("audioAsset") or item.get("audio_asset"),
                },
            ))
        return BehaviorPlan(
            behavior_id=behavior_id,
            request_id=request_id,
            context=context,
            profile_version=context.profile_version,
            source=source,
            speech=tuple(speech),
            motions=tuple(motions),
            expressions=tuple(expressions),
            visual=tuple(_as_commands(data.get("visual"), key="visual")),
            course_commands=tuple(_as_commands(data.get("courseCommands"), key="course")),
            resolution_trace=trace,
            metadata={
                "sequence": copy.deepcopy(sequence),
                "auxType": data.get("auxType"),
                "mode": source,
                "speechConfigured": "speech" in data,
            },
        )


__all__ = ["InteractionResolver", "LegacyInteractionAdapter"]
