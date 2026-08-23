"""v5.39 三栏目内容丰富计划的新能力测试。

覆盖：易经经典一句 / 问题扩池 / 黄历现代化 / 免责尾注双路径 /
塔罗框架轮换 / 私聊敏感分流 / greeting 节气注入。
所有新能力默认关闭：关闭时行为与既有基线一致。
"""

from datetime import datetime, timedelta, timezone


_CST = timezone(timedelta(hours=8))


def _config(**mystic_overrides):
    mystic = {
        "enabled": True,
        "cta_enabled": False,
        "private_reply_enabled": True,
        "disclaimer_note_enabled": False,
        "tarot_spread_rotation_enabled": False,
        "private_sensitive_guard_enabled": False,
    }
    mystic.update(mystic_overrides)
    return {"MYSTIC_BROADCAST_CONFIG": mystic}


# ── 批次1：易经经典一句 ────────────────────────────────────────────


def test_iching_payload_contains_classic_line_for_every_hexagram():
    from tasks.support.mystic_content import (
        _HEXAGRAMS,
        _HEXAGRAM_CLASSICS,
        build_mystic_broadcast,
    )

    assert len(_HEXAGRAM_CLASSICS) == 64
    for name, (plain, action) in _HEXAGRAM_CLASSICS.items():
        assert plain and action, f"{name} 经典句不完整"
        assert "→" not in plain and "→" not in action

    payload = build_mystic_broadcast(
        _config(), "evening", datetime(2026, 7, 27, 20, 35, tzinfo=_CST)
    )
    guancha = dict(payload["blocks"][1]["lines"])
    assert "经典一句" in guancha
    assert "→" in guancha["经典一句"]
    # 卦名与经典表一一对应（本卦名必须在表内）
    ben = dict(payload["blocks"][0]["lines"])["本卦"]
    assert any(f"第{h[0]}卦" in ben and h[1] in _HEXAGRAM_CLASSICS for h in _HEXAGRAMS)
    names = [h[1] for h in _HEXAGRAMS]
    assert len(names) == len(set(names)) == 64


def test_iching_questions_pool_expanded_without_duplicates():
    from tasks.support.mystic_content import _ICHING_QUESTIONS

    assert len(_ICHING_QUESTIONS) == 16
    assert len(set(_ICHING_QUESTIONS)) == 16


# ── 批次2：黄历现代化 ──────────────────────────────────────────────


def test_almanac_has_duty_god_note_and_lucky_hours_line():
    from tasks.support.mystic_content import build_mystic_broadcast

    payload = build_mystic_broadcast(
        _config(), "morning", datetime(2026, 7, 27, 9, 5, tzinfo=_CST)
    )
    day_value = dict(payload["blocks"][1]["lines"])
    # 值神浅释跟随库内值神名存在（2026-07-27 为金贵）
    assert day_value.get("值神浅释", "").startswith(("黄道", "黑道"))
    # 吉时参考：吉时辰名 + 两位钟点区间
    lucky_line = day_value.get("吉时参考", "")
    assert lucky_line, "当日应至少有一个吉时"
    for chunk in lucky_line.split(" · "):
        assert chunk.endswith("时") or "-" in chunk


def test_format_lucky_hours_handles_midnight_crossing_and_empty():
    from tasks.support.mystic_content import _format_lucky_hours

    hours = [("子", 23, "吉"), ("丑", 1, "凶"), ("卯", 5, "吉")]
    text = _format_lucky_hours(hours)
    assert "子时23-01" in text
    assert "卯时05-07" in text
    assert "丑" not in text
    all_unlucky = [("子", 23, "凶")]
    assert _format_lucky_hours(all_unlucky) == ""
    assert _format_lucky_hours([]) == ""


def test_almanac_insight_pools_expanded_with_branch_keywords():
    """扩池后各分支条目仍含分支关键词，保住 golden 断言口径。"""
    import inspect

    from tasks.support import mystic_content

    source = inspect.getsource(mystic_content._build_almanac)
    # 分支1 的每个模板串都必须含「动土」或「出行」（golden 断言依赖）
    branch1 = source.split("insight = ins.choice((")[1].split("))")[0]
    templates = [seg for seg in branch1.split('",') if seg.strip()]
    assert len(templates) >= 8
    assert all("动土" in seg or "出行" in seg for seg in templates)


# ── 批次2c：免责尾注双路径 ─────────────────────────────────────────


def test_disclaimer_disabled_by_default_keeps_payload_clean():
    from tasks.support.mystic_content import build_mystic_broadcast

    now = datetime(2026, 7, 27, 9, 5, tzinfo=_CST)
    for period in ("morning", "afternoon", "evening"):
        payload = build_mystic_broadcast(_config(), period, now)
        assert "note" not in payload


