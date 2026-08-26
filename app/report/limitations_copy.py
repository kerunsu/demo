"""报告 / 监控 limitations 原因码 → 中文文案。"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

LIMITATION_LABELS = {
    "TEACHER_RATING_MISSING": "部分课点缺少教师评分，相关结果仅依据已有有效记录呈现",
    "LANGUAGE_DATA_MISSING": "语言过程样本不足，相关结果仅依据有效课程作答形成",
    "EXPRESSIVE_DATA_MISSING": "表达性语言有效结果不足，本次未作推断",
    "RECEPTIVE_DATA_MISSING": "接受性语言有效结果不足，本次未作推断",
    "MATCHING_DATA_MISSING": "配对课程未形成足够的有效结果",
    "SEQUENCING_DATA_MISSING": "排序课程未形成足够的有效结果",
    "ATTENTION_DATA_MISSING": "注意力有效样本不足（含无人脸/摄像头不可用）",
    "ATTENTION_PROVIDER_DEGRADED_OR_MOCK": "注意力分析器为演示/占位数据，仅供参考",
    "SPEECH_PROVIDER_MOCK": "语音分析器为演示/占位数据，仅供参考",
    "DEMO_OR_MOCK_ANALYZERS": "当前使用 Mock 分析器，监控与报告为演示数据",
    "PREVIEW_DISABLED": "监控预览未启用",
    "PREVIEW_STALE": "监控预览帧已过期",
    "PREVIEW_UNAVAILABLE": "暂无可用预览帧（agent 尚未上行）",
    "NO_ATTENTION_OBSERVATIONS": "暂无注意力观测（warmup 或分析未启动）",
    "behavior_store_unavailable": "行为存储不可用，监控数据可能不完整",
    "DIMENSION_ATTENTION_UNAVAILABLE": "注意力维度数据不足，未计入综合分",
    "DIMENSION_EXPRESSIVE_UNAVAILABLE": "表达性语言维度数据不足，未计入综合分",
    "DIMENSION_RECEPTIVE_UNAVAILABLE": "接受性语言维度数据不足，未计入综合分",
    "DIMENSION_MATCHING_UNAVAILABLE": "配对维度数据不足，未计入综合分",
    "DIMENSION_ORDERING_UNAVAILABLE": "排序维度数据不足，未计入综合分",
}


def translate_limitation(code: Optional[str]) -> str:
    if not code:
        return ""
    text = str(code).strip()
    if not text:
        return ""
    # 已是中文说明则原样返回
    if text in LIMITATION_LABELS.values():
        return text
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return text
    known = LIMITATION_LABELS.get(text)
    if known:
        return known
    # 教师可见投影不能泄露未知的内部原因码。未知码仍保留在原始
    # dataQuality.limitations 中供审计，这里只给出可理解的边界说明。
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", text):
        return "部分过程数据未形成有效结果，相关项目未作推断"
    return text


def translate_limitations(codes: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for code in codes or []:
        label = translate_limitation(code)
        if not label or label in seen:
            continue
        seen.add(label)
        out.append(label)
    return out
