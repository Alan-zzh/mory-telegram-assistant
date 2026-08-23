# -*- coding: utf-8 -*-
"""
tests/unit/test_proactive_engage.py  ·  v5.14.0

测试 ProactiveEngage 模块的冷却逻辑、豁免、异常保护
"""
import sys
import os
import time
import sqlite3
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


class _FakeMoryBot:
    def __init__(self):
        self.bot = _FakeBot()
        self.reply_calls = 0

    def reply_and_track(self, m, text):
        self.reply_calls += 1
        return _FakeMessage(self.reply_calls)


class _FakeBot:
    def __init__(self):
        self.sent = []
        self.edited_markups = []

    def send_message(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return _FakeMessage(0)

    def edit_message_reply_markup(self, *args, **kwargs):
        self.edited_markups.append((args, kwargs))


class _FakeMessage:
    def __init__(self, mid):
        self.message_id = mid
        self.chat = type("Chat", (), {"id": 100})()


class _FakeDB:
    def __init__(self):
        self.logged = []
        self.events = []

    def log_proactive_engage(self, **kwargs):
        self.logged.append(kwargs)
        return len(self.logged)

    def log_conversion_event(self, uid, event_type):
        self.events.append((uid, event_type))


class _FakePersistedDB(_FakeDB):
    def __init__(self):
        super().__init__()
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            """CREATE TABLE proactive_engage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                uname TEXT NOT NULL DEFAULT '',
                msg TEXT NOT NULL DEFAULT '',
                matched_keyword TEXT NOT NULL DEFAULT '',
                reply_text TEXT NOT NULL DEFAULT '',
                ts INTEGER NOT NULL,
                converted INTEGER NOT NULL DEFAULT 0
            )"""
        )


def make_pe(enabled=True, cooldown_minutes=30):
    from modules.proactive_engage import ProactiveEngage
    cfg = {
        "PROACTIVE_ENGAGE_CONFIG": {
            "enabled": enabled,
            "cooldown_minutes": cooldown_minutes,
        },
        "ADMIN_ID": 0,
    }
    return ProactiveEngage(
        db=_FakeDB(),
        mory_bot=_FakeMoryBot(),
        ai=None,
        config=cfg,
    )


def test_should_engage_disabled():
    """enabled=false 时不搭讪"""
    pe = make_pe(enabled=False)
    ok, kw = pe.should_engage(uid=123, msg="订阅一个月的有多少视频", is_admin=False)
    assert ok is False
    assert kw == ""
    print("✓ enabled=false 时不搭讪")


def test_should_engage_admin_exempt():
    """管理员豁免"""
    pe = make_pe(enabled=True)
    ok, kw = pe.should_engage(uid=123, msg="订阅多少钱", is_admin=True)
    assert ok is False
    print("✓ 管理员豁免")


def test_should_engage_normal_user():
    """普通用户命中关键词应搭讪"""
    pe = make_pe(enabled=True)
    ok, kw = pe.should_engage(uid=123, msg="订阅一个月的有多少视频", is_admin=False)
    assert ok is True
    assert "订阅" in kw
    print(f"✓ 普通用户命中: keyword={kw}")


def test_should_engage_no_keyword():
    """无关消息不搭讪"""
    pe = make_pe(enabled=True)
    ok, kw = pe.should_engage(uid=123, msg="今天天气真好", is_admin=False)
    assert ok is False
    print("✓ 无关消息不搭讪")


def test_custom_concept_question_is_not_treated_as_order():
    pe = make_pe(enabled=True)
    ok, _ = pe.should_engage(
        uid=123,
        msg="定制舞是什么？先介绍一下",
        is_admin=False,
    )
    assert ok is False


def test_cooldown_blocks_repeat():
    """冷却期内不搭讪"""
    pe = make_pe(enabled=True, cooldown_minutes=30)
    uid = 456

    # 第一次
    ok1, _ = pe.should_engage(uid=uid, msg="订阅多少钱", is_admin=False)
    assert ok1 is True
    pe._set_cooldown(uid)

    # 第二次（同冷却期内）
    ok2, _ = pe.should_engage(uid=uid, msg="包月划算吗", is_admin=False)
    assert ok2 is False
    print("✓ 冷却期内不搭讪")


def test_persisted_cooldown_blocks_after_restart():
    """[Codex] 落库冷却应在重启后继续生效"""
    from modules.proactive_engage import ProactiveEngage

    db = _FakePersistedDB()
    db.conn.execute(
        "INSERT INTO proactive_engage_log (uid, chat_id, uname, msg, matched_keyword, reply_text, ts, converted) VALUES (?,?,?,?,?,?,?,0)",
        (999, 100, "u", "订阅多少钱", "订阅", "reply", int(time.time())),
    )
    db.conn.commit()
    pe = ProactiveEngage(
        db=db,
        mory_bot=_FakeMoryBot(),
        ai=None,
        config={"PROACTIVE_ENGAGE_CONFIG": {"enabled": True, "cooldown_minutes": 30}},
    )

    ok, _ = pe.should_engage(uid=999, msg="订阅多少钱", is_admin=False)

    assert ok is False
    print("✓ 落库冷却跨重启生效")


def test_cooldown_expired():
    """冷却期外可搭讪"""
    pe = make_pe(enabled=True, cooldown_minutes=0)  # 0 分钟（无冷却）
    uid = 789

    ok1, _ = pe.should_engage(uid=uid, msg="订阅多少钱", is_admin=False)
    pe._set_cooldown(uid)
    ok2, _ = pe.should_engage(uid=uid, msg="包月划算吗", is_admin=False)
    assert ok1 is True
    # cooldown_minutes=0 表示立即过期
    assert ok2 is True
    print("✓ cooldown_minutes=0 时立即过期")


