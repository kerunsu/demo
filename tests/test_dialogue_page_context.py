"""对话页上下文与配对/排序错答鼓励。"""
import os

from app.dialogue.page_context_store import (
    clear_interactive_page_context,
    get_interactive_page_context,
    merge_page_context,
    set_interactive_page_context,
)
from app.dialogue.phrases import get_phrase_bank, pick_phrase
from app.dialogue.service import DialogueService, SYSTEM_PROMPT
from app.dialogue.image_semantics import matching_label_from_src, ordering_option_label


def test_system_prompt_requires_short_visual_cues():
    """孩子不会认字：命名/选图要带短视觉线索，不能只报名字或方位。"""
    assert "红红的草莓" in SYSTEM_PROMPT
    assert "不要只报光秃秃的名字" in SYSTEM_PROMPT
    assert "选左边那张" in SYSTEM_PROMPT
    assert "除非孩子问，不主动描述细节" not in SYSTEM_PROMPT


def test_build_page_context_text_includes_option_visuals():
    svc = DialogueService.__new__(DialogueService)
    text = svc.build_page_context_text(
        {
            "courseType": "pairing",
            "prompt": "选和上面一样的。",
            "target": "草莓",
            "targetDescription": "一颗红色草莓，上面有绿色叶子",
            "options": [
                {"id": "a", "label": "草莓", "description": "一颗红色草莓，上面有叶子"},
                {"id": "b", "label": "香蕉", "description": "一串黄色香蕉"},
            ],
            "correctPosition": 1,
            "correctLabel": "草莓",
        }
    )
    assert "上面的图片：草莓（一颗红色草莓）" in text
    assert "下面第1张：草莓（一颗红色草莓）" in text
    assert "下面第2张：香蕉（一串黄色香蕉）" in text


def test_position_rule_reply_uses_short_visual():
    svc = DialogueService.__new__(DialogueService)
    page = {
        "courseType": "pairing",
        "target": "草莓",
        "targetDescription": "一颗红色草莓，上面有叶子",
        "options": [
            {"id": "a", "label": "香蕉", "description": "一串黄色香蕉，弯弯的"},
            {"id": "b", "label": "草莓", "description": "一颗红色草莓"},
        ],
    }
    below = svc.generate_reply(
        "下面第一张是什么",
        session_id="t_vis",
        page_context=page,
    )
    assert below["strategy"] == "rule_position"
    assert "黄色香蕉" in below["reply"]
    assert "弯弯" not in below["reply"]

    above = svc.generate_reply(
        "上面的图片是什么",
        session_id="t_vis2",
        page_context=page,
    )
    assert above["strategy"] == "rule_position"
    assert "红色草莓" in above["reply"]
    assert "叶子" not in above["reply"]


def test_build_page_context_text_includes_options_and_rule():
    svc = DialogueService.__new__(DialogueService)
    text = svc.build_page_context_text(
        {
            "courseType": "pairing",
            "prompt": "选和上面一样的。",
            "target": "绿色棱柱",
            "options": [
                {"id": "a", "label": "椅子"},
                {"id": "b", "label": "绿色棱柱"},
                {"id": "c", "label": "篮球"},
            ],
            "wrongAttempts": 1,
            "questionIndex": 3,
            "totalQuestions": 15,
            "correctPosition": 2,
            "correctLabel": "绿色棱柱",
        }
    )
    assert "课型：pairing" in text
    assert "玩法：找一样的图片" in text
    assert "现在是第 3/15 题" in text
    assert "孩子听到的问题：选和上面一样的。" in text
    assert "上面的图片：绿色棱柱" in text
    assert "下面从左到右的图片：" in text
    assert "下面第1张：椅子" in text
    assert "下面第2张：绿色棱柱" in text
    assert "本题已错次数：1" in text
    assert "应该点：下面第2张，绿色棱柱" in text
    assert "正确答案名称" not in text
    assert "物品" not in text
    assert "问「下面第一张」只答下面第1张" in text


