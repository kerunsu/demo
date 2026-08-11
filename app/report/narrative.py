"""规则叙事：禁止临床诊断措辞；支持 narrative_provider: rule | mock。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.logger import setup_logger

logger = setup_logger("report_narrative")


def _mock_narrative(report_core: Dict[str, Any]) -> Dict[str, Any]:
    overall = report_core.get("overall")
    return {
        "status": "READY",
        "provider": "mock",
        "analysis": (
            "【演示占位叙事】本段为 mock 叙事，不反映真实算法结论。"
            + (f" 综合参考分占位为 {overall}。" if overall is not None else "")
            + " 正式环境请使用 narrative_provider: rule。"
        ),
        "recommendations": [
            {
                "title": "演示建议",
                "body": "这是 mock 推荐条目，仅用于联调界面布局。",
            }
        ],
        "disclaimer": "本报告仅供教育训练参考，不构成诊断或医疗建议。",
    }


def _rule_narrative(report_core: Dict[str, Any]) -> Dict[str, Any]:
    dims = report_core.get("dimensions") or {}
    overall = report_core.get("overall")
    limitations = report_core.get("limitations") or []
    curve = report_core.get("attentionCurve") or []

    low_dims = [
        name for name, meta in dims.items()
        if meta.get("available") and (meta.get("score") or 0) < 55
    ]
    strong_dims = [
        name for name, meta in dims.items()
        if meta.get("available") and (meta.get("score") or 0) >= 75
    ]

    name_map = {
        "attention": "注意力",
        "expressiveLanguage": "表达性语言",
        "receptiveLanguage": "接受性语言",
        "matching": "配对",
        "ordering": "排序",
    }

    dip_note = ""
    if curve:
        scored = [(c.get("question_index"), c.get("score")) for c in curve if c.get("score") is not None]
        if scored:
            min_item = min(scored, key=lambda x: x[1])
            dip_note = f"注意力曲线在第 {min_item[0] + 1} 个课点附近出现相对低点（约 {min_item[1]:.0f}）。"

    analysis_parts = [
        "本报告仅供教育训练参考，不构成任何临床或诊断结论。",
    ]
    if overall is not None:
        analysis_parts.append(f"本次训练综合参考分为 {overall}。")
    if strong_dims:
        analysis_parts.append(
            "相对优势维度：" + "、".join(name_map.get(d, d) for d in strong_dims) + "。"
        )
    if low_dims:
        analysis_parts.append(
            "可重点关注维度：" + "、".join(name_map.get(d, d) for d in low_dims) + "。"
        )
    if dip_note:
        analysis_parts.append(dip_note)
    if limitations:
        from app.report.limitations_copy import translate_limitations

        labels = translate_limitations(limitations)
        analysis_parts.append(
            "部分维度因数据不足已降级展示：" + "、".join(labels[:5]) + "。"
        )

    recommendations: List[Dict[str, str]] = []
    if "ordering" in low_dims:
        recommendations.append({
            "title": "多步指令练习",
            "body": "日常生活中可增加「先…再…最后…」的短指令游戏，帮助巩固顺序执行习惯。",
        })
    if "attention" in low_dims:
        recommendations.append({
            "title": "短时专注任务",
            "body": "用短时视觉寻找或配对小游戏，逐步延长专注窗口，避免一次任务过长。",
        })
    if "expressiveLanguage" in low_dims:
        recommendations.append({
            "title": "表达鼓励",
            "body": "在安全、低压力情境下鼓励孩子用完整短句描述所见，成人可做示范与扩展。",
        })
    if not recommendations:
        recommendations.append({
            "title": "保持节奏",
            "body": "继续按当前课程节奏训练，并关注孩子情绪与参与度，适时给予正向反馈。",
        })

    return {
        "status": "READY",
        "provider": "rule",
        "analysis": " ".join(analysis_parts),
        "recommendations": recommendations,
        "disclaimer": "本报告仅供教育训练参考，不构成诊断或医疗建议。",
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
