"""报告评分 v2：逐课点教师评分 + 客观任务指标。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple
import yaml

from app.course_scope import enabled_course_dimensions, enabled_course_types


DEFAULT_WEIGHTS = {
    "attention": 34,
    "matching": 33,
    "ordering": 33,
}
DEFAULT_COURSE_WEIGHTS = {
    "pairing": 1,
    "ordering": 1,
}
DEFAULT_MIN_EFFECTIVE_SAMPLES = {
    "pairing": 5,
    "ordering": 5,
}
COURSE_SAMPLE_UNITS = {
    "pairing": "answered_question",
    "ordering": "answered_question",
}
COURSE_LABELS = {
    "pairing": "配对",
    "ordering": "排序",
}

COURSE_ALIASES = {
    "matching": "pairing",
    "sequencing": "ordering",
    "speech": "naming",
    "imitation": "mimic",
    "pose": "mimic",
}
COURSE_TYPE_EXPECTATIONS = {
    "pairing": ["matching"],
    "ordering": ["ordering"],
    "mimic": ["attention"],
}
SCORING_FINGERPRINT_KEYS = (
    "schema_version",
    "weights",
    "teacher_rating",
    "interactive_course",
    "dimension_weights",
    "course_weights",
    "sample_sufficiency",
)


def load_scoring_config() -> Dict[str, Any]:
    from app.config import BASE_DIR
    path = BASE_DIR / "config" / "report_scoring.yaml"
    if not path.exists():
        cfg = {
            "schema_version": "education-training-index-v3-sample-sufficiency-demo",
            "score_boundary": "education_training_reference_only",
            "course_goal_score": 70,
            "weights": DEFAULT_WEIGHTS,
            "course_weights": DEFAULT_COURSE_WEIGHTS,
            "sample_sufficiency": {
                "minimum_effective_samples": DEFAULT_MIN_EFFECTIVE_SAMPLES,
            },
            "teacher_rating": {"min": 1, "max": 5, "scale": 20},
            "interactive_course": {
                "accuracy_weight": 0.75,
                "response_weight": 0.25,
                "objective_weight": 0.70,
                "teacher_weight": 0.30,
                "ideal_response_sec": 3.0,
                "slow_response_sec": 12.0,
            },
            "grade_thresholds": {
                "excellent": 85,
                "good": 70,
                "fair": 55,
                "needs_support": 0,
            },
            "narrative_provider": "rule",
        }
    else:
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    # The deployable curriculum scope is a separate reviewed fact source.  It
    # narrows report output without duplicating course lists in scoring YAML.
    cfg["enabled_course_types"] = list(enabled_course_types())
    cfg["enabled_dimension_keys"] = list(enabled_course_dimensions())
    return cfg


def validate_scoring_config(cfg: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    weights = cfg.get("weights") or {}
    if not isinstance(weights, dict):
        errors.append("weights 必须为对象")
        return errors
    keys = tuple(enabled_course_dimensions())
    total = 0.0
    for k in keys:
        if k not in weights:
            errors.append(f"缺少权重 {k}")
            continue
        try:
            total += float(weights[k])
        except (TypeError, ValueError):
            errors.append(f"权重 {k} 必须为数字")
    if abs(total - 100.0) > 0.01:
        errors.append(f"Demo 三维 weights 之和必须为 100（当前 {total:.2f}）")
    np_ = cfg.get("narrative_provider")
    if np_ is not None and np_ not in ("rule", "mock"):
        errors.append("narrative_provider 仅为 rule|mock")
    ic = cfg.get("interactive_course")
    if ic is not None and not isinstance(ic, dict):
        errors.append("interactive_course 必须为对象")
    try:
        reference = float(cfg.get("course_goal_score", 70))
        if not 0 <= reference <= 100:
            errors.append("course_goal_score 必须在 0 到 100 之间")
    except (TypeError, ValueError):
        errors.append("course_goal_score 必须为数字")
    sufficiency = cfg.get("sample_sufficiency")
    if sufficiency is not None and not isinstance(sufficiency, dict):
        errors.append("sample_sufficiency 必须为对象")
    elif isinstance(sufficiency, dict):
        minimums = sufficiency.get("minimum_effective_samples")
        if minimums is not None and not isinstance(minimums, dict):
            errors.append("sample_sufficiency.minimum_effective_samples 必须为对象")
        elif isinstance(minimums, dict):
            for course_type in DEFAULT_MIN_EFFECTIVE_SAMPLES:
                if course_type not in minimums:
                    continue
                value = minimums.get(course_type)
                try:
                    parsed = int(value)
                    if isinstance(value, bool) or float(value) != parsed or not 1 <= parsed <= 100:
                        raise ValueError
                except (TypeError, ValueError):
                    errors.append(
                        f"minimum_effective_samples.{course_type} 必须为 1 到 100 的整数"
                    )
    return errors


def scoring_config_fingerprint(cfg: Dict[str, Any]) -> str:
    """Return a stable fingerprint of the effective scoring configuration."""
    effective = {key: cfg.get(key) for key in SCORING_FINGERPRINT_KEYS}
    effective["sample_sufficiency"] = {
        "minimum_effective_samples": _minimum_effective_samples(cfg),
    }
    payload = json.dumps(
        effective,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def save_scoring_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """校验后写盘；先备份 .bak。"""
    import shutil
    from app.config import BASE_DIR

    errors = validate_scoring_config(cfg)
    if errors:
        raise ValueError("；".join(errors))

    path = BASE_DIR / "config" / "report_scoring.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return cfg


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v)))


def _mean(values: Iterable[float]) -> Optional[float]:
    items = [float(v) for v in values]
    return sum(items) / len(items) if items else None


def _weighted_mean(values: Dict[str, Optional[float]], weights: Dict[str, Any]) -> Optional[float]:
    total = 0.0
    weight_total = 0.0
    for key, value in values.items():
        if value is None:
            continue
        weight = float(weights.get(key, 1))
        if weight <= 0:
            continue
        total += float(value) * weight
        weight_total += weight
    return total / weight_total if weight_total else None


def _metric_section(metrics: Dict[str, Any], key: str) -> Dict[str, Any]:
    section = metrics.get(key)
    if isinstance(section, dict):
        return section
    if metrics.get("type") == key:
        return metrics
    return {}


def _canonical_course_type(value: Any) -> str:
    course_type = str(value or "").lower()
    return COURSE_ALIASES.get(course_type, course_type)


def _normalize_rate(value: Any) -> Optional[float]:
    if value is None:
        return None
    rate = float(value)
    if 0 <= rate <= 1:
        rate *= 100
    return _clamp(rate)


def _response_score(response_ms: Optional[float], cfg: Dict[str, Any]) -> Optional[float]:
    if response_ms is None:
        return None
    interactive = cfg.get("interactive_course") or {}
    ideal = float(interactive.get("ideal_response_sec", 3.0))
    slow = float(interactive.get("slow_response_sec", 12.0))
    if slow <= ideal:
        return 50.0
    response_sec = float(response_ms) / 1000.0
    return _clamp(100.0 * (slow - response_sec) / (slow - ideal))


def _minimum_effective_samples(cfg: Dict[str, Any]) -> Dict[str, int]:
    configured = (
        (cfg.get("sample_sufficiency") or {}).get("minimum_effective_samples")
        if isinstance(cfg.get("sample_sufficiency"), dict)
        else {}
    )
    configured = configured if isinstance(configured, dict) else {}
    return {
        course_type: int(configured.get(course_type, default))
        for course_type, default in DEFAULT_MIN_EFFECTIVE_SAMPLES.items()
    }


def _positive_int(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _interactive_evidence_count(metrics: Dict[str, Any], objective: Dict[str, Any]) -> int:
    """Count answered questions represented by one pairing/ordering window."""
    for source in (objective, metrics):
        for key in ("answered", "total", "total_questions", "totalQuestions"):
            count = _positive_int(source.get(key))
            if count is not None:
                return count
    for source in (objective, metrics):
        times = source.get("response_times_ms")
        if times is None:
            times = source.get("responseTimesMs")
        if isinstance(times, list) and times:
            return len(times)
    return 1


def build_course_metrics(summary: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """从题目窗口构建类型平衡的课程分、表现率和响应时长。"""
    configured_types = cfg.get("enabled_course_types")
    reviewed_types = set(enabled_course_types())
    active_course_types = [
        _canonical_course_type(value)
        for value in configured_types
        if _canonical_course_type(value) in reviewed_types
    ] if isinstance(configured_types, list) else list(enabled_course_types())
    active_course_types = list(dict.fromkeys(active_course_types))
    if not active_course_types and not isinstance(configured_types, list):
        active_course_types = list(enabled_course_types())
    course_points: Dict[str, List[float]] = {key: [] for key in active_course_types}
    performance_points: Dict[str, List[float]] = {key: [] for key in active_course_types}
    response_points: Dict[str, List[float]] = {key: [] for key in active_course_types}
    rating_counts: Dict[str, int] = {key: 0 for key in active_course_types}
    observed_counts: Dict[str, int] = {key: 0 for key in active_course_types}
    evidence_counts: Dict[str, int] = {key: 0 for key in active_course_types}
    response_sample_counts: Dict[str, int] = {key: 0 for key in active_course_types}
    missing_rating_types = set()
    interactive_cfg = cfg.get("interactive_course") or {}
    accuracy_weight = float(interactive_cfg.get("accuracy_weight", 0.75))
    response_weight = float(interactive_cfg.get("response_weight", 0.25))
    objective_weight = float(interactive_cfg.get("objective_weight", 0.70))
    teacher_weight = float(interactive_cfg.get("teacher_weight", 0.30))

    for window in summary.get("windows") or []:
        course_type = _canonical_course_type(window.get("course_type"))
        if course_type not in course_points:
            continue
        observed_counts[course_type] += 1
        metrics = window.get("task_metrics") or {}
        teacher = metrics.get("teacher_rating") if isinstance(metrics.get("teacher_rating"), dict) else {}
        teacher_score = teacher.get("normalized_score")
        if teacher_score is None and teacher.get("rating") is not None:
            teacher_score = float(teacher["rating"]) * float((cfg.get("teacher_rating") or {}).get("scale", 20))
        teacher_score = _clamp(teacher_score) if teacher_score is not None else None
        if teacher_score is not None:
            rating_counts[course_type] += 1
        else:
            missing_rating_types.add(course_type)

        response_ms = teacher.get("response_ms")
        accuracy = None
        if course_type == "pairing":
            objective = _metric_section(metrics, "matching")
            accuracy = _normalize_rate(objective.get("accuracy", metrics.get("accuracy")))
        elif course_type == "ordering":
            objective = _metric_section(metrics, "sequencing")
            accuracy = _normalize_rate(objective.get("accuracy", metrics.get("accuracy")))
        else:
            objective = {}

        if course_type in ("pairing", "ordering"):
            objective_response = objective.get("avg_response_ms")
            if objective_response is None:
                objective_response = metrics.get("avg_response_ms")
            if objective_response is not None:
                response_ms = objective_response
            if accuracy is not None:
                evidence_count = _interactive_evidence_count(metrics, objective)
                speed_score = _response_score(float(response_ms), cfg) if response_ms is not None else None
                if speed_score is None:
                    objective_score = accuracy
                else:
                    denom = accuracy_weight + response_weight
                    objective_score = (
                        accuracy * accuracy_weight + speed_score * response_weight
                    ) / denom if denom > 0 else accuracy
                if teacher_score is None:
                    point_score = objective_score
                else:
                    denom = objective_weight + teacher_weight
                    point_score = (
                        objective_score * objective_weight + teacher_score * teacher_weight
                    ) / denom if denom > 0 else objective_score
                course_points[course_type].append(_clamp(point_score))
                performance_points[course_type].append(accuracy)
                evidence_counts[course_type] += evidence_count
        elif teacher_score is not None:
            course_points[course_type].append(teacher_score)
            performance_points[course_type].append(teacher_score)

        # 历史命名训练可用旧 receptive 指标兜底，但不伪造教师评分。
        if course_type in ("naming", "onomatopoeia") and teacher_score is None:
            receptive = _metric_section(metrics, "receptive")
            historical = receptive.get("score")
            if historical is None:
                historical = receptive.get("pass_rate")
            historical = _normalize_rate(historical)
            if historical is not None:
                course_points[course_type].append(historical)
                performance_points[course_type].append(historical)

        if response_ms is not None:
            try:
                response = float(response_ms)
                if 0 <= response <= 7_200_000:
                    response_points[course_type].append(response)
                    if course_type in ("pairing", "ordering") and accuracy is not None:
                        response_sample_counts[course_type] += _interactive_evidence_count(
                            metrics, objective
                        )
                    else:
                        response_sample_counts[course_type] += 1
            except (TypeError, ValueError):
                pass

    raw_course_scores = {key: _mean(values) for key, values in course_points.items()}
    raw_performance_by_type = {key: _mean(values) for key, values in performance_points.items()}
    raw_response_by_type = {key: _mean(values) for key, values in response_points.items()}
    minimum_samples = _minimum_effective_samples(cfg)
    sufficient_types = {
        key
        for key, score in raw_course_scores.items()
        if score is not None and evidence_counts.get(key, 0) >= minimum_samples[key]
    }
    course_scores = {
        key: value if key in sufficient_types else None
        for key, value in raw_course_scores.items()
    }
    performance_by_type = {
        key: value if key in sufficient_types else None
        for key, value in raw_performance_by_type.items()
    }
    response_by_type = {
        key: value if key in sufficient_types else None
        for key, value in raw_response_by_type.items()
    }
    course_weights = cfg.get("course_weights") or DEFAULT_COURSE_WEIGHTS
    overall = _weighted_mean(course_scores, course_weights)
    task_performance = _weighted_mean(performance_by_type, course_weights)
    avg_response_ms = _weighted_mean(response_by_type, course_weights)
    target_score = _clamp(
        float(
            cfg.get(
                "course_goal_score",
                (cfg.get("grade_thresholds") or {}).get("good", 70),
            )
        )
    )
    course_evaluations = []
    for course_type in active_course_types:
        label = COURSE_LABELS[course_type]
        score = course_scores.get(course_type)
        provisional_score = raw_course_scores.get(course_type)
        observed = int(observed_counts.get(course_type) or 0)
        if score is not None:
            status = "evaluated"
        elif provisional_score is not None or observed > 0:
            status = "insufficient_data"
        else:
            status = "not_evaluated"
        course_evaluations.append({
            "courseType": course_type,
            "label": label,
            "status": status,
            "score": round(float(score), 1) if score is not None else None,
            "provisionalScore": (
                round(float(provisional_score), 1)
                if provisional_score is not None and score is None else None
            ),
            "targetScore": round(float(target_score), 1),
            "gapToTarget": (
                round(float(score) - float(target_score), 1)
                if score is not None else None
            ),
            "itemCount": observed,
            "teacherRatingCount": int(rating_counts.get(course_type) or 0),
            "validSampleCount": int(evidence_counts.get(course_type) or 0),
            "requiredSampleCount": int(minimum_samples[course_type]),
            "sampleUnit": COURSE_SAMPLE_UNITS[course_type],
            "sampleAdequacy": round(
                min(1.0, evidence_counts.get(course_type, 0) / minimum_samples[course_type]),
                3,
            ),
            "contributesToOverall": score is not None,
        })

    return {
        "course_scores": course_scores,
        "raw_course_scores": raw_course_scores,
        "overall": overall,
        "performance_by_type": performance_by_type,
        "task_performance": task_performance,
        "response_by_type_ms": response_by_type,
        "avg_response_ms": avg_response_ms,
        "covered_course_types": [key for key, value in response_by_type.items() if value is not None],
        "response_sample_count": sum(
            response_sample_counts[key] for key in sufficient_types
        ),
        "rating_counts": rating_counts,
        "observed_counts": observed_counts,
        "evidence_counts": evidence_counts,
        "minimum_samples": minimum_samples,
        "insufficient_course_types": sorted(
            key
            for key, value in raw_course_scores.items()
            if value is not None and key not in sufficient_types
        ),
        "has_course_evidence": any(value is not None for value in raw_course_scores.values()),
        "course_evaluations": course_evaluations,
        "course_goal_score": target_score,
        "missing_rating_types": sorted(missing_rating_types),
    }


def _legacy_expressive(summary: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[float]:
    lang = summary.get("language") or {}
    speech_ratio = lang.get("avg_speech_ratio")
    word_count = lang.get("total_word_count") or 0
    if speech_ratio is None and not word_count:
        return None
    exp = cfg.get("expressive") or {}
    cap = float(exp.get("word_count_cap", 40) or 40)
    speech_score = _clamp((speech_ratio or 0) * 100)
    word_score = _clamp(float(word_count) / cap * 100) if cap > 0 else 0
    return _clamp(speech_score * 0.7 + word_score * 0.3)


def _legacy_receptive(summary: Dict[str, Any]) -> Optional[float]:
    task = summary.get("task") or {}
    values = [_normalize_rate(task.get(key)) for key in (
        "matching_accuracy", "sequencing_accuracy", "receptive_pass_rate"
    )]
    return _mean(v for v in values if v is not None)


def grade_label(overall: float, thresholds: Dict[str, Any]) -> str:
    if overall >= float(thresholds.get("excellent", 85)):
        return "优秀 (Excellent)"
    if overall >= float(thresholds.get("good", 70)):
        return "良好 (Good)"
    if overall >= float(thresholds.get("fair", 55)):
        return "一般 (Fair)"
    return "需加强 (Needs Support)"


def _expected_dimensions(summary: Dict[str, Any]) -> set:
    expected = set()
    if summary.get("windows") or (summary.get("attention") or {}).get("avg_score") is not None:
        expected.add("attention")
    for window in summary.get("windows") or []:
        course_type = _canonical_course_type(window.get("course_type"))
        expected.update(COURSE_TYPE_EXPECTATIONS.get(course_type, []))
    return expected


def compute_dimensions(
    summary: Dict[str, Any],
    cfg: Optional[Dict[str, Any]] = None,
    *,
    soft: bool = True,
) -> Dict[str, Any]:
    cfg = cfg or load_scoring_config()
    legacy_weights = cfg.get("weights") or DEFAULT_WEIGHTS
    expected = _expected_dimensions(summary)
    course_metrics = build_course_metrics(summary, cfg)
    course_scores = course_metrics["course_scores"]

    dimension_cfg = cfg.get("dimension_weights") or {}
    attention_auto = (summary.get("attention") or {}).get("avg_score")
    attention_weights = dimension_cfg.get("attention") or {"automatic": 1.0}
    attention = _weighted_mean(
        {"automatic": attention_auto},
        attention_weights,
    )
    expressive = _weighted_mean(
        {"naming": course_scores.get("naming"), "onomatopoeia": course_scores.get("onomatopoeia")},
        dimension_cfg.get("expressive") or {"naming": 1, "onomatopoeia": 1},
    )
    if expressive is None:
        expressive = _legacy_expressive(summary, cfg)
    receptive = _weighted_mean(
        {key: course_scores.get(key) for key in ("pairing", "ordering", "naming", "onomatopoeia")},
        dimension_cfg.get("receptive") or {
            "pairing": 1, "ordering": 1, "naming": 1, "onomatopoeia": 1,
        },
    )
    if receptive is None:
        receptive = _legacy_receptive(summary)

    task = summary.get("task") or {}
    matching = course_scores.get("pairing")
    observed_counts = course_metrics["observed_counts"]
    if matching is None and not observed_counts.get("pairing", 0):
        matching = _normalize_rate(task.get("matching_accuracy"))
    ordering = course_scores.get("ordering")
    if ordering is None and not observed_counts.get("ordering", 0):
        ordering = _normalize_rate(task.get("sequencing_accuracy"))

    all_values: List[Tuple[str, Optional[float], str]] = [
        ("attention", attention, "ATTENTION_DATA_MISSING"),
        ("expressiveLanguage", expressive, "EXPRESSIVE_DATA_MISSING"),
        ("receptiveLanguage", receptive, "RECEPTIVE_DATA_MISSING"),
        ("matching", matching, "MATCHING_DATA_MISSING"),
        ("ordering", ordering, "SEQUENCING_DATA_MISSING"),
    ]
    configured_dimensions = cfg.get("enabled_dimension_keys")
    dimension_keys = (
        {str(key) for key in configured_dimensions}
        if isinstance(configured_dimensions, list)
        else {key for key, _value, _limitation in all_values}
    )
    values = [item for item in all_values if item[0] in dimension_keys]
    dimensions: Dict[str, Any] = {}
    modules: Dict[str, str] = {}
    limitations: List[str] = list(summary.get("limitations") or [])
    for key, value, limitation in values:
        status = "ready" if value is not None else ("pending" if soft and key in expected else "missing")
        dimensions[key] = {
            "score": round(float(value), 1) if value is not None else None,
            "available": value is not None,
            "status": status,
            "weight": float(legacy_weights.get(key, 0)),
        }
        modules[key] = status
        if value is None:
            limitations.append(limitation)

    overall = course_metrics.get("overall")
    if overall is None and not course_metrics["has_course_evidence"]:
        # 历史训练没有可构造的课程分时，维持旧的五维加权回退。
        overall = _weighted_mean(
            {key: dimensions[key]["score"] for key in dimensions},
            legacy_weights,
        )
    overall = round(float(overall), 1) if overall is not None else None

    if course_metrics["missing_rating_types"]:
        limitations.append("TEACHER_RATING_MISSING")
    if course_metrics["insufficient_course_types"]:
        limitations.append("COURSE_SAMPLE_INSUFFICIENT")
    unique_limitations = list(dict.fromkeys(item for item in limitations if item))
    any_pending = any(status == "pending" for status in modules.values())
    report_status = "PARTIAL" if any_pending else "READY"
    modules["narrative"] = "ready" if overall is not None else "pending"
    modules["attentionCurve"] = (
        "ready" if attention_auto is not None else ("pending" if soft and "attention" in expected else "missing")
    )

    return {
        "dimensions": dimensions,
        "modules": modules,
        "status": report_status,
        "overall": overall,
        "grade": grade_label(overall, cfg.get("grade_thresholds") or {}) if overall is not None else "数据加载中",
        "overallNote": (
            "按达到最低有效样本量的课程类型平衡计算"
            if overall is not None else None
        ),
        "limitations": unique_limitations,
        "formulaVersion": cfg.get("schema_version", "education-training-index-v2-teacher-rating"),
        "formulaFingerprint": scoring_config_fingerprint(cfg),
        "scoreBoundary": cfg.get("score_boundary", "education_training_reference_only"),
        "courseScores": {
            key: (round(value, 1) if value is not None else None)
            for key, value in course_scores.items()
        },
        "courseEvaluations": course_metrics["course_evaluations"],
        "courseGoalScore": round(float(course_metrics["course_goal_score"]), 1),
        "taskPerformance": (
            round(course_metrics["task_performance"], 1)
            if course_metrics["task_performance"] is not None else None
        ),
        "responseMetrics": {
            "avgResponseMs": (
                round(course_metrics["avg_response_ms"], 1)
                if course_metrics["avg_response_ms"] is not None else None
            ),
            "sampleCount": course_metrics["response_sample_count"],
            "coveredCourseTypes": course_metrics["covered_course_types"],
            "byCourseTypeMs": {
                key: (round(value, 1) if value is not None else None)
                for key, value in course_metrics["response_by_type_ms"].items()
            },
        },
        "teacherRatingCounts": course_metrics["rating_counts"],
    }