def test_position_rule_reply_below_first_not_target():
    """「下面第一张是什么」必须答选项1，不能答上面目标。"""
    svc = DialogueService.__new__(DialogueService)
    page = {
        "courseType": "pairing",
        "target": "绿色棱柱",
        "options": [
            {"id": "a", "label": "椅子"},
            {"id": "b", "label": "绿色棱柱"},
            {"id": "c", "label": "篮球"},
        ],
        "correctPosition": 2,
        "correctLabel": "绿色棱柱",
    }
    reply = svc.generate_reply(
        "下面第一张图片是什么呀",
        session_id="t_pos",
        page_context=page,
    )
    assert reply["strategy"] == "rule_position"
    assert "椅子" in reply["reply"]
    assert "棱柱" not in reply["reply"]

    above = svc.generate_reply(
        "上面的图片是什么呀",
        session_id="t_pos2",
        page_context=page,
    )
    assert above["strategy"] == "rule_position"
    assert "棱柱" in above["reply"]


def test_history_cleared_on_course_type_change_to_naming():
    """配对 → 命名：历史与指纹必须切换，回答应对准当前物品。"""
    from app.dialogue.service import _page_context_fingerprint

    svc = DialogueService.__new__(DialogueService)
    svc._history = {}
    svc._context_fp = {}
    svc.provider = "rule"
    svc.api_key = ""

    pairing = {
        "courseType": "pairing",
        "questionIndex": 1,
        "questionId": "q1",
        "target": "绿色棱柱",
        "options": [
            {"id": "a", "label": "椅子"},
            {"id": "b", "label": "绿色棱柱"},
        ],
    }
    naming = {
        "courseType": "naming",
        "itemId": 42,
        "questionId": "naming_42",
        "target": "猫",
        "speechTarget": "猫",
        "prompt": "这是什么呀",
    }
    svc._history["t_switch"] = [
        {"role": "user", "content": "下面第一张是什么"},
        {"role": "assistant", "content": "这是椅子。"},
    ]
    svc._context_fp["t_switch"] = _page_context_fingerprint(pairing)

    page_text = svc.build_page_context_text(naming)
    assert "课型：naming" in page_text
    assert "当前物品：猫" in page_text
    assert "下面从左到右" not in page_text
    assert "椅子" not in page_text

    reply = svc.generate_reply(
        "这是什么",
        session_id="t_switch",
        page_context=naming,
    )
    assert svc._history.get("t_switch") == [] or "椅子" not in str(svc._history.get("t_switch"))
    assert svc._context_fp["t_switch"] == _page_context_fingerprint(naming)
    assert "椅子" not in reply["reply"]
    assert "棱柱" not in reply["reply"]


def test_page_context_store_overwrite_on_naming_after_pairing():
    clear_interactive_page_context("s_name")
    set_interactive_page_context(
        "s_name",
        {
            "courseType": "pairing",
            "questionIndex": 1,
            "target": "绿色棱柱",
            "options": [{"label": "椅子"}, {"label": "绿色棱柱"}],
            "prompt": "选和上面一样的。",
        },
    )
    # 模拟 play_resource 命名：先清再写
    clear_interactive_page_context("s_name")
    set_interactive_page_context(
        "s_name",
        {
            "courseType": "naming",
            "itemId": 7,
            "target": "猫",
            "speechTarget": "猫",
            "name": "猫",
            "prompt": "这是什么呀",
        },
    )
    stored = get_interactive_page_context("s_name")
    assert stored.get("courseType") == "naming"
    assert stored.get("target") == "猫"
    assert stored.get("prompt") == "这是什么呀"
    assert "options" not in stored
    merged = merge_page_context(
        {
            "courseType": "naming",
            "itemId": 7,
            "target": "猫",
            "prompt": "这是什么呀",
        },
        "s_name",
    )
    assert merged.get("target") == "猫"
    assert not merged.get("options")
    clear_interactive_page_context("s_name")