def test_engage_success_writes_log():
    """engage 成功应写库"""
    pe = make_pe(enabled=True)
    pe._set_cooldown = lambda uid: None  # 避免锁

    m = _FakeMessage(0)
    result = pe.engage(
        uid=111,
        uname="测试用户",
        chat_id=222,
        msg="订阅多少钱",
        matched_keyword="订阅",
        m=m,
    )
    assert result is True
    assert len(pe.db.logged) == 1
    assert pe.db.logged[0]["uid"] == 111
    assert pe.db.logged[0]["matched_keyword"] == "订阅"
    assert (111, "proactive_engaged") in pe.db.events
    assert len(pe.mory_bot.bot.sent) == 1
    markup = pe.mory_bot.bot.edited_markups[0][1]["reply_markup"]
    assert len(markup.keyboard) == 1
    assert markup.keyboard[0][0].url == "https://t.me/moryselect"
    print("✓ engage 成功写库 + 事件")


def test_engage_exception_silent():
    """engage 异常应静默（不抛未捕获异常）"""
    class _BrokenDB:
        def log_proactive_engage(self, **kw):
            raise RuntimeError("DB broken")

    from modules.proactive_engage import ProactiveEngage
    cfg = {"PROACTIVE_ENGAGE_CONFIG": {"enabled": True, "cooldown_minutes": 30}, "ADMIN_ID": 0}
    pe = ProactiveEngage(
        db=_BrokenDB(),
        mory_bot=_FakeMoryBot(),
        ai=None,
        config=cfg,
    )
    m = _FakeMessage(0)
    # 必须不抛异常
    result = pe.engage(uid=1, uname="x", chat_id=2, msg="订阅", matched_keyword="订阅", m=m)
    # 入库失败但群回复可能成功 → 不强制 result=True
    assert isinstance(result, bool)
    print("✓ engage 异常静默不崩")


def test_engage_send_failure_does_not_claim_success_or_persist():
    """真实发送失败时必须交还主链，不能写成功日志并截断 P10。"""
    pe = make_pe(enabled=True)
    pe.mory_bot = object()
    pe._generate_reply = lambda *_args, **_kwargs: "测试回复"

    result = pe.engage(
        uid=1,
        uname="测试用户",
        chat_id=2,
        msg="订阅多少钱",
        matched_keyword="订阅",
        m=_FakeMessage(0),
    )

    assert result is False
    assert pe.db.logged == []
    assert pe.db.events == []


def test_dispatcher_leaves_explicit_subscription_to_unified_p10():
    """截图原句必须绕过旧搭讪旁路，由 P10 生成人设正文和单一下单按钮。"""
    from core.message_dispatcher import _dispatch_p7_5_proactive_engage

    class _Proactive:
        def __init__(self):
            self.should_calls = 0
            self.engage_calls = 0

        def should_engage(self, **_kwargs):
            self.should_calls += 1
            return True, "订阅"

        def engage(self, **_kwargs):
            self.engage_calls += 1
            return True

    proactive = _Proactive()
    dctx = SimpleNamespace(
        is_group=True,
        proactive_eligible=True,
        uid=42,
        uname="雨轩",
        chat_id=-1001,
        text="怎么订阅",
        conversation_history=[{
            "role": "assistant",
            "content": "全套预览在 @moryselect，你先看看。",
        }],
        msg=_FakeMessage(9),
        ctx=SimpleNamespace(
            proactive_engage=proactive,
            db=_FakeDB(),
            config={
                "PROACTIVE_ENGAGE_CONFIG": {
                    "enabled": True,
                    "only_in_group_id": False,
                },
            },
        ),
    )

    assert _dispatch_p7_5_proactive_engage(dctx) is False
    assert proactive.should_calls == 0
    assert proactive.engage_calls == 0


def test_old_private_prompt_is_invalidated_and_reply_follows_single_target():
    from modules.proactive_engage import ProactiveEngage

    class _FakeAI:
        def __init__(self):
            self.calls = []

        def ask(self, prompt, mode="normal", **kwargs):
            self.calls.append((prompt, mode, kwargs))
            return "先去预览看看。"

    ai = _FakeAI()
    pe = ProactiveEngage(
        db=_FakeDB(),
        mory_bot=_FakeMoryBot(),
        ai=ai,
        config={
            "PROMPT_TEMPLATES": {
                "business_engage": "旧提示：自然引导他私聊了解详情。",
            },
            "PROACTIVE_ENGAGE_CONFIG": {"enabled": True},
        },
    )

    preview_reply = pe._generate_reply("订阅多少钱", "订阅", "测试用户")

    assert ai.calls[0][0] == "订阅多少钱"
    assert ai.calls[0][1] == "convert"
    assert "不要引导私聊" in ai.calls[0][2]["stage_hint"]
    # v5.39 治理：入口由按钮承载，正文不再出现 @ 链接（去双呈现）
    assert "@moryselect" not in preview_reply.lower()
    assert "@MorychannelBot" not in preview_reply

    order_reply = pe._generate_reply("我要下单", "下单", "测试用户")
    assert "@MorychannelBot" not in order_reply
    assert "@moryselect" not in order_reply.lower()


if __name__ == "__main__":
    test_should_engage_disabled()
    test_should_engage_admin_exempt()
    test_should_engage_normal_user()
    test_should_engage_no_keyword()
    test_cooldown_blocks_repeat()
    test_cooldown_expired()
    test_engage_success_writes_log()
    test_engage_exception_silent()
    print("\n🎉 所有 ProactiveEngage 测试通过！")
