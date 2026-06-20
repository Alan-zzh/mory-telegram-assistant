# -*- coding: utf-8 -*-
"""
tests/alert/test_cascade_suppression.py  ·  阶段2-A 级联告警抑制故障注入测试

验证 core/alert_bot.py 的级联抑制、限流、汇总逻辑，确保极端故障下
不刷屏、不触发 Telegram 429 频控。

测试覆盖（5 个用例）：
  1. 数据库锁定级联抑制（根因活跃 → 下游 mute）
  2. 根因解除后下游恢复
  3. 5min 定时汇总（count>1 合并发送）
  4. 限流保护（10/min 上限）
  5. 非级联告警正常发送

设计要点：
  - 每个用例独立 _AlertBot 实例（setUp 重建，tearDown 清单例）
  - mock _call_telegram 替代真实 TG 发送，记录调用次数与文本
  - 不修改 alert_bot.py 源码，仅通过实例属性注入 mock
"""

import os
import sys
import time
import unittest

# 把项目根目录加入 sys.path，便于直接 import core.alert_bot
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core import alert_bot
from core.alert_bot import _AlertBot, _DEDUP_WINDOW, _RATE_LIMIT_MAX


class CascadeSuppressionTestBase(unittest.TestCase):
    """级联抑制测试基类：每个用例独立 _AlertBot 实例，mock TG 发送"""

    def setUp(self):
        # 重置模块级单例，避免用例间相互污染
        alert_bot._instance = None
        # 直接构造实例，绕过懒加载（不读环境变量）
        self.bot = _AlertBot()
        # 强制启用，跳过"未配置 Token"降级分支
        self.bot.enabled = True
        # mock 实际 TG 发送：记录调用文本，始终返回成功
        self.tg_calls = []
        self.bot._call_telegram = self._fake_call_telegram
        # 注入单例，让模块级函数（send_alert / flush_alert_summary / get_alert_stats）使用本实例
        alert_bot._instance = self.bot

    def tearDown(self):
        # 清理单例，避免影响后续用例
        alert_bot._instance = None

    def _fake_call_telegram(self, text: str) -> bool:
        """模拟 Telegram 发送：记录文本，始终返回成功"""
        self.tg_calls.append(text)
        return True

    def _stats(self) -> dict:
        """获取告警统计的快捷方法"""
        return self.bot.get_stats()