def test_history_cleared_on_question_change():
    """换题后旧 Q&A 不得污染；下面第一张应跟当前选项。"""
    from app.dialogue.service import _page_context_fingerprint

    svc = DialogueService.__new__(DialogueService)
    svc._history = {}
    svc._context_fp = {}
    svc.provider = "rule"
    svc.api_key = ""

    q1 = {
        "courseType": "pairing",
        "questionIndex": 1,
        "questionId": "q1",
        "target": "苹果",
        "options": [
            {"id": "a", "label": "椅子"},
            {"id": "b", "label": "苹果"},
        ],
    }
    q2 = {
        "courseType": "pairing",
        "questionIndex": 2,
        "questionId": "q2",
        "target": "篮球",
        "options": [
            {"id": "c", "label": "西瓜"},
            {"id": "d", "label": "篮球"},
        ],
    }
    # 模拟上一题 LLM 轮次写入了旧选项名；指纹先对齐 Q1
    svc._history["t_hist"] = [
        {"role": "user", "content": "下面第一张是什么"},
        {"role": "assistant", "content": "这是椅子。"},
    ]
    svc._context_fp["t_hist"] = _page_context_fingerprint(q1)

    r1 = svc.generate_reply(
        "下面第一张是什么",
        session_id="t_hist",
        page_context=q1,
    )
    assert "椅子" in r1["reply"]
    # 同题指纹不变，不清空（规则答也不写入 history）
    assert len(svc._history["t_hist"]) == 2

    r2 = svc.generate_reply(
        "下面第一张是什么",
        session_id="t_hist",
        page_context=q2,
    )
    assert r2["strategy"] == "rule_position"
    assert "西瓜" in r2["reply"]
    assert "椅子" not in r2["reply"]
    assert svc._history.get("t_hist") == []
    assert svc._context_fp["t_hist"] == _page_context_fingerprint(q2)


def test_benign_offtopic_and_danger_rule_replies():
    svc = DialogueService.__new__(DialogueService)
    svc._history = {}
    svc._context_fp = {}
    svc.provider = "rule"
    svc.api_key = ""

    weather = svc.generate_reply(
        "今天天气真好，我想出去玩",
        session_id="t_off",
        page_context={"courseType": "pairing", "questionIndex": 1},
    )
    assert weather["strategy"] == "offtopic_redirect"
    assert "天气" in weather["reply"] or "玩" in weather["reply"]
    assert "屏幕" in weather["reply"] or "游戏" in weather["reply"]

    danger = svc.generate_reply(
        "我想自伤",
        session_id="t_off",
        page_context={"courseType": "pairing"},
    )
    assert danger["strategy"] == "safety_adult"
    assert "家长" in danger["reply"] or "老师" in danger["reply"]


def test_page_context_store_clears_on_question_index_change():
    clear_interactive_page_context("s_q")
    set_interactive_page_context(
        "s_q",
        {
            "courseType": "pairing",
            "questionIndex": 1,
            "target": "椅子",
            "options": [{"label": "旧选项A"}],
        },
    )
    set_interactive_page_context(
        "s_q",
        {
            "courseType": "pairing",
            "questionIndex": 2,
            "target": "篮球",
            "options": [{"label": "新选项B"}],
        },
    )
    stored = get_interactive_page_context("s_q")
    assert stored.get("questionIndex") == 2
    assert stored.get("target") == "篮球"
    assert stored["options"][0]["label"] == "新选项B"
    clear_interactive_page_context("s_q")


def test_build_page_context_strips_filename_and_wupin_labels():
    svc = DialogueService.__new__(DialogueService)
    text = svc.build_page_context_text(
        {
            "courseType": "pairing",
            "prompt": "选和上面一样的。",
            "target": "物品064",
            "options": [
                {"id": "a", "label": "物品064"},
                {"id": "b", "label": "/static/resources/images/matching/057/001.jpg"},
            ],
            "correctPosition": 1,
            "correctLabel": "物品064",
        }
    )
    assert "物品064" not in text
    assert "/static/" not in text
    assert "001.jpg" not in text


def test_matching_label_from_src_uses_semantics():
    assert matching_label_from_src("/static/resources/images/matching/064/001.jpg") == "彩色球"
    assert matching_label_from_src("/static/resources/images/matching/image_5.jpg") == "西瓜"
    assert matching_label_from_src("unknown/xyz", 0) == "左边"
    assert matching_label_from_src("unknown/xyz") == "这张"


def test_ordering_option_label_uses_object_name():
    assert "苹果" in ordering_option_label("apple", 3, 0)
    assert "饼干" in ordering_option_label("cookie", 2, 1)


