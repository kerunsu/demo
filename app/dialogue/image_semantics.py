"""互动课图片语义：人读名称（禁止「物品064」/文件路径）。"""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional, Tuple

import yaml

from app.config import BASE_DIR
from app.utils.logger import setup_logger

logger = setup_logger("dialogue.image_semantics")

_DEFAULT_PATH = BASE_DIR / "config" / "interactive_image_semantics.yaml"
_lock = Lock()
_cache: Optional[Dict[str, Any]] = None

# 客户端/服务端共用的内置兜底（与 yaml 对齐）
BUILTIN_MATCHING: Dict[str, Dict[str, str]] = {
    "image_1.jpg": {"label": "苹果", "description": "一颗红色苹果"},
    "image_2.jpg": {"label": "桃子", "description": "一个粉色桃子"},
    "image_3.jpg": {"label": "香蕉", "description": "一串黄色香蕉"},
    "image_4.jpg": {"label": "菠萝", "description": "一个黄色菠萝"},
    "image_5.jpg": {"label": "西瓜", "description": "一个绿色西瓜"},
    "image_6.jpg": {"label": "草莓", "description": "一颗红色草莓"},
    "image_7.jpg": {"label": "葡萄", "description": "一串紫色葡萄"},
    "057": {"label": "小汽车", "description": "一辆红色小汽车"},
    "058": {"label": "篮球", "description": "一个橙色篮球"},
    "059": {"label": "绿色尖尖块", "description": "一个绿色尖尖块"},
    "060": {"label": "水杯", "description": "一个蓝色水杯"},
    "061": {"label": "椅子", "description": "一把橙色椅子"},
    "062": {"label": "自行车", "description": "一辆小自行车"},
    "063": {"label": "碗", "description": "一个黄色的碗"},
    "064": {"label": "彩色球", "description": "一个彩色球"},
}

BUILTIN_ORDERING_PREFIXES: Dict[str, str] = {
    "Circle": "圆",
    "Square": "方块",
    "Triangle": "三角",
    "carrot": "胡萝卜",
    "pencil": "铅笔",
    "ruler": "尺子",
    "train": "火车",
    "house": "房子",
    "house-red": "红房子",
    "apple": "苹果",
    "cookie": "饼干",
    "cup": "杯子",
}

# 命名等：短特征线索（颜色自然用颜色；大型哺乳用性情/体型/可爱）
BUILTIN_ITEM_CUES: Dict[str, str] = {
    "草莓": "红红的草莓",
    "苹果": "红红的苹果",
    "香蕉": "黄黄的香蕉",
    "西瓜": "绿绿的西瓜",
    "葡萄": "紫紫的葡萄",
    "青蛙": "可爱的青蛙",
    "瓢虫": "红红的瓢虫",
    "狮子": "凶猛的狮子",
    "老虎": "凶猛的老虎",
    "羊": "可爱的小羊",
    "小羊": "可爱的小羊",
    "猫": "可爱的小猫",
    "狗": "可爱的小狗",
    "熊猫": "胖胖的熊猫",
    "斑马": "条纹的斑马",
    "大象": "大大的大象",
    "长颈鹿": "高高的长颈鹿",
    "兔": "可爱的小兔",
    "兔子": "可爱的小兔",
}


def get_semantics(force_reload: bool = False) -> Dict[str, Any]:
    global _cache
    with _lock:
        if _cache is not None and not force_reload:
            return _cache
        matching = dict(BUILTIN_MATCHING)
        prefixes = dict(BUILTIN_ORDERING_PREFIXES)
        item_cues = dict(BUILTIN_ITEM_CUES)
        path = Path(_DEFAULT_PATH)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                for k, v in (data.get("matching") or {}).items():
                    if isinstance(v, dict) and v.get("label"):
                        matching[str(k)] = {
                            "label": str(v["label"]),
                            "description": str(v.get("description") or v["label"]),
                        }
                    elif isinstance(v, str) and v.strip():
                        matching[str(k)] = {"label": v.strip(), "description": v.strip()}
                for k, v in (data.get("ordering_prefixes") or {}).items():
                    if v:
                        prefixes[str(k)] = str(v)
                for k, v in (data.get("item_cues") or {}).items():
                    if k and v:
                        item_cues[str(k).strip()] = str(v).strip()
            except Exception as e:
                logger.warning("加载 interactive_image_semantics 失败: %s", e)
        _cache = {
            "matching": matching,
            "ordering_prefixes": prefixes,
            "item_cues": item_cues,
        }
        return _cache