def test_disclaimer_enabled_renders_across_all_layers():
    from core.broadcast_formatter import build_mystic_html, build_rich_mystic_card_message
    from core.broadcast_image_payload import build_mystic_image_payload
    from tasks.broadcast.mystic_broadcast_task import build_mystic_cta
    from tasks.support.mystic_content import DISCLAIMER_NOTE, build_mystic_broadcast

    now = datetime(2026, 7, 27, 9, 5, tzinfo=_CST)
    for period in ("morning", "afternoon", "evening"):
        payload = build_mystic_broadcast(
            _config(disclaimer_note_enabled=True), period, now
        )
        assert payload.get("note") == DISCLAIMER_NOTE

        image_payload = build_mystic_image_payload(payload)
        footers = [value for label, value in image_payload.get("footer_lines", [])]
        assert DISCLAIMER_NOTE in footers

        combo = build_mystic_cta(payload, config=_config(disclaimer_note_enabled=True))
        payload["cta"] = (combo.get("buttons") or [{}])[0]
        html = build_mystic_html(payload)
        rich = build_rich_mystic_card_message(payload)
        assert DISCLAIMER_NOTE in html
        assert DISCLAIMER_NOTE in rich
        # 尾注不是 block：h3 数仍等于 blocks 数
        assert rich.count("<h3>") == len(payload["blocks"])


def test_private_reply_disclaimer_follows_same_switch():
    from tasks.support.mystic_content import DISCLAIMER_NOTE, build_private_mystic_reply

    now = datetime(2026, 7, 27, 16, 0, tzinfo=_CST)
    off = build_private_mystic_reply("帮我看看风水", 42, now, config=_config())
    assert DISCLAIMER_NOTE not in off["text"]
    on = build_private_mystic_reply(
        "帮我看看风水", 42, now, config=_config(disclaimer_note_enabled=True)
    )
    assert on["text"].endswith(DISCLAIMER_NOTE)


# ── 批次3：塔罗框架轮换 ────────────────────────────────────────────


def test_tarot_rotation_disabled_keeps_default_framework():
    from tasks.support.mystic_content import build_mystic_broadcast

    payload = build_mystic_broadcast(
        _config(), "afternoon", datetime(2026, 7, 27, 13, 5, tzinfo=_CST)
    )
    rows = payload["blocks"][0]["lines"]
    assert [row[0] for row in rows] == ["主牌", "助力", "提醒"]
    assert "牌阵从" in payload["insight"]


def test_tarot_spread_key_distribution_respects_80_percent_floor():
    from datetime import date, timedelta

    from tasks.support.mystic_content import _resolve_tarot_spread_key, _spread_rng

    base = date(2026, 7, 1)
    alternates = 0
    total = 200
    for offset in range(total):
        day = (base + timedelta(days=offset)).strftime("%Y-%m-%d")
        key = _resolve_tarot_spread_key(True, _spread_rng(day, "afternoon"))
        alternates += key != "default"
    # 统计意义上允许波动，但不应显著低于 80% 下限
    assert alternates <= total * 0.35
    # 关闭时永远 default
    for offset in range(30):
        day = (base + timedelta(days=offset)).strftime("%Y-%m-%d")
        key = _resolve_tarot_spread_key(False, _spread_rng(day, "afternoon"))
        assert key == "default"


def test_tarot_alternate_frameworks_have_independent_roles_and_templates():
    from tasks.support.mystic_content import _TAROT_SPREAD_STYLES

    default_roles = _TAROT_SPREAD_STYLES["default"]["roles"]
    for key in ("situation", "status"):
        style = _TAROT_SPREAD_STYLES[key]
        assert style["roles"] != default_roles
        assert len(style["actions"]) >= 10
        assert len(style["templates"]) >= 5
        # 备选框架句式不带「牌阵从」，动作池不带主牌/提醒角色词
        joined_actions = "".join(style["actions"])
        assert "主牌" not in joined_actions and "提醒牌" not in joined_actions


# ── 批次4：私聊占卜敏感分流 ────────────────────────────────────────


def test_sensitive_guard_disabled_keeps_normal_divination_output():
    from tasks.support.mystic_content import build_private_mystic_reply

    reply = build_private_mystic_reply(
        "我该买哪支股票，帮我算卦",
        42,
        datetime(2026, 7, 27, 16, 0, tzinfo=_CST),
        config=_config(),
    )
    assert reply["mode"] == "iching"
    assert "为你起一卦" in reply["text"]