def test_build_page_context_text_ordering_rule():
    svc = DialogueService.__new__(DialogueService)
    text = svc.build_page_context_text(
        {
            "courseType": "ordering",
            "prompt": "选出更大的那张。",
            "rule": "bigger",
            "ruleText": "选大的",
            "category": "size",
            "target": "选大的",  # 旧客户端误把 ruleText 当 target
            "objectName": "圆",
            "options": [
                {"label": "左边圆（程度3）", "name": "圆"},
                {"label": "右边圆（程度1）", "name": "圆"},
            ],
            "correctPosition": 1,
            "correctLabel": "左边圆（程度3）",
        }
    )
    assert "玩法：按规则找图片" in text
    assert "孩子听到的问题：选出更大的那张。" in text
    assert "当前规则：选大的" in text
    assert "本题物品：圆" in text
    assert "上面的图片：" not in text  # 排序无上方图，勿把规则当目标
    assert "下面第1张：左边圆（程度3）" in text


def test_page_context_store_clears_target_on_ordering():
    clear_interactive_page_context("s_ord")
    set_interactive_page_context(
        "s_ord",
        {"courseType": "pairing", "target": "绿色棱柱", "options": [{"label": "椅子"}]},
    )
    set_interactive_page_context(
        "s_ord",
        {
            "courseType": "ordering",
            "target": None,
            "prompt": "选出更大的那张。",
            "category": "size",
            "rule": "bigger",
            "options": [{"label": "左边圆"}],
        },
    )
    stored = get_interactive_page_context("s_ord")
    assert stored.get("courseType") == "ordering"
    assert "target" not in stored
    assert stored.get("prompt") == "选出更大的那张。"
    clear_interactive_page_context("s_ord")


def test_page_context_store_merge_prefers_client():
    clear_interactive_page_context("s1")
    set_interactive_page_context(
        "s1",
        {"courseType": "pairing", "prompt": "服务端题干", "target": "服务端目标", "wrongAttempts": 0},
    )
    merged = merge_page_context(
        {"prompt": "客户端题干", "wrongAttempts": 2},
        "s1",
    )
    assert merged["prompt"] == "客户端题干"
    assert merged["target"] == "服务端目标"
    assert merged["wrongAttempts"] == 2
    assert get_interactive_page_context("s1")["prompt"] == "服务端题干"
    clear_interactive_page_context("s1")


def test_encourage_pools_match_demorobot_style():
    bank = get_phrase_bank(force_reload=True)
    pairing = bank["encourage"]["pairing"]
    ordering = bank["encourage"]["ordering"]
    assert "没关系，再试一次" in pairing
    assert "先找和上面最像的那一张。" in pairing
    assert "我们慢慢来，先比较，再选择。" in ordering
    assert bank["encourage"]["matching"] == pairing
    assert bank["encourage"]["sequencing"] == ordering


def test_play_interactive_encourage_emits_robot_speak_text(monkeypatch):
    monkeypatch.setenv("DIALOGUE_TTS_MODE", "browser")
    get_phrase_bank(force_reload=True)

    from app.audio.service import AudioService

    emitted = []

    class FakeSocketio:
        def emit(self, event, payload, room=None, broadcast=False):
            emitted.append({"event": event, "payload": payload, "room": room})

    class FakeEmitter:
        socketio = FakeSocketio()

        def emit_for_course(self, **kwargs):
            raise AssertionError("browser 模式不应调用 emit_for_course")

    svc = AudioService()
    svc._emitter = FakeEmitter()
    ok = svc.play_interactive_course_audio("sess1", "pairing", "encourage")
    assert ok is True
    assert emitted[0]["event"] == "robot_speak_text"
    assert emitted[0]["payload"]["intent"] == "encourage"
    assert emitted[0]["payload"]["text"] in get_phrase_bank()["encourage"]["pairing"]


def test_matching_wrong_triggers_encourage():
    """错答分支应选择 encourage，点对表扬优先。"""
    def branch(data):
        if data.get("triggerPraise") or (
            "triggerPraise" not in data and data.get("isCorrect")
        ):
            return "praise"
        if data.get("isCorrect") is False and not data.get("triggerPraise"):
            return "encourage"
        return None

    assert branch({"isCorrect": False, "triggerPraise": False}) == "encourage"
    assert branch({"isCorrect": True, "triggerPraise": True}) == "praise"
    assert branch({"isCorrect": False, "triggerPraise": True}) == "praise"
    # 本题曾点错后最终点对：计分 isCorrect=false，但仍 triggerPraise
    assert branch({"isCorrect": False, "triggerPraise": True}) == "praise"
    assert pick_phrase("encourage", "pairing")
    assert pick_phrase("encourage", "ordering")


