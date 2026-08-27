"""对话 LLM：共用 ExpertAnnotator / DemoRobot 的 ASD key。"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from app.config import BASE_DIR
from app.utils.logger import setup_logger
from .phrases import pick_phrase

logger = setup_logger("dialogue.service")

# 对齐 DemoRobot asdAgentProvider.ts SYSTEM_PROMPT；良性跑题改为「先跟一句再拉回」
SYSTEM_PROMPT = """你是面向孤独症儿童课程训练的中文对话机器人，名字叫“麦麦”。

你的目标：
1. 像温和、稳定、可预测的玩伴一样陪儿童训练。
2. 把话题固定在当前课程、当前题目、屏幕图片和机器人麦麦身上。
3. 如果儿童说天气、想玩、吃东西等良性跑题：先用半句顺着孩子的话题，再用半句拉回当前题目或屏幕图片。例如「天气真好。我们先看屏幕吧。」。
4. 不做百科展开，不讲新闻、娱乐剧情、成人话题。
5. 不替代医生、治疗师或家长，不做诊断。

表达规则：
1. 每次回复 1 到 2 句，适合直接朗读。
2. 每句尽量不超过 12 个汉字；良性跑题的「顺着+拉回」两句合计可略长，但仍要短。
3. 尽量短，只说重点。
4. 语气要有感情，温柔、鼓励、亲近。
5. 使用短句、具体、正向、可预测的表达。
6. 鼓励语要短，例如“真棒”“很好”。
7. 不使用责备、否定、威胁、讽刺、复杂抽象表达。
8. 不说“你错了”，改说“我们再试一次”。
9. 课程引导时少用强转折；良性跑题拉回可用「我们先……吧」。
10. 不使用“你必须”“你应该”等命令式语气。
11. 如出现自伤、伤人、走失、严重痛苦等风险，提示马上找家长或老师，不要顺着危险话题聊。
12. 不使用“目标图”“选项”“页面上下文”“训练目标”“三角体”“立方体”“几何体”等专业词。
13. 面向孩子说话，要说“上面的图片”“下面的图片”“左边这张”“右边这张”。
14. 不说“观察目标图”，改说“看看上面的图片”。
15. 不说“选择正确选项”，改说“点这一张”。
16. 说形状时用孩子能懂的话：尖尖的、方方的、圆圆的、三角形的。
17. 不说“和积木做朋友”“真有趣”“有模有样”“你看见了吗”。
18. 不反问孩子，不说“你找找哪一张呀”。
19. 孩子不会认字：说名字、提示选哪张时，不要只报光秃秃的名字或只说方位。
20. 命名/问「是什么」：用短说法，一带合适特征+名字。优先「这是红红的草莓。」「这是凶猛的狮子。」，不要只说「这是草莓。」「这是狮子。」。
21. 特征要会判断，不要见物就套颜色：水果、物品、颜色鲜明的小虫可用叠字颜色，如「红红的草莓」「红红的瓢虫」，也要具体参考图片；狮子、老虎、羊等大型/常见哺乳动物颜色说法别扭，改用性情、体型或可爱感，如「凶猛的狮子」「凶猛的老虎」「可爱的小羊」。禁止「黄黄的狮子」「黄黄的老虎」「黄黄的小狗」这类生硬颜色。
22. 配对/排序提示选哪张：方位后加一句短线索（合适的颜色/形状/大小/性情），如「点左边红红的。」「选大的圆圆的。」「点凶猛的。」；已知页面特征时不要只说「选左边那张」。
23. 线索只要一小截：一个合适形容词/特征+名字即可；不讲叶子、纹路、笑脸等细节，不说成长句或老师讲解。
24. 上下文若有物品说明，把它收成孩子能听懂的短词再用；没有说明时按上述规则自选合适特征。动物可用「小猫咪」「小狗」「小兔子」等亲近叫法，但前面的形容词仍要合理。

位置规则（配对课必须遵守）：
1. 「上面的图片」只指屏幕上方那一张，不等于下面任何一张。
2. 「下面第一张 / 下面第1张 / 左边这张」指下面从左到右第1张。
3. 「下面第二张 / 右边这张」指下面从左到右第2张；第三张及以后同理。
4. 孩子问下面第N张是什么时，必须只根据【当前页】选项列表第N张作答；禁止用上面的图片回答；禁止沿用更早对话里旧题目的名称。
5. 当上下文提供了选项顺序时，你必须按从左到右的顺序描述。
6. 当上下文提供了“应该点”时，你必须使用它，不要猜。
7. 若系统提示「题目已切换」，必须忘掉上一题的选项与名称。