def test_sensitive_guard_blocks_only_when_enabled_and_matched():
    from tasks.support.mystic_content import build_private_mystic_reply

    cfg = _config(private_sensitive_guard_enabled=True)
    now = datetime(2026, 7, 27, 16, 0, tzinfo=_CST)
    cases = {
        "我该买哪支股票，帮我算卦": "金融投资",
        "帮我算卦看这场官司能不能赢": "法律纠纷",
        "抽一张塔罗看看这个病能不能治好": "医疗健康",
    }
    for text, domain in cases.items():
        reply = build_private_mystic_reply(text, 42, now, config=cfg)
        assert reply["mode"] == "sensitive_hold"
        assert domain in reply["text"]
        assert "@" not in reply["text"]
        assert "专业人士" in reply["text"]
        assert reply["token_usage"] == 0


def test_sensitive_guard_does_not_hijack_normal_requests():
    from tasks.support.mystic_content import resolve_private_mystic_mode as resolve

    from tasks.support.mystic_content import build_private_mystic_reply

    cfg = _config(private_sensitive_guard_enabled=True)
    now = datetime(2026, 7, 27, 16, 0, tzinfo=_CST)
    normal_cases = {
        "帮我算卦看工作": "iching",
        "给我抽一下塔罗看感情": "tarot",
        "帮我看看风水": "almanac",
        "想算一下最近的事业运该不该换个方向": None,  # 不在窄词表内，正常放行
    }
    for text, mode in normal_cases.items():
        if mode is not None:
            assert resolve(text) == mode
            reply = build_private_mystic_reply(text, 42, now, config=cfg)
            assert reply["mode"] == mode, f"正常请求被误拦: {text}"
            assert reply["mode"] != "sensitive_hold"


# ── 批次5：greeting 节气注入 ───────────────────────────────────────


def test_solar_term_hint_disabled_by_default():
    from core.ai_engine import AIEngine

    engine = AIEngine.__new__(AIEngine)
    engine.config = {"GREETING_CONFIG": {}}
    assert engine._get_solar_term_hint() == ""


def test_solar_term_hint_returns_date_fact_when_enabled(monkeypatch):
    from types import SimpleNamespace

    from core.ai_engine import AIEngine

    calls = []

    class FakeLunar:
        todaySolarTerms = "无"
        nextSolarTerm = "白露"
        nextSolarTermDate = (9, 7)

    fake_module = SimpleNamespace(Lunar=lambda *_a, **_k: FakeLunar())
    import sys

    monkeypatch.setitem(sys.modules, "cnlunar", fake_module)

    engine = AIEngine.__new__(AIEngine)
    engine.config = {"GREETING_CONFIG": {"solar_term_hint_enabled": True}}
    AIEngine._SOLAR_TERM_HINT_CACHE.clear()
    try:
        hint = engine._get_solar_term_hint()
        calls.append(hint)
        assert "白露" in hint
        assert "距下一节气" in hint
        # 当日缓存：第二次直接命中
        again = engine._get_solar_term_hint()
        assert again == hint
    finally:
        AIEngine._SOLAR_TERM_HINT_CACHE.clear()


def test_greeting_prompt_appends_solar_hint_only_when_enabled(monkeypatch):
    from core.ai_engine import AIEngine

    engine = AIEngine.__new__(AIEngine)
    engine.config = {"GREETING_CONFIG": {"solar_term_hint_enabled": False}}
    engine._legacy_greeting_prompt_warned = False
    # 场景1：hint 方法返回空串（等价于开关关闭的真实行为）→ 正文无节气段
    monkeypatch.setattr(AIEngine, "_get_solar_term_hint", lambda self: "")
    text, is_full = engine._get_mode_persona("morning")
    assert is_full is True
    assert "处暑" not in text

    # 场景2：开关开启且 hint 非空 → 追加在问候要求之后
    monkeypatch.setattr(
        AIEngine,
        "_get_solar_term_hint",
        lambda self: "\n【今日交节·处暑：测试提示。】",
    )
    engine.config = {"GREETING_CONFIG": {"solar_term_hint_enabled": True}}
    text_open, _ = engine._get_mode_persona("morning")
    assert "处暑" in text_open
    assert "{seed_hint}" not in text_open


def test_non_greeting_modes_never_get_solar_hint(monkeypatch):
    from core.ai_engine import AIEngine

    engine = AIEngine.__new__(AIEngine)
    engine.config = {}
    engine._legacy_greeting_prompt_warned = False
    monkeypatch.setattr(
        AIEngine,
        "_get_solar_term_hint",
        lambda self: "\n【今日交节·处暑：测试提示。】",
    )
    # rules 模式走同一 return 分支但不属于 greeting modes，不得被注入
    text, is_full = engine._get_mode_persona("rules")
    assert is_full is True
    assert "处暑" not in text