def test_interactive_status_update_always_speaks_feedback():
    """配对/排序答对或答错都必须走到 praise/encourage，不能静默。"""
    def matching_branch(is_correct, trigger_praise):
        data = {"isCorrect": is_correct, "triggerPraise": trigger_praise}
        if data.get("triggerPraise") or (
            "triggerPraise" not in data and data.get("isCorrect")
        ):
            return "praise"
        if data.get("isCorrect") is False and not data.get("triggerPraise"):
            return "encourage"
        return None

    def ordering_branch(is_correct):
        if is_correct:
            return "praise"
        if is_correct is False:
            return "encourage"
        return None

    assert matching_branch(True, True) == "praise"
    assert matching_branch(False, False) == "encourage"
    assert ordering_branch(True) == "praise"
    assert ordering_branch(False) == "encourage"
    assert ordering_branch(None) is None


def test_ordering_bare_aux_question_ignored(monkeypatch):
    """排序裸 aux.question 应被忽略，避免盖掉规则提问。"""
    monkeypatch.setenv("DIALOGUE_TTS_MODE", "browser")
    from app.audio.service import AudioService

    emitted = []

    class FakeSocketio:
        def emit(self, event, payload, room=None, broadcast=False):
            emitted.append({"event": event, "payload": payload, "room": room})

    class FakeEmitter:
        socketio = FakeSocketio()

        def emit_for_course(self, **kwargs):
            emitted.append({"event": "file", "kwargs": kwargs})
            return True

    svc = AudioService()
    svc._emitter = FakeEmitter()
    ok = svc.process_play_resource(
        "sess1",
        {"courseType": "ordering", "aux": {"question": True}},
    )
    assert ok is False
    assert emitted == []


def test_ordering_question_text_override(monkeypatch):
    """sequencing 传入的规则句应原样朗读，不回落兜底。"""
    monkeypatch.setenv("DIALOGUE_TTS_MODE", "browser")
    get_phrase_bank(force_reload=True)
    from app.audio.service import AudioService

    emitted = []

    class FakeSocketio:
        def emit(self, event, payload, room=None, broadcast=False):
            emitted.append(payload)

    class FakeEmitter:
        socketio = FakeSocketio()

        def emit_for_course(self, **kwargs):
            raise AssertionError("browser 模式不应调用 emit_for_course")

    svc = AudioService()
    svc._emitter = FakeEmitter()
    ok = svc.play_interactive_course_audio(
        "s_ov",
        "ordering",
        "question_size_bigger",
        category="size",
        rule="bigger",
        text="选出更大的那张。",
    )
    assert ok is True
    assert emitted[0]["text"] == "选出更大的那张。"
    assert "按规则" not in emitted[0]["text"]


def test_onomatopoeia_question_uses_item_name():
    from app.dialogue.phrases import (
        format_onomatopoeia_question,
        get_phrase_bank,
        naturalize_onomatopoeia_name,
        pick_phrase,
    )

    get_phrase_bank(force_reload=True)
    assert naturalize_onomatopoeia_name("猫") == "小猫"
    assert naturalize_onomatopoeia_name("小猫叫") == "小猫"
    assert naturalize_onomatopoeia_name("小狗叫") == "小狗"
    cat_pool = {
        "小猫会怎么叫呀？",
        "学一学小猫的叫声。",
        "小猫的声音是怎样的？",
    }
    dog_pool = {
        "小狗会怎么叫呀？",
        "学一学小狗的叫声。",
        "小狗的声音是怎样的？",
    }
    assert format_onomatopoeia_question("猫") in cat_pool
    assert format_onomatopoeia_question("小猫叫") in cat_pool
    assert format_onomatopoeia_question(None) == "听听，这是什么声音呀？"
    assert pick_phrase("question", "onomatopoeia", name="狗") in dog_pool