课程约束：
1. 当前页面上下文比普通聊天历史更重要；空间/第几张问题只看当前页选项。
2. 回答必须服务于当前课程训练。
3. 儿童问页面相关问题时，必须先直接回答问题。
4. 需要鼓励时，只说“真棒”或“很好”。
5. 不要只说“你在认真尝试”。
6. 儿童问“你是谁”时，可以介绍“我是麦麦”，随后邀请儿童回到当前题目。
7. 儿童良性跑题时：先短短顺着一句，再拉回当前题目或下面的图片；不要百科展开。
8. 优先引导儿童看上面的图片、看下面的图片、尝试点击或继续表达。
9. 拟声课的目标是让儿童开口模仿声音：示范一个短拟声，再邀请儿童跟着说；禁止要求儿童点击、指认或选择图片。
10. 模仿课的目标是让儿童观察屏幕上的动作图片并照着做：只说“看图片”“学着做”“照着做”或具体动作提示；不要声称机器人会示范全部动作，禁止要求儿童读、说、念或模仿声音。"""

ADULT_HELP_REPLY = "这个问题要找老师或家长。我们先停一下。"
WAKE_ACK_REPLY = "我在这里"
# 浏览器 ASR 常把「麦麦」听成「妹妹/卖卖/慢慢」等；用近音字白名单匹配。
# 单个 XX 即可唤醒；旧版 XX，XX / XXXX 仍兼容。只识别句首，可带后续内容。
_WAKE_MAI_CHARS = (
    "麦妹卖脉迈买唛玫枚莓媒埋霾"
    "慢慢满漫曼蛮瞒谩"
    "吗嘛妈麻马码玛骂"
)
# 两字短唤醒有更高误触风险，不纳入常见称呼「妈妈」所属的 ma 音节；
# mai/mei/man 已覆盖「麦麦、买卖、卖卖、妹妹、慢慢」等浏览器 ASR 变体。
_WAKE_SHORT_CHARS = (
    "麦妹卖脉迈买唛玫枚莓媒埋霾"
    "慢满漫曼蛮瞒谩"
)
_WAKE_SEP = r"[\s，,。.!！?？、·~～…\-—_]*"
_WAKE_PAIR = rf"[{_WAKE_MAI_CHARS}]{_WAKE_SEP}[{_WAKE_MAI_CHARS}]"
_WAKE_PREFIX_RE = re.compile(
    rf"^[\s]*{_WAKE_PAIR}{_WAKE_SEP}{_WAKE_PAIR}{_WAKE_SEP}(.*)$",
    re.DOTALL,
)
# 紧凑四连（无第二组分隔时仍可由 PREFIX 覆盖；保留兼容显式四字）
_WAKE_COMPACT_RE = re.compile(
    rf"^[\s，,。.!！?？、·~～…\-—_]*"
    rf"[{_WAKE_MAI_CHARS}]{{4}}"
    rf"[\s，,。.!！?？、·~～…\-—_]*(.*)$",
    re.DOTALL,
)
_WAKE_SHORT_RE = re.compile(
    rf"^[\s，,。.!！?？、·~～…\-—_]*"
    rf"[{_WAKE_SHORT_CHARS}]{_WAKE_SEP}[{_WAKE_SHORT_CHARS}]"
    rf"{_WAKE_SEP}(.*)$",
    re.DOTALL,
)
# 音节级兜底：去掉标点后若句首四音节均为 mai/mei/man/ma（含已知同音映射），也算唤醒
_WAKE_SYLLABLE_MAP = {
    "麦": "mai",
    "妹": "mei",
    "卖": "mai",
    "脉": "mai",
    "迈": "mai",
    "买": "mai",
    "唛": "mai",
    "埋": "mai",
    "霾": "mai",
    "玫": "mei",
    "枚": "mei",
    "莓": "mei",
    "媒": "mei",
    "慢": "man",
    "满": "man",
    "漫": "man",
    "曼": "man",
    "蛮": "man",
    "瞒": "man",
    "谩": "man",
    "吗": "ma",
    "嘛": "ma",
    "妈": "ma",
    "麻": "ma",
    "马": "ma",
    "码": "ma",
    "玛": "ma",
    "骂": "ma",
}
_WAKE_SOFT_SYLLABLES = frozenset({"mai", "mei", "man", "ma"})
CONTEXT_SWITCH_NOTE = (
    "题目已切换，以下为当前页。"
    "请忽略更早对话里关于旧选项、旧名称的说法。"
    "问「下面第N张/下面第一张」只能根据当前选项列表作答，不能沿用上一题。"
)

_CN_ORDINAL = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
}


def _load_asd_env_file() -> None:
    """把 ASD_AGENT_ENV_FILE（默认 ExpertAnnotator .env）合并进进程环境。"""
    raw = (os.environ.get("ASD_AGENT_ENV_FILE") or "").strip()
    candidates = []
    if raw:
        candidates.append(Path(raw))
        if not Path(raw).is_absolute():
            candidates.append(BASE_DIR / raw)
            candidates.append(BASE_DIR.parent / raw)
    candidates.append(
        BASE_DIR.parent / "ExpertAnnotator_ASD-main" / "asd_llm_agent" / ".env"
    )
    for path in candidates:
        try:
            if path.is_file():
                from dotenv import load_dotenv

                load_dotenv(path, override=False)
                logger.info("已加载 ASD 对话环境: %s", path)
                return
        except Exception as exc:  # noqa: BLE001
            logger.warning("加载 ASD 环境失败 %s: %s", path, exc)


def _extract_below_position(child_text: str) -> Optional[int]:
    """解析「下面第一张 / 下面第1张 / 左边这张 / 右边这张」→ 1-based 下标。"""
    text = (child_text or "").strip()
    if not text:
        return None
    # 明确问上面 → 不算下面
    if re.search(r"上面", text) and not re.search(r"下面", text):
        return None
    m = re.search(r"下面第\s*([一二两三四五六\d])\s*张", text)
    if m:
        token = m.group(1)
        if token.isdigit():
            return int(token)
        return _CN_ORDINAL.get(token)
    if re.search(r"下面.*(第一|第1)|第一张|最左边|左边这张|左边那张", text):
        if re.search(r"上面", text):
            return None
        return 1
    if re.search(r"下面.*(第二|第2)|右边这张|右边那张|最右边", text):
        return 2
    if re.search(r"下面.*(第三|第3)", text):
        return 3
    return None


def _asks_about_above(child_text: str) -> bool:
    text = (child_text or "").strip()
    return bool(re.search(r"上面", text)) and not bool(re.search(r"下面", text))


def _is_dangerous_topic(child_text: str) -> bool:
    text = (child_text or "").strip().lower()
    if not text:
        return False
    return bool(
        re.search(
            r"自伤|自杀|不想活|伤害自己|打人|杀人|刀|打死|走丢|走失|"
            r"家暴|受伤很痛|血很多|self[- ]?harm|suicide|kill myself",
            text,
            re.I,
        )
    )


def _is_benign_offtopic(child_text: str) -> bool:
    """天气/出去玩等与当前题目无关的闲聊（不含危险话题）。"""
    text = (child_text or "").strip()
    if not text or _is_dangerous_topic(text):
        return False
    # 页面相关问句不算跑题
    if re.search(r"上面|下面|第.+张|左边|右边|是什么|怎么玩|怎么选|点哪", text):
        return False
    return bool(
        re.search(
            r"天气|下雨|下雪|太阳|出去玩|想玩|玩游戏|吃饭|喝水|睡觉|"
            r"爸爸|妈妈|幼儿园|动画片|唱歌|跳舞|好玩吗",
            text,
        )
    )


def _benign_offtopic_rule_reply(child_text: str) -> str:
    text = (child_text or "").strip()
    if re.search(r"天气|下雨|下雪|太阳", text):
        return "是呀天气真好。我们先看屏幕吧。"
    if re.search(r"出去玩|想玩|玩游戏", text):
        return "想玩呀。我们先做完这个游戏吧。"
    if re.search(r"吃饭|喝水|睡觉", text):
        return "好的。我们先看图片吧。"
    return "你说得真好。我们先看屏幕吧。"


_ONOMATOPOEIA_VISUAL_ACTION_RE = re.compile(
    r"点击|点一|点这|选择|选一|指认|指出|哪一张|哪张|图片"
)
_ONOMATOPOEIA_VOICE_ACTION_RE = re.compile(
    r"跟着|跟麦麦|说一|说说|学一|模仿|发声|声音|叫声|怎么叫|再来|试着说"
)


def _align_onomatopoeia_reply(
    reply: str,
    page_context: Optional[Dict[str, Any]],
) -> str:
    """拟声课硬约束：回复必须回到开口模仿，不能落成看图点击任务。"""
    context = page_context or {}
    course_type = str(
        context.get("courseType") or context.get("course_type") or ""
    ).strip().lower()
    if course_type != "onomatopoeia":
        return reply

    from .image_semantics import humanize_label

    raw_sound = (
        context.get("speechTarget")
        or context.get("speech_target")
        or context.get("target")
        or ""
    )
    sound = humanize_label(raw_sound, fallback="")[:8]
    if sound:
        practice = f"{sound}，跟麦麦说一次。"
    else:
        object_name = humanize_label(
            context.get("objectName") or context.get("object_name") or "",
            fallback="",
        )[:8]
        practice = (
            f"学一学{object_name}的声音。"
            if object_name
            else "跟麦麦学一学声音。"
        )

    text = str(reply or "").strip()
    if not text or _ONOMATOPOEIA_VISUAL_ACTION_RE.search(text):
        return practice
    if _ONOMATOPOEIA_VOICE_ACTION_RE.search(text):
        return text
    first_sentence = re.split(r"[。！？!?]", text, maxsplit=1)[0].strip()[:12]
    return f"{first_sentence}。{practice}" if first_sentence else practice


_MIMIC_NON_ACTION_RE = re.compile(
    r"读|朗读|说一|说说|念|复述|发声|声音|叫声|怎么叫|点击|点一|选择|哪一张|哪张"
)
_MIMIC_ROBOT_FOLLOW_RE = re.compile(
    r"看着?麦麦|跟着?麦麦|麦麦做|机器人做|跟着?机器人"
)
_MIMIC_ACTION_RE = re.compile(
    r"动作|图片|图上|屏幕|学着做|照着做|手臂|身体|抬手|举手|伸手|摆手"
)


def _align_mimic_reply(
    reply: str,
    page_context: Optional[Dict[str, Any]],
) -> str:
    """动作模仿课硬约束：引导身体动作，绝不退化成跟读/拟声。"""
    context = page_context or {}
    course_type = str(
        context.get("courseType") or context.get("course_type") or ""
    ).strip().lower()
    if course_type not in ("mimic", "imitation", "pose"):
        return reply

    practice = pick_phrase("question", "mimic")
    text = str(reply or "").strip()
    if not text or _MIMIC_NON_ACTION_RE.search(text) or _MIMIC_ROBOT_FOLLOW_RE.search(text):
        return practice
    if _MIMIC_ACTION_RE.search(text):
        return text
    first_sentence = re.split(r"[。！？!?]", text, maxsplit=1)[0].strip()[:12]
    return f"{first_sentence}。{practice}" if first_sentence else practice


def _align_course_reply(
    reply: str,
    page_context: Optional[Dict[str, Any]],
) -> str:
    """Apply the mutually-exclusive semantic guard for the active course."""
    aligned = _align_onomatopoeia_reply(reply, page_context)
    return _align_mimic_reply(aligned, page_context)


def _short_kid_visual(label: str, description: str = "") -> str:
    """把语义说明收成短视觉/特征说法；无说明则查物品短线索，再退回名称。"""
    name = str(label or "").strip()
    desc = str(description or "").strip()
    if not desc:
        try:
            from .image_semantics import item_cue_from_label

            cue = item_cue_from_label(name)
            if cue:
                return cue
        except Exception:  # noqa: BLE001
            pass
        return name
    # 只要第一截：去掉叶子/纹路等长尾细节
    short = re.split(r"[，,。；;]", desc, maxsplit=1)[0].strip()
    if not short:
        return name
    # 过长则仍用名称，避免规则答变成长句
    if len(short) > 12:
        return name or short[:12]
    return short


def _page_context_fingerprint(page_context: Optional[Dict[str, Any]]) -> str:
    """稳定的课型/条目/题目指纹。

    目标文字、选项和提示会在同一题展示后继续补齐，不能参与身份判断；
    否则教师刚唤醒后，一次正常的题面补报就会被误判为换题并清除唤醒。
    """
    if not page_context:
        return ""
    course_type = (
        page_context.get("courseType")
        or page_context.get("course_type")
        or ""
    )
    course_id = page_context.get("courseId") or page_context.get("course_id") or ""
    qid = (
        page_context.get("questionId")
        or page_context.get("question_id")
        or ""
    )
    item_id = page_context.get("itemId") or page_context.get("item_id") or ""
    q_index = page_context.get("questionIndex")
    if q_index is None:
        q_index = page_context.get("question_index")
    return "|".join(
        [
            str(course_type).strip().lower(),
            str(course_id).strip(),
            str(qid).strip(),
            str(item_id).strip(),
            str(q_index if q_index is not None else ""),
        ]
    )


# 教师端只能看到即将播放的课点，交互页最终提交的 questionId 可能要到儿童端
# iframe 生成首题后才确定。手动唤醒先记为待绑定，由当前儿童端的已提交上下文完成绑定。
_PENDING_MANUAL_WAKE_CONTEXT = "__pending_manual_wake_context__"


def _wake_syllables(text: str) -> list[str]:
    """将文本映射为 mai/mei/man/ma 音节序列（非近音字中断）。"""
    out: list[str] = []
    for ch in text or "":
        if ch.isspace() or ch in "，,。.!！?？、·~～…-—_":
            continue
        syl = _WAKE_SYLLABLE_MAP.get(ch)
        if syl is None:
            break
        out.append(syl)
    return out


def parse_wake_utterance(text: str) -> tuple[bool, str]:
    """识别唤醒词「麦麦」及 ASR 近音变体。

    规则（句首）：
    1. 一个 mai/mei/man 近音字对：XX，如「麦麦」「买卖」「妹妹」「慢慢」
    2. 兼容两个近音字对：XX[分隔]XX，如「麦麦，麦麦」「妹妹，卖卖」
    3. 兼容四个近音字连写及 mai/mei/man/ma 四音节旧变体

    Returns:
        (matched, remainder)：matched 为 True 表示句首是唤醒；
        remainder 为空表示纯唤醒，非空则是唤醒后的对话内容。
    """
    raw = (text or "").strip()
    if not raw:
        return False, ""
    m = _WAKE_PREFIX_RE.match(raw)
    if m:
        return True, (m.group(1) or "").strip()
    m2 = _WAKE_COMPACT_RE.match(raw)
    if m2:
        return True, (m2.group(1) or "").strip()
    m3 = _WAKE_SHORT_RE.match(raw)
    if m3:
        return True, (m3.group(1) or "").strip()
    # 音节兜底：至少四个 mai/mei/man/ma，remainder 从第 5 个有效汉字起
    syllables = _wake_syllables(raw)
    if len(syllables) >= 4 and all(s in _WAKE_SOFT_SYLLABLES for s in syllables[:4]):
        seen = 0
        rem_start = len(raw)
        for i, ch in enumerate(raw):
            if ch.isspace() or ch in "，,。.!！?？、·~～…-—_":
                continue
            if ch not in _WAKE_SYLLABLE_MAP:
                rem_start = i
                break
            seen += 1
            if seen >= 4:
                rem_start = i + 1
                # 吞掉紧随唤醒后的标点/空白
                while rem_start < len(raw) and (
                    raw[rem_start].isspace()
                    or raw[rem_start] in "，,。.!！?？、·~～…-—_"
                ):
                    rem_start += 1
                break
        return True, raw[rem_start:].strip()
    return False, raw


def is_wake_phrase(text: str) -> bool:
    """是否为纯唤醒（无后续对话内容）。"""
    matched, remainder = parse_wake_utterance(text)
    return matched and not remainder


class DialogueService:
    def __init__(self) -> None:
        _load_asd_env_file()
        self.provider = (os.environ.get("AI_CHAT_PROVIDER") or "asd").strip().lower()
        self.api_key = (
            os.environ.get("ASD_LLM_API_KEY")
            or os.environ.get("LLM_API_KEY")
            or ""
        ).strip()
        self.base_url = (
            os.environ.get("ASD_LLM_BASE_URL")
            or os.environ.get("LLM_BASE_URL")
            or "https://api.deepseek.com"
        ).rstrip("/")
        self.model = (
            os.environ.get("DIALOGUE_LLM_MODEL")
            or os.environ.get("ASD_LLM_MODEL")
            or os.environ.get("LLM_MODEL")
            or "deepseek-chat"
        )
        # 推理型 flash 模型常把回复放进 reasoning_content；儿童对话优先非推理短回复
        if "flash" in self.model.lower() and not os.environ.get("DIALOGUE_LLM_MODEL"):
            logger.info("对话模型 %s 易空 content，改用 deepseek-chat", self.model)
            self.model = "deepseek-chat"
        try:
            self.timeout_s = float(os.environ.get("ASD_LLM_TIMEOUT_SECONDS") or 90)
        except ValueError:
            self.timeout_s = 90.0
        self._history: Dict[str, List[Dict[str, str]]] = {}
        # session_id → 上次用于对话的稳定题目指纹
        self._context_fp: Dict[str, str] = {}
        # session_id → 唤醒时绑定的题目指纹；题目变化后需重新唤醒
        self._awake_fp: Dict[str, str] = {}

    def _ensure_awake_store(self) -> None:
        if not hasattr(self, "_awake_fp") or self._awake_fp is None:
            self._awake_fp = {}

    def is_session_awake(
        self,
        session_id: str,
        page_context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """当前 session 是否已在本题目指纹下唤醒。"""
        self._ensure_awake_store()
        awake_fp = self._awake_fp.get(session_id)
        if awake_fp is None:
            return False
        if awake_fp == _PENDING_MANUAL_WAKE_CONTEXT:
            return True
        fp = _page_context_fingerprint(page_context)
        if awake_fp != fp:
            self.clear_awake(session_id)
            return False
        return True

    def set_awake(
        self,
        session_id: str,
        page_context: Optional[Dict[str, Any]] = None,
        *,
        defer_context_binding: bool = False,
    ) -> None:
        self._ensure_awake_store()
        self._awake_fp[session_id] = (
            _PENDING_MANUAL_WAKE_CONTEXT
            if defer_context_binding
            else _page_context_fingerprint(page_context)
        )

    def bind_pending_awake_context(
        self,
        session_id: str,
        page_context: Optional[Dict[str, Any]],
    ) -> bool:
        """用儿童端已提交的题目上下文完成一次手动唤醒绑定。"""
        self._ensure_awake_store()
        if self._awake_fp.get(session_id) != _PENDING_MANUAL_WAKE_CONTEXT:
            return False
        fingerprint = _page_context_fingerprint(page_context)
        if not fingerprint:
            return False
        self._awake_fp[session_id] = fingerprint
        return True

    def clear_awake(self, session_id: str) -> None:
        self._ensure_awake_store()
        self._awake_fp.pop(session_id, None)

    def _option_entries(self, page_context: Dict[str, Any]) -> List[Dict[str, str]]:
        """选项名 + 短视觉说明（供上下文与规则答使用）。"""
        from .image_semantics import humanize_label, is_filename_like

        options = page_context.get("options") or page_context.get("optionsLeftToRight")
        entries: List[Dict[str, str]] = []
        if isinstance(options, list):
            for idx, opt in enumerate(options):
                fallback = "左边" if idx == 0 else f"第{idx + 1}张"
                if isinstance(opt, dict):
                    label = (
                        opt.get("label")
                        or opt.get("name")
                        or opt.get("text")
                        or ""
                    )
                    if is_filename_like(str(label)):
                        label = humanize_label(opt.get("name") or "", fallback=fallback)
                    else:
                        label = humanize_label(label, fallback=fallback)
                    label = str(label or fallback)
                    visual = _short_kid_visual(
                        label, str(opt.get("description") or "")
                    )
                    entries.append({"label": label, "visual": visual or label})
                else:
                    label = humanize_label(opt, fallback=fallback)
                    entries.append({"label": label, "visual": label})
        elif isinstance(options, str) and options.strip():
            label = humanize_label(options.strip(), fallback="左边")
            entries.append({"label": label, "visual": label})
        return entries

    def _option_labels(self, page_context: Dict[str, Any]) -> List[str]:
        return [e["label"] for e in self._option_entries(page_context)]

    def build_page_context_text(self, page_context: Optional[Dict[str, Any]]) -> str:
        """对齐 DemoRobot buildPageContextForPrompt / buildPageContextNarrative。"""
        if not page_context:
            return ""
        from .image_semantics import humanize_label, is_filename_like

        course_type = (
            page_context.get("courseType")
            or page_context.get("course_type")
            or ""
        )
        course_type_l = str(course_type).strip().lower()
        is_ordering = course_type_l in ("ordering", "sequencing")
        is_pairing = course_type_l in ("pairing", "matching")
        is_speech = course_type_l in ("naming", "speech", "onomatopoeia")
        is_mimic = course_type_l in ("mimic", "imitation", "pose")
        is_single_target = is_speech or is_mimic

        prompt = page_context.get("prompt") or ""
        raw_target = (
            page_context.get("target")
            or page_context.get("targetText")
            or page_context.get("speechTarget")
            or page_context.get("itemLabel")
            or page_context.get("label")
            or page_context.get("name")
            or ""
        )
        rule_id = str(page_context.get("rule") or "").strip()
        rule_text = str(page_context.get("ruleText") or "").strip()
        category = str(page_context.get("category") or "").strip()
        object_name = humanize_label(
            page_context.get("objectName") or page_context.get("object_name") or "",
            fallback="",
        )

        play_hint = "找一样的图片" if is_pairing else (
            "按规则找图片" if is_ordering else ""
        )
        lines = [f"课型：{course_type}"]
        if play_hint:
            lines.append(f"玩法：{play_hint}")
        q_index = page_context.get("questionIndex")
        q_total = page_context.get("totalQuestions")
        if q_index is not None:
            if q_total:
                lines.append(f"现在是第 {q_index}/{q_total} 题")
            else:
                lines.append(f"现在是第 {q_index} 题")
        variant = None
        if is_ordering:
            from .phrases import ordering_phrase_key

            variant = ordering_phrase_key(category, rule_id)
        if prompt:
            heard = prompt
        elif course_type_l == "onomatopoeia":
            from .phrases import format_onomatopoeia_question, resolve_item_display_name

            heard = format_onomatopoeia_question(
                resolve_item_display_name(page_context, raw_target)
            )
        else:
            heard = pick_phrase("question", str(course_type), variant=variant)
        lines.append(f"孩子听到的问题：{heard}")
        if course_type_l == "onomatopoeia":
            lines.append("课程目标：让儿童开口模仿声音，不需要点击、指认或选择图片。")
            if object_name:
                lines.append(f"练习对象：{object_name}")
            if raw_target:
                lines.append(f"练习声音：{raw_target}")
            lines.append(
                "回复要求：示范一个短拟声并邀请儿童跟着说；禁止说“点一张图”或要求儿童选择图片。"
            )
        elif is_mimic:
            lines.append("课程目标：让儿童观察屏幕上的动作图片并学着做身体动作，不是跟读或模仿声音。")
            lines.append(
                "回复要求：使用“看图片”“学着做”“照着做”或具体动作提示；不要声称机器人会示范全部动作，禁止要求儿童读、说、念或发声。"
            )
        if category or rule_id or rule_text:
            lines.append(
                f"当前规则：{rule_text or f'{category} {rule_id}'.strip()}".strip()
            )
        if object_name:
            lines.append(f"本题物品：{object_name}")

        # 排序：不要把 ruleText（选大的）当成「上面的图片」
        target = ""
        if is_ordering:
            target = ""
        else:
            target = humanize_label(raw_target, fallback="")
            if not target or is_filename_like(str(raw_target or "")):
                target = ""
            if target and rule_text and target == rule_text:
                target = ""
            # 禁止把「左边」这类选项方位词当成上面目标名
            if target in ("左边", "右边", "第1张", "第一张"):
                target = ""
        if target:
            target_vis = _short_kid_visual(
                target,
                str(page_context.get("targetDescription") or ""),
            )
            if is_mimic:
                lines.append(f"当前图片动作：{target}")
            elif is_speech:
                if target_vis and target_vis != target:
                    lines.append(f"当前物品：{target}（{target_vis}）")
                else:
                    lines.append(f"当前物品：{target}")
            else:
                if target_vis and target_vis != target:
                    lines.append(f"上面的图片：{target}（{target_vis}）")
                else:
                    lines.append(f"上面的图片：{target}")

        option_entries = self._option_entries(page_context)
        option_labels = [e["label"] for e in option_entries]
        if option_entries and not is_single_target:
            # DemoRobot：下面第N张：label（从左到右）；附短视觉供孩子听懂
            parts = []
            for i, ent in enumerate(option_entries):
                lab, vis = ent["label"], ent["visual"]
                if vis and vis != lab:
                    parts.append(f"下面第{i + 1}张：{lab}（{vis}）")
                else:
                    parts.append(f"下面第{i + 1}张：{lab}")
            lines.append(f"下面从左到右的图片：{'；'.join(parts)}")
            lines.append(
                "位置说明：下面第1张=左边这张；问「下面第一张」只答下面第1张，"
                "不要答上面的图片。"
            )

        correct_pos = page_context.get("correctPosition") or page_context.get(
            "correctOptionPosition"
        )
        correct_label = page_context.get("correctLabel") or page_context.get(
            "correctOptionLabel"
        )
        correct_desc = str(
            page_context.get("correctDescription")
            or page_context.get("correctOptionDescription")
            or ""
        )
        lab_txt = ""
        vis_txt = ""
        if correct_pos or correct_label:
            pos_txt = f"第{correct_pos}张" if correct_pos else ""
            lab_txt = humanize_label(correct_label, fallback="") if correct_label else ""
            if lab_txt and is_filename_like(str(correct_label or "")):
                lab_txt = ""
            # 若选项列表里有对应短视觉，优先用
            if correct_pos:
                try:
                    idx = int(correct_pos) - 1
                    if 0 <= idx < len(option_entries):
                        vis_txt = option_entries[idx]["visual"]
                        if not lab_txt:
                            lab_txt = option_entries[idx]["label"]
                except (TypeError, ValueError):
                    pass
            if not vis_txt and lab_txt:
                vis_txt = _short_kid_visual(lab_txt, correct_desc)
            hint = lab_txt
            if vis_txt and vis_txt != lab_txt:
                hint = f"{lab_txt}，{vis_txt}" if lab_txt else vis_txt
            lines.append(
                f"应该点：下面{pos_txt}{'，' if pos_txt and hint else ''}{hint}".rstrip("，")
            )

        wrong = page_context.get("wrongAttempts")
        if wrong is not None:
            lines.append(f"本题已错次数：{wrong}")

        # DemoRobot narrative：给模型一句连贯总览
        if is_pairing and (target or option_entries):
            opt_narr = (
                "；".join(
                    (
                        f"下面第{i + 1}张：{e['label']}（{e['visual']}）"
                        if e["visual"] != e["label"]
                        else f"下面第{i + 1}张：{e['label']}"
                    )
                    for i, e in enumerate(option_entries)
                )
                or "下面没有图片"
            )
            answer_narr = ""
            if correct_pos:
                lab = (vis_txt or lab_txt) if (correct_pos or correct_label) else ""
                answer_narr = f"应该点下面第{correct_pos}张{('：' + lab) if lab else ''}。"
            lines.append(
                f"叙事：现在玩找一样的图片。"
                f"上面的图片：{target or '上面那张'}。"
                f"下面的图片：{opt_narr}。{answer_narr}"
            )
        return "\n".join(lines)

    def _position_rule_reply(
        self,
        child_text: str,
        page_context: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """配对：问下面第N张 / 上面的图片是什么 → 确定性短答，避免 LLM 串位。"""
        if not page_context:
            return None
        course_type = str(
            page_context.get("courseType") or page_context.get("course_type") or ""
        ).strip().lower()
        if course_type not in ("pairing", "matching"):
            return None
        if not re.search(r"什么|啥|叫|哪个", child_text or ""):
            # 仍允许纯位置问法「下面第一张呢」
            if not re.search(r"下面|上面|左边|右边|第.+张", child_text or ""):
                return None

        from .image_semantics import humanize_label, is_filename_like

        def _pack(reply: str) -> Dict[str, Any]:
            return {
                "reply": reply,
                "strategy": "rule_position",
                "provider": "rule",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        if _asks_about_above(child_text or ""):
            raw_target = (
                page_context.get("target")
                or page_context.get("targetText")
                or ""
            )
            label = humanize_label(raw_target, fallback="")
            if label and not is_filename_like(str(raw_target)) and label not in (
                "左边",
                "右边",
            ):
                visual = _short_kid_visual(
                    label,
                    str(
                        page_context.get("targetDescription")
                        or page_context.get("description")
                        or ""
                    ),
                )
                return _pack(f"这是{visual or label}。")
            return None

        pos = _extract_below_position(child_text or "")
        if not pos:
            return None
        entries = self._option_entries(page_context)
        if pos < 1 or pos > len(entries):
            return None
        ent = entries[pos - 1]
        name = ent["visual"] or ent["label"]
        # 去掉「左边/右边」前缀噪音，保留物品名若已是纯名
        clean = re.sub(r"^(左边|右边)", "", name).strip() or name
        return _pack(f"这是{clean}。")

    def _sync_history_for_context(
        self,
        session_id: str,
        page_context: Optional[Dict[str, Any]],
    ) -> bool:
        """题目/选项变化时清空历史。返回 True 表示本轮发生了切换。"""
        if not hasattr(self, "_history") or self._history is None:
            self._history = {}
        if not hasattr(self, "_context_fp") or self._context_fp is None:
            self._context_fp = {}
        fp = _page_context_fingerprint(page_context)
        prev = self._context_fp.get(session_id)
        # 含空指纹：离开互动课到命名时若短暂无上下文，也要丢掉旧历史
        switched = prev is not None and prev != fp
        if switched:
            self._history[session_id] = []
            self.clear_awake(session_id)
            logger.info(
                "题目上下文切换，已清空对话历史并退出唤醒 sid=%s prev_fp=%s new_fp=%s",
                session_id,
                (prev or "")[:80],
                (fp or "")[:80],
            )
        self._context_fp[session_id] = fp
        return switched

    def _rule_reply(self, child_text: str, course_type: Optional[str]) -> Dict[str, Any]:
        text = (child_text or "").strip()
        if _is_dangerous_topic(text):
            reply = ADULT_HELP_REPLY
            strategy = "safety_adult"
        elif _is_benign_offtopic(text):
            reply = _benign_offtopic_rule_reply(text)
            strategy = "offtopic_redirect"
        elif any(k in text for k in ("不会", "不懂", "难", "怕", "帮")):
            reply = pick_phrase("encourage", course_type)
            strategy = "encourage"
        elif any(k in text for k in ("我会了", "完成", "太简单", "好玩")):
            reply = pick_phrase("praise", course_type)
            strategy = "praise"
        elif not text:
            reply = "我陪你。先看屏幕吧。"
            strategy = "fallback"
        else:
            reply = "你很认真。我们继续吧。"
            strategy = "encourage"
        return {
            "reply": reply,
            "strategy": strategy,
            "provider": "rule",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def _asd_reply(
        self,
        child_text: str,
        *,
        session_id: str,
        page_context_text: str,
        page_context: Optional[Dict[str, Any]] = None,
        context_switched: bool = False,
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("ASD_LLM_API_KEY/LLM_API_KEY is not configured")

        history = self._history.setdefault(session_id, [])
        messages: List[Dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        if page_context_text:
            # 对齐 DemoRobot asdAgentProvider contextMessage；强化当前页优先
            ctx_preamble = (
                "当前课程页面上下文如下，只给你理解页面用。回复孩子时不能照抄字段名。"
                "儿童问颜色、图形、位置、第几张、怎么玩时，先直接回答。"
                "每次最多2句，每句尽量不超过12字。"
                "问「是什么」用短说法：合适特征+名字。水果/物品/小虫可用颜色如「这是红红的草莓。」「这是绿绿的青蛙。」；"
                "狮子老虎等勿说「黄黄的」，改用「这是凶猛的狮子。」「这是可爱的小羊。」；不要只报光秃秃名字。"
                "提示选哪张时：方位加合适的颜色/形状/大小/性情短线索，如「点左边红红的。」「点凶猛的。」；不要只说「选左边那张」。"
                "上下文括号里的说明请收成孩子能懂的短词，不要复述长细节。"
                "问「下面第N张/下面第一张」必须只根据【当前】下面从左到右第N张作答，"
                "禁止答上面的图片，禁止沿用历史里旧题目的选项名称。"
                "当前页面上下文优先于聊天历史。"
                "若当前是拟声课，只引导儿童开口模仿声音，可先示范短拟声；绝不要求点击、指认或选择图片。"
                "若当前是模仿课，只引导儿童看当前动作图片并照着做；不要让儿童跟机器人做，也不要声称机器人能完成图片中的全部动作。"
                "不要反问孩子。"
                "不要说“目标图”“选项”“训练目标”“页面上下文”“三角体”“立方体”“几何体”"
                "“做朋友”“真有趣”：\n"
                f"{page_context_text}"
            )
            messages.append({"role": "system", "content": ctx_preamble})
            if context_switched:
                messages.append({"role": "system", "content": CONTEXT_SWITCH_NOTE})
        else:
            messages.append(
                {
                    "role": "system",
                    "content": "当前没有可靠课程上下文。只说一句短话，请孩子看屏幕。每句不超过12字。",
                }
            )
        # 题目切换后历史已空；同题内只保留短窗口，降低旧轮次权重
        hist_window = 2 if context_switched else 6
        messages.extend(history[-hist_window:])
        messages.append({"role": "user", "content": child_text})

        url = f"{self.base_url}/chat/completions"
        resp = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.32,
                "max_tokens": 90,
            },
            timeout=self.timeout_s,
        )
        if not resp.ok:
            raise RuntimeError(f"ASD LLM failed: {resp.status_code} {resp.text[:300]}")
        payload = resp.json()
        message = (((payload.get("choices") or [{}])[0]).get("message") or {})
        content = (message.get("content") or "").strip()
        if not content:
            content = (message.get("reasoning_content") or "").strip()
            if content and len(content) > 40:
                # 推理模型偶发把长思考塞进该字段；截成短句
                content = content.split("。")[0][:24]
        if not content:
            raise RuntimeError("ASD LLM returned empty reply")
        content = _align_course_reply(content, page_context)

        history.append({"role": "user", "content": child_text})
        history.append({"role": "assistant", "content": content})
        self._history[session_id] = history[-16:]
        return {
            "reply": content,
            "strategy": "asd_llm",
            "provider": "asd-agent-llm",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def generate_reply(
        self,
        child_text: str,
        *,
        session_id: str = "default",
        page_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        course_type = None
        if page_context:
            course_type = page_context.get("courseType") or page_context.get("course_type")
        page_text = self.build_page_context_text(page_context)
        context_switched = self._sync_history_for_context(session_id, page_context)

        # 危险话题：规则硬拦截（对齐 DemoRobot escalate_to_adult）
        if _is_dangerous_topic(child_text):
            return {
                "reply": ADULT_HELP_REPLY,
                "strategy": "safety_adult",
                "provider": "rule",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        # 位置问答优先走规则 + 当前 pageContext，避免 LLM/历史串题
        positioned = self._position_rule_reply(child_text, page_context)
        if positioned:
            return positioned

        # 无 key / rule 模式：良性跑题也走规则软拉回
        if self.provider == "rule" or not self.api_key:
            if self.provider == "asd" and not self.api_key:
                logger.warning("ASD key 未配置，对话降级为 rule")
            result = self._rule_reply(child_text, course_type)
            result["reply"] = _align_course_reply(result.get("reply", ""), page_context)
            return result

        try:
            return self._asd_reply(
                child_text,
                session_id=session_id,
                page_context_text=page_text,
                page_context=page_context,
                context_switched=context_switched,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("ASD 对话失败，降级 rule: %s", exc)
            result = self._rule_reply(child_text, course_type)
            result["reply"] = _align_course_reply(result.get("reply", ""), page_context)
            return result

    def clear_history(self, session_id: str) -> None:
        self._history.pop(session_id, None)
        self._context_fp.pop(session_id, None)
        self.clear_awake(session_id)


_service: Optional[DialogueService] = None


def init_dialogue_service() -> DialogueService:
    global _service
    _service = DialogueService()
    logger.info(
        "对话服务已初始化 provider=%s key_configured=%s",
        _service.provider,
        bool(_service.api_key),
    )
    return _service


def get_dialogue_service() -> DialogueService:
    global _service
    if _service is None:
        return init_dialogue_service()
    return _service