def item_cue_from_label(label: str) -> str:
    """物品名 → 孩子能听懂的短特征说法；未命中返回空串。"""
    name = str(label or "").strip()
    if not name:
        return ""
    bank = get_semantics().get("item_cues") or {}
    hit = bank.get(name)
    if hit:
        return str(hit)
    # 「小狮子」等：去掉前缀「小」再查
    if name.startswith("小") and len(name) > 1:
        hit = bank.get(name[1:])
        if hit:
            return str(hit)
    return ""


def _matching_rel_candidates(src: str) -> list:
    """从 URL/路径提取可查 key：相对 matching 路径、文件夹号、文件名。"""
    s = str(src or "").replace("\\", "/")
    keys = []
    marker = "/matching/"
    idx = s.lower().find(marker)
    if idx >= 0:
        rel = s[idx + len(marker) :]
        keys.append(rel)
        parts = [p for p in rel.split("/") if p]
        if len(parts) >= 2:
            keys.append(parts[0])  # folder
            keys.append("/".join(parts[-2:]))
        if parts:
            keys.append(parts[-1])  # filename
    else:
        parts = [p for p in s.split("/") if p]
        if parts:
            keys.append(parts[-1])
            if len(parts) >= 2:
                keys.append(parts[-2])
                keys.append(f"{parts[-2]}/{parts[-1]}")
    # 去重保序
    seen = set()
    out = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def matching_label_from_src(src: str, fallback_index: Optional[int] = None) -> str:
    """人读名称；未命中时：无下标→「这张」，选项0→「左边」，永不返回物品NNN 或路径。"""
    bank = get_semantics().get("matching") or {}
    for key in _matching_rel_candidates(src):
        hit = bank.get(key)
        if isinstance(hit, dict) and hit.get("label"):
            return str(hit["label"])
        if isinstance(hit, str) and hit.strip():
            return hit.strip()
    if fallback_index is None:
        return "这张"
    if fallback_index == 0:
        return "左边"
    return f"第{fallback_index + 1}张"


def matching_semantic_from_src(src: str) -> Dict[str, str]:
    bank = get_semantics().get("matching") or {}
    for key in _matching_rel_candidates(src):
        hit = bank.get(key)
        if isinstance(hit, dict) and hit.get("label"):
            return {
                "label": str(hit["label"]),
                "description": str(hit.get("description") or hit["label"]),
            }
    label = matching_label_from_src(src, 0)
    return {"label": label, "description": label}


def ordering_object_name(prefix: str) -> str:
    bank = get_semantics().get("ordering_prefixes") or {}
    if prefix in bank:
        return str(bank[prefix])
    # 宽松：忽略大小写
    lower_map = {str(k).lower(): v for k, v in bank.items()}
    hit = lower_map.get(str(prefix or "").lower())
    if hit:
        return str(hit)
    # 未知前缀：仍用人话，不用文件名
    clean = str(prefix or "").strip()
    if clean and not clean.isdigit() and "/" not in clean and "\\" not in clean:
        return clean
    return "东西"


def ordering_option_label(
    prefix: str,
    level: Optional[int] = None,
    index: Optional[int] = None,
    *,
    include_degree: bool = True,
) -> str:
    name = ordering_object_name(prefix)
    side = None
    if index is not None:
        if index == 0:
            side = "左边"
        elif index == 1:
            side = "右边"
        else:
            side = f"第{index + 1}张"
    parts = []
    if side:
        parts.append(side)
    parts.append(name)
    if include_degree and level is not None:
        parts.append(f"（程度{level}）")
    return "".join(parts) if side else (f"{name}（程度{level}）" if level is not None else name)


def is_filename_like(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    if "/" in t or "\\" in t:
        return True
    if t.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return True
    if t.startswith("物品") and t[2:].isdigit():
        return True
    return False


def humanize_label(text: Any, fallback: str = "左边") -> str:
    """页上下文展示用：丢掉路径/物品NNN。"""
    if text is None:
        return fallback
    s = str(text).strip()
    if not s or is_filename_like(s):
        return fallback
    return s