def test_onomatopoeia_aux_question_emits_named_phrase(monkeypatch):
    monkeypatch.setenv("DIALOGUE_TTS_MODE", "browser")
    get_phrase_bank(force_reload=True)
    from app.audio.service import AudioService

    emitted = []

    class FakeSocketio:
        def emit(self, event, payload, room=None, broadcast=False):
            emitted.append({"event": event, "payload": payload})

    class FakeEmitter:
        socketio = FakeSocketio()

        def emit_for_course(self, **kwargs):
            raise AssertionError("browser 模式不应调用 emit_for_course")

    svc = AudioService()
    svc._emitter = FakeEmitter()
    ok = svc.process_play_resource(
        "sess_ono",
        {
            "courseType": "onomatopoeia",
            "aux": {"question": True},
            "itemName": "猫",
            "speechTarget": "喵",
        },
    )
    assert ok is True
    assert emitted[0]["event"] == "robot_speak_text"
    assert emitted[0]["payload"]["text"] in {
        "小猫会怎么叫呀？",
        "学一学小猫的叫声。",
        "小猫的声音是怎样的？",
    }


def test_parse_wake_utterance_variants():
    from app.dialogue.service import is_wake_phrase, parse_wake_utterance

    for text in (
        "麦麦，麦麦",
        "麦麦麦麦",
        "麦麦 麦麦",
        "麦麦！麦麦",
        " 麦麦，麦麦。 ",
        "妹妹妹妹",
        "卖卖卖卖",
        "妹妹，卖卖",
        "买卖买卖",
        "妹妹，妹妹",
        "卖卖，麦麦",
        "脉脉迈迈",
        "妹 妹，卖 卖",
        # ASR 近音：man/ma 软匹配
        "慢慢慢慢",
        "卖卖麦吗",
        "慢慢，麦麦",
        "吗吗嘛嘛",
        "埋埋霾霾",
        "满满漫漫",
    ):
        matched, rem = parse_wake_utterance(text)
        assert matched is True, text
        assert rem == "", text
        assert is_wake_phrase(text) is True, text

    matched, rem = parse_wake_utterance("麦麦，麦麦，下面第一张是什么")
    assert matched is True
    assert "下面第一张" in rem
    assert is_wake_phrase("麦麦，麦麦，下面第一张是什么") is False

    matched, rem = parse_wake_utterance("妹妹妹妹你好")
    assert matched is True
    assert rem == "你好"

    matched, rem = parse_wake_utterance("麦麦麦麦你好")
    assert matched is True
    assert rem == "你好"

    matched, rem = parse_wake_utterance("慢慢慢慢你好")
    assert matched is True
    assert rem == "你好"

    matched, rem = parse_wake_utterance("卖卖麦吗，下面第一张是什么")
    assert matched is True
    assert "下面第一张" in rem

    # 过短 / 无关：不应唤醒
    for text in (
        "你好",
        "小猫叫",
        "妹妹",
        "卖卖",
        "麦麦",
        "慢慢",
        "妈妈",
        "你好麦麦",
        "今天天气怎么样",
        "妹妹你好吗",
        "我家有一只妹妹",
        "买卖东西",
        "你慢慢说",
        "这是什么吗",
    ):
        matched, rem = parse_wake_utterance(text)
        assert matched is False, text
        assert rem == text.strip(), text
        assert is_wake_phrase(text) is False, text

def test_awake_cleared_on_question_fingerprint_change():
    from app.dialogue.service import _page_context_fingerprint

    svc = DialogueService.__new__(DialogueService)
    svc._history = {}
    svc._context_fp = {}
    svc._awake_fp = {}
    svc.provider = "rule"
    svc.api_key = ""

    q1 = {
        "courseType": "pairing",
        "questionId": "q1",
        "itemId": 1,
        "questionIndex": 1,
        "target": "椅子",
        "options": [{"label": "椅子"}, {"label": "球"}],
    }
    q2 = {
        "courseType": "pairing",
        "questionId": "q2",
        "itemId": 1,
        "questionIndex": 2,
        "target": "球",
        "options": [{"label": "球"}, {"label": "椅子"}],
    }

    svc.set_awake("wake_sid", q1)
    assert svc.is_session_awake("wake_sid", q1) is True
    assert svc._awake_fp["wake_sid"] == _page_context_fingerprint(q1)

    # 同指纹 generate_reply 不退出唤醒
    svc._context_fp["wake_sid"] = _page_context_fingerprint(q1)
    svc.generate_reply("下面第一张是什么", session_id="wake_sid", page_context=q1)
    assert svc.is_session_awake("wake_sid", q1) is True

    # 题目切换：同步历史时退出唤醒
    svc.generate_reply("下面第一张是什么", session_id="wake_sid", page_context=q2)
    assert svc.is_session_awake("wake_sid", q2) is False
    assert "wake_sid" not in svc._awake_fp