class TestCascadeSuppression(CascadeSuppressionTestBase):
    """阶段2-A 级联告警抑制故障注入测试（5 个用例）"""

    # ── 用例 1：数据库锁定级联抑制 ────────────────────────────
    def test_01_database_lock_cascade_suppression(self):
        """
        故障注入：SYSTEM_DATABASE_LOCKED 根因告警活跃时，
        立即触发 10 个 SCHEDULER_JOB_FAILED + 5 个 WRITE_QUEUE_BACKLOG，
        断言下游 15 条全部被抑制，根因告警正常发送。
        """
        # 1) 发送根因告警：数据库锁定（标题归一化为 SYSTEM_DATABASE_LOCKED）
        ok = alert_bot.send_alert(
            "CRITICAL", "数据库锁定", "SQLite busy timeout", {"lock": True}
        )
        self.assertTrue(ok, "根因告警应发送成功")
        self.assertIn(
            "SYSTEM_DATABASE_LOCKED",
            self.bot._active_root_causes,
            "根因告警应写入 _active_root_causes",
        )

        # 2) 立即发送 10 个 SCHEDULER_JOB_FAILED（下游，标题归一化匹配）
        for i in range(10):
            alert_bot.send_alert(
                "CRITICAL", "调度任务失败", f"job_{i} error", {"job": f"j{i}"}
            )

        # 3) 立即发送 5 个 WRITE_QUEUE_BACKLOG（下游，标题归一化匹配）
        for i in range(5):
            alert_bot.send_alert(
                "WARNING", "WriteQueue 积压", f"qsize={60 + i}", {"qsize": 60 + i}
            )

        stats = self._stats()
        # 根因告警发送成功，下游 15 条全部被抑制
        self.assertEqual(
            stats["sent"], 1, f"应仅发送 1 条根因告警，实际 sent={stats['sent']}"
        )
        self.assertEqual(
            stats["suppressed"], 15,
            f"应抑制 15 条下游告警，实际 suppressed={stats['suppressed']}",
        )
        # TG 实际只被调用 1 次（根因告警）
        self.assertEqual(
            len(self.tg_calls), 1,
            f"TG 应只被调用 1 次，实际 {len(self.tg_calls)} 次",
        )

    # ── 用例 2：根因解除后下游恢复 ────────────────────────────
    def test_02_downstream_recovers_after_root_cause_cleared(self):
        """
        故障注入：根因告警后手动清除 _active_root_causes（等价于 5min 无新触发），
        断言下游告警恢复正常发送，不再被抑制。
        """
        # 1) 先发根因告警
        alert_bot.send_alert("CRITICAL", "数据库锁定", "lock", {})

        # 2) 此时下游应被抑制（返回 False，suppressed +1）
        ok_suppressed = alert_bot.send_alert(
            "CRITICAL", "调度任务失败", "job error", {}
        )
        self.assertFalse(
            ok_suppressed, "根因活跃时，下游告警应被抑制（send_alert 返回 False）"
        )
        self.assertEqual(self._stats()["suppressed"], 1, "应已抑制 1 条")

        # 3) 模拟根因解除：清空 _active_root_causes（等价于 5min 无新触发被 _gc_root_causes 回收）
        self.bot._active_root_causes.clear()

        # 4) 再次发送下游告警，应正常发送
        #    注：旧 counter 的 suppressed 状态翻转，会先收尾旧 counter 再开新窗口
        ok_recovered = alert_bot.send_alert(
            "CRITICAL", "调度任务失败", "job error 2", {}
        )
        self.assertTrue(
            ok_recovered, "根因解除后，下游告警应正常发送（send_alert 返回 True）"
        )

        stats = self._stats()
        # 抑制计数不应再增加（仍为 1）
        self.assertEqual(
            stats["suppressed"], 1,
            f"根因解除后不应再增加抑制计数，实际 suppressed={stats['suppressed']}",
        )
        # 应有告警发送成功（根因 1 + 恢复后 1 = 2）
        self.assertGreaterEqual(
            stats["sent"], 2,
            f"应有 ≥2 条告警发送成功（根因 + 恢复后下游），实际 sent={stats['sent']}",
        )

    # ── 用例 3：5min 定时汇总 ────────────────────────────────
    def test_03_flush_alert_summary_merges_duplicates(self):
        """
        故障注入：窗口内相同 fingerprint 告警触发多次（count>1），
        调用 flush_alert_summary() 后断言发送了合并汇总消息。
        """
        # 1) 发送 3 次相同 fingerprint 告警（同 level + 同 title → 同 dedup_key）
        title = "AI 穿帮过滤触发"
        alert_bot.send_alert("WARNING", title, "第1次", {})
        alert_bot.send_alert("WARNING", title, "第2次", {})
        alert_bot.send_alert("WARNING", title, "第3次", {})

        stats_after_send = self._stats()
        # 首条立即发送，后 2 条去重计数
        self.assertEqual(stats_after_send["sent"], 1, "首条应立即发送")
        self.assertEqual(stats_after_send["deduped"], 2, "后续 2 条应去重计数")

        # 2) 把计数器 first_ts 改到 5min 以前，模拟窗口过期
        now = time.time()
        for c in self.bot._counters.values():
            c["first_ts"] = now - _DEDUP_WINDOW - 1

        # 3) 调用 flush_alert_summary，应发送 1 条合并汇总
        tg_before = len(self.tg_calls)
        summary_count = alert_bot.flush_alert_summary()
        self.assertEqual(
            summary_count, 1, f"应发送 1 条汇总，实际 {summary_count}"
        )

        stats_after_flush = self._stats()
        # summarized 计数 +1
        self.assertEqual(
            stats_after_flush["summarized"], 1,
            f"summarized 应为 1，实际 {stats_after_flush['summarized']}",
        )
        # TG 多了一次调用（汇总消息）
        self.assertEqual(
            len(self.tg_calls), tg_before + 1, "flush 应触发 1 次 TG 调用"
        )
        # 汇总消息文本应包含"告警合并"字样
        self.assertIn(
            "告警合并", self.tg_calls[-1], "汇总消息应包含'告警合并'字样"
        )

    # ── 用例 4：限流保护 ─────────────────────────────────────
    def test_04_rate_limit_protection(self):
        """
        故障注入：1 分钟内快速发送 15 条不同 fingerprint 告警，
        断言仅发送 10 条（限流 10/min），其余 5 条被限流。
        """
        # 发送 15 条不同 fingerprint 告警（不同 title → 不同 dedup_key）
        for i in range(15):
            alert_bot.send_alert(
                "WARNING", f"测试告警类型_{i}", f"msg_{i}", {"idx": i}
            )

        stats = self._stats()
        # 限流上限 _RATE_LIMIT_MAX（10）条
        self.assertEqual(
            stats["sent"], _RATE_LIMIT_MAX,
            f"应仅发送 {_RATE_LIMIT_MAX} 条，实际 sent={stats['sent']}",
        )
        self.assertEqual(
            stats["throttled"], 5,
            f"应限流 5 条，实际 throttled={stats['throttled']}",
        )
        # TG 实际调用次数 = 10
        self.assertEqual(
            len(self.tg_calls), _RATE_LIMIT_MAX,
            f"TG 应被调用 {_RATE_LIMIT_MAX} 次，实际 {len(self.tg_calls)} 次",
        )

    # ── 用例 5：非级联告警正常发送 ────────────────────────────
    def test_05_non_cascade_alert_sent_normally(self):
        """
        故障注入：无根因活跃时发送 AI_LEAK_RETRY 告警（标题"AI 穿帮过滤触发"），
        断言正常发送，不被抑制。
        """
        ok = alert_bot.send_alert(
            "WARNING", "AI 穿帮过滤触发", "leak text", {"triggered": True}
        )
        self.assertTrue(ok, "非级联告警应发送成功")

        stats = self._stats()
        self.assertEqual(stats["sent"], 1, f"sent 应为 1，实际 {stats['sent']}")
        self.assertEqual(
            stats["suppressed"], 0, f"suppressed 应为 0，实际 {stats['suppressed']}"
        )
        self.assertEqual(
            len(self.tg_calls), 1, f"TG 应被调用 1 次，实际 {len(self.tg_calls)} 次"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
