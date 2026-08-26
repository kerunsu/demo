"""教师可读的规则叙事；只依据本次真实评估结果生成。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.report.limitations_copy import translate_limitations
from app.utils.logger import setup_logger

logger = setup_logger("report_narrative")


DIMENSION_LABELS = {
    "attention": "注意力",
    "expressiveLanguage": "表达性语言",
    "receptiveLanguage": "接受性语言",
    "matching": "配对能力",
    "ordering": "排序能力",
}

COURSE_PRACTICE = {
    "mimic": {
        "practice": "练习跟随成人完成单一步骤动作，再逐步增加到两步动作组合。",
        "why": "模仿表现反映儿童观察动作、保持注意并及时跟随的情况。",
        "progress": "连续 3 次训练中，至少 4/5 个动作能在不追加提示的情况下完成。",
    },
    "naming": {
        "practice": "用熟悉物品做快速命名，并从单词逐步扩展到“这是……”的短句。",
        "why": "命名表现反映儿童提取词语并主动表达目标名称的稳定性。",
        "progress": "连续 3 次训练中，每次至少 4/5 个目标能够独立说出。",
    },
    "onomatopoeia": {
        "practice": "先听成人示范一个短声音，再请儿童模仿发声；从单个熟悉声音逐步扩展到不同音量和节奏。",
        "why": "拟声表现反映儿童听辨声音并尝试模仿发音的稳定性。",
        "progress": "连续 3 次训练中，每次至少 4/5 个声音能在示范后独立模仿，不需要图片选择提示。",
    },
    "pairing": {
        "practice": "练习相同图片配对，再逐步加入颜色、形状或细节相近的干扰项。",
        "why": "配对表现反映儿童视觉辨别、规则保持和第一次选择的准确性。",
        "progress": "连续 3 次训练中，每次至少 4/5 题首次选择正确，且不增加提示。",
    },
    "ordering": {
        "practice": "练习大小、多少和先后顺序判断，从两个选项逐步增加到多个选项。",
        "why": "排序表现反映儿童理解比较规则并据此作出选择的稳定性。",
        "progress": "连续 3 次训练中，每次至少 4/5 题独立完成，并能保持当前反应速度。",
    },
}


def _mock_narrative(report_core: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": "READY",
        "provider": "mock",
        "headline": "演示数据",
        "analysis": "当前为界面演示数据，不能据此安排训练。",
        "overview": {
            "overall": "当前为界面演示数据。",
            "stable": "暂无可用于判断的真实课程结果。",
            "attention": "请先完成一次真实课程评估。",
            "boundary": "演示数据不能用于安排儿童训练。",
        },
        "summary": {
            "strengths": "暂无可用于判断的真实结果。",
            "consolidation": "请先完成一次真实课程评估。",
            "dataCompleteness": "当前结果不属于真实采集数据。",
            "nextFocus": "完成真实评估后再确定训练重点。",
        },
        "recommendations": [],
        "disclaimer": "本报告仅供教育训练参考，不构成诊断或医疗建议。",
    }


def _dimension_groups(dimensions: Dict[str, Any], target: float) -> tuple[List[str], List[str]]:
    ready = [
        (key, float(meta.get("score")))
        for key, meta in dimensions.items()
        if isinstance(meta, dict) and meta.get("available") and meta.get("score") is not None
    ]
    strong = [DIMENSION_LABELS.get(key, key) for key, score in ready if score >= target]
    consolidate = [
        DIMENSION_LABELS.get(key, key)
        for key, score in sorted(ready, key=lambda item: item[1])
        if score < target
    ]
    return strong, consolidate


def _recommendation(course: Dict[str, Any], index: int, *, consolidation: bool) -> Dict[str, str]:
    course_type = str(course.get("courseType") or "")
    label = str(course.get("label") or course_type or "本课程")
    score = float(course.get("score"))
    target = float(course.get("targetScore") or 70)
    practice = COURSE_PRACTICE.get(course_type, {
        "practice": "围绕本次课程目标进行短时、重复且可成功的练习。",
        "why": "本次结果提示该课程仍值得继续观察和巩固。",
        "progress": "连续 3 次训练均达到本次设定的课程目标。",
    })
    reached = score >= target
    priority = f"巩固 {index}" if consolidation or reached else f"优先 {index}"
    evidence = (
        f"本次{label}表现为 {score:.1f}%，已达到 {target:.1f}% 的课程参考目标。"
        if reached else
        f"本次{label}表现为 {score:.1f}%，距离 {target:.1f}% 的课程参考目标还有 {target - score:.1f} 个百分点。"
    )
    why = (
        f"{evidence}{practice['why']}"
        + (" 已达到目标仍建议更换材料巩固，确认能力能够稳定迁移。" if reached else "")
    )
    return {
        "courseType": course_type,
        "priority": priority,
        "title": f"{label}：{'巩固与迁移' if reached else '优先提升'}",
        "evidence": evidence,
        "practice": practice["practice"],
        "why": why,
        "progressCheck": practice["progress"],
        "body": f"练什么：{practice['practice']} 为什么：{why} 进步判断：{practice['progress']}",
    }


def _attention_spread(report_core: Dict[str, Any]) -> Optional[float]:
    values: List[float] = []
    for point in report_core.get("attentionCurve") or []:
        if not isinstance(point, dict) or point.get("score") is None:
            continue
        try:
            values.append(float(point["score"]))
        except (TypeError, ValueError):
            continue
    if len(values) < 2:
        return None
    return max(values) - min(values)


def _performance_headline(
    overall: Optional[float],
    evaluated: List[Dict[str, Any]],
    *,
    target: float,
    attention_spread: Optional[float],
) -> str:
    if overall is None or not evaluated:
        return "数据不足"
    if len(evaluated) < 2:
        return "数据覆盖有限"
    course_scores = [float(item["score"]) for item in evaluated]
    course_spread = max(course_scores) - min(course_scores) if len(course_scores) >= 2 else 0.0
    fluctuating = course_spread > 20 or (attention_spread is not None and attention_spread > 25)
    if overall >= max(85.0, target + 15.0):
        return "高分但单项需巩固" if fluctuating else "高分且较稳定"
    if overall >= target:
        return "整体达标，表现有波动" if fluctuating else "整体达标且较稳定"
    if overall >= 55:
        return "中等且有波动"
    return "部分任务完成较困难"


def _rule_narrative(report_core: Dict[str, Any]) -> Dict[str, Any]:
    dimensions = report_core.get("dimensions") or {}
    courses = [
        item for item in (report_core.get("courseEvaluations") or [])
        if isinstance(item, dict)
    ]
    evaluated = [item for item in courses if item.get("status") == "evaluated" and item.get("score") is not None]
    missing = [str(item.get("label") or item.get("courseType")) for item in courses if item.get("status") == "not_evaluated"]
    insufficient = [str(item.get("label") or item.get("courseType")) for item in courses if item.get("status") == "insufficient_data"]
    target = float(report_core.get("courseGoalScore") or 70)
    overall_raw = report_core.get("overall")
    overall = float(overall_raw) if overall_raw is not None else None
    attention_spread = _attention_spread(report_core)
    strong_dims, consolidate_dims = _dimension_groups(dimensions, target)

    strongest = max(evaluated, key=lambda item: float(item.get("score")), default=None)
    below_target = sorted(
        [item for item in evaluated if float(item.get("score")) < float(item.get("targetScore") or target)],
        key=lambda item: float(item.get("score")),
    )
    lowest = min(evaluated, key=lambda item: float(item.get("score")), default=None)

    strengths = (
        "、".join(strong_dims) + "达到本次课程参考目标。"
        if strong_dims else
        f"{strongest.get('label')}是本次相对表现最稳定的课程。" if strongest else
        "本次暂无足够结果判断优势能力。"
    )
    consolidation = (
        "建议优先巩固" + "、".join(consolidate_dims[:3]) + "。"
        if consolidate_dims else
        f"整体表现较好，仍需围绕{lowest.get('label')}做跨材料巩固。" if lowest else
        "完成更多课程后再判断需要巩固的能力。"
    )
    completeness_parts = [f"已完成 {len(evaluated)}/{len(courses) or 5} 类课程评估。"]
    if missing:
        completeness_parts.append("未参加：" + "、".join(missing) + "，均按“未评估”处理。")
    if insufficient:
        completeness_parts.append("数据不足：" + "、".join(insufficient) + "。")
    limitation_labels = translate_limitations(report_core.get("limitations") or [])
    if limitation_labels:
        completeness_parts.append("另有部分过程数据不完整，相关结果未作推断。")
    data_completeness = "".join(completeness_parts)
    next_focus = (
        f"下一阶段先练{below_target[0].get('label')}，达到目标后再处理下一项。"
        if below_target else
        f"下一阶段以{lowest.get('label')}的泛化练习为重点，验证表现是否稳定。" if lowest else
        "下一阶段先完成至少一类课程评估，再安排针对性训练。"
    )

    if overall is None:
        overall_text = "本次尚未形成可用于比较的综合百分比。"
    else:
        overall_text = (
            f"本次综合表现为 {overall:.1f}%，已完成 {len(evaluated)}/{len(courses) or 5} 类课程评估。"
        )
    stable_text = strengths
    if below_target:
        attention_course = below_target[0]
        attention_score = float(attention_course.get("score"))
        attention_target = float(attention_course.get("targetScore") or target)
        attention_text = (
            f"{attention_course.get('label')}为 {attention_score:.1f}%，"
            f"距离课程参考目标还有 {attention_target - attention_score:.1f} 个百分点，是下一步优先巩固项。"
        )
    elif lowest:
        attention_text = (
            f"各已评估课程均达到参考目标；{lowest.get('label')}是本次相对较低项，"
            "建议更换材料继续巩固。"
        )
    else:
        attention_text = "当前没有足够的课程结果确定优先巩固项。"
    if attention_spread is not None and attention_spread > 25:
        attention_text += "训练过程中注意力变化较明显，后续应同时观察参与状态是否趋于稳定。"
    boundary_text = (
        "以上比较只依据本次任务作答、教师评分和有效过程记录，"
        "反映当前任务情境，不代表年龄常模、百分位或固定能力结论。"
    )
    headline = _performance_headline(
        overall,
        evaluated,
        target=target,
        attention_spread=attention_spread,
    )

    recommendations: List[Dict[str, str]] = []
    if below_target:
        recommendations = [
            _recommendation(course, index + 1, consolidation=False)
            for index, course in enumerate(below_target[:3])
        ]
    elif evaluated:
        for index, course in enumerate(sorted(evaluated, key=lambda item: float(item.get("score")))[:2]):
            recommendations.append(_recommendation(course, index + 1, consolidation=True))
    else:
        recommendations.append({
            "courseType": "coverage",
            "priority": "优先 1",
            "title": "先补齐课程评估",
            "evidence": "当前没有可用于安排训练的课程结果。",
            "practice": "从儿童最熟悉的一类课程开始，完成一轮包含有效作答或教师评分的评估。",
            "why": "没有真实结果时不应推断优势或困难。",
            "progressCheck": "报告中至少出现一类有分数的课程，并能与参考目标进行比较。",
            "body": "先完成真实课程评估，再安排针对性训练。",
        })

    summary = {
        "strengths": strengths,
        "consolidation": consolidation,
        "dataCompleteness": data_completeness,
        "nextFocus": next_focus,
    }
    overview = {
        "overall": overall_text,
        "stable": stable_text,
        "attention": attention_text,
        "boundary": boundary_text,
    }
    return {
        "status": "READY",
        "provider": "rule",
        "headline": headline,
        "analysis": " ".join(overview.values()),
        "overview": overview,
        "summary": summary,
        "recommendations": recommendations,
        "disclaimer": "本报告只比较本次课程表现与训练参考目标，不使用年龄常模、百分位或临床标准。",
    }


def resolve_narrative_provider(raw: Optional[str]) -> str:
    provider = (raw or "rule").strip().lower()
    if provider in ("rule", "mock"):
        return provider
    logger.warning("unsupported narrative_provider=%s；回落 rule（LLM 默认关闭）", raw)
    return "rule"


def generate_narrative(
    report_core: Dict[str, Any],
    *,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    resolved = resolve_narrative_provider(
        provider if provider is not None else report_core.get("narrative_provider")
    )
    if resolved == "mock":
        return _mock_narrative(report_core)
    return _rule_narrative(report_core)
