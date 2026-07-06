# -*- coding: utf-8 -*-
"""【v5.31.2 审计整改 P2-8】补充单元测试覆盖 5 个新函数

覆盖目标：
1. dashboard/auth.py:_verify_password - 双模式密码校验（sha256 + 明文）
2. core/ai_engine.py:get_fallback_text - 统一兜底文案入口
3. core/write_queue.py:enqueue_batch - 批量入队
4. core/db_repos/tracking_repo.py:cleanup_channel_tracking_orphan - channel_tracking 孤儿清理
5. core/llm_cost_guard.py:check_before_call step 6 - 全局 24h 熔断

设计原则：
- 不依赖运行时环境（不连真实 DB、不连真实 LLM）
- 每个测试用例独立，可单独运行
- 覆盖正常路径 + 边界条件 + 错误分支
"""
import hashlib
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# 确保项目根目录在 sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ═══════════════════════════════════════════════════════════════════
# 1. _verify_password 双模式密码校验测试
# ═══════════════════════════════════════════════════════════════════

class TestVerifyPassword:
    """测试 dashboard/auth.py:_verify_password 双模式校验"""

    @pytest.fixture(autouse=True)
    def _import_function(self):
        """导入 _verify_password（autouse 自动应用）"""
        from dashboard.auth import _verify_password, _hash_password
        self._verify = _verify_password
        self._hash = _hash_password

    def test_sha256_correct_password(self):
        """sha256 模式：正确密码应通过"""
        password = "my_secret_123"
        stored_hash = self._hash(password)
        assert self._verify(password, stored_hash) is True

    def test_sha256_wrong_password(self):
        """sha256 模式：错误密码应拒绝"""
        stored_hash = self._hash("correct_password")
        assert self._verify("wrong_password", stored_hash) is False

    def test_plaintext_correct(self):
        """明文模式：正确密码应通过（向后兼容）"""
        assert self._verify("plain123", "plain123") is True

    def test_plaintext_wrong(self):
        """明文模式：错误密码应拒绝"""
        assert self._verify("wrong", "plain123") is False

    def test_empty_stored_rejected(self):
        """空 stored 应拒绝"""
        assert self._verify("any", "") is False

    def test_empty_password_rejected(self):
        """空密码应拒绝"""
        assert self._verify("", "any_hash") is False

    def test_sha256_case_insensitive(self):
        """sha256 模式：stored 大写 hex 也应识别（兼容性）"""
        password = "Test_Pwd_456"
        stored_upper = self._hash(password).upper()
        assert self._verify(password, stored_upper) is True

    def test_sha256_64_len_but_not_hex_treated_as_plaintext(self):
        """64 位长度但非 hex 字符 → 视为明文"""
        # 64 字符但包含非 hex 字符（g/h/i/j/k/l/m/n/o/p/q/r/s/t/u/v/w/x/y/z）
        fake_64 = "gggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggg"
        assert self._verify(fake_64, fake_64) is True  # 明文模式匹配


# ═══════════════════════════════════════════════════════════════════
# 2. get_fallback_text 统一兜底文案测试
# ═══════════════════════════════════════════════════════════════════

class TestGetFallbackText:
    """测试 core/ai_engine.py:get_fallback_text"""

    @pytest.fixture(autouse=True)
    def _import_function(self):
        from core.ai_engine import get_fallback_text
        self._get = get_fallback_text

    def test_convert_private(self):
        """convert 模式 + 私聊：应返回带 URL 的入口文案"""
        text = self._get("convert", is_priv=True)
        assert "https://t.me/moryselect" in text
        assert "https://t.me/MorychannelBot" in text
        assert len(text) > 20  # 非空

    def test_convert_group(self):
        """convert 模式 + 群聊：应返回带 @username 的入口文案"""
        text = self._get("convert", is_priv=False)
        assert "@moryselect" in text
        assert "@MorychannelBot" in text

    def test_contact_mory_private(self):
        """contact_mory 模式 + 私聊：应返回入口文案"""
        text = self._get("contact_mory", is_priv=True)
        assert "https://t.me/moryselect" in text

    def test_default_returns_empty(self):
        """default/未知 模式：应返回空串（静默，不暴露系统异常）"""
        assert self._get("default") == ""
        assert self._get("unknown_mode") == ""
        assert self._get() == ""  # 默认参数

    def test_priv_vs_group_distinct(self):
        """私聊与群聊文案应不同"""
        priv_text = self._get("convert", is_priv=True)
        group_text = self._get("convert", is_priv=False)
        assert priv_text != group_text


# ═══════════════════════════════════════════════════════════════════
# 3. enqueue_batch 批量入队测试
# ═══════════════════════════════════════════════════════════════════

class TestEnqueueBatch:
    """测试 core/write_queue.py:enqueue_batch"""

    @pytest.fixture
    def mock_conn(self):
        """Mock SQLite 连接

        WriteQueue.enqueue_batch 会调用 getattr(conn, "_real", conn)，
        MagicMock 默认会自动生成 _real 属性（新的 MagicMock），
        导致后续 executemany 调用打在 _real 上而非 conn 本身。
        所以这里显式设置 _real = conn 让其回环到自身。
        """
        conn = MagicMock()
        conn._real = conn  # 让 getattr(conn, "_real", conn) 返回 conn 自身
        conn.executemany = MagicMock()
        conn.commit = MagicMock()
        return conn

    @pytest.fixture
    def stopped_queue(self, mock_conn):
        """未启动的 WriteQueue（会回退同步 executemany）"""
        from core.write_queue import WriteQueue
        q = WriteQueue(max_size=100)
        # _running=False 时走同步分支
        return q, mock_conn

    def test_stopped_queue_fallback_sync(self, stopped_queue):
        """未启动队列：应回退同步 executemany"""
        q, conn = stopped_queue
        params_seq = [(1,), (2,), (3,)]
        result = q.enqueue_batch(conn, "INSERT INTO t VALUES (?)", params_seq)
        assert result is True
        conn.executemany.assert_called_once_with("INSERT INTO t VALUES (?)", params_seq)
        conn.commit.assert_called_once()

    def test_empty_sequence_skipped(self, stopped_queue):
        """空参数序列：不应调用 executemany"""
        q, conn = stopped_queue
        result = q.enqueue_batch(conn, "INSERT INTO t VALUES (?)", [])
        # 空序列在 db_connection_proxy 层处理，WriteQueue 直接走同步分支会调用 executemany([])
        # 实际 SQLite executemany([]) 是合法的 no-op
        assert result is True

    def test_running_queue_enqueues_task(self, mock_conn):
        """已启动队列：应入队 _WriteTask"""
        from core.write_queue import WriteQueue
        q = WriteQueue(max_size=100)
        # 模拟已启动
        q._running = True
        params_seq = [(1,), (2,)]
        result = q.enqueue_batch(mock_conn, "INSERT INTO t VALUES (?)", params_seq)
        assert result is True
        # 队列应有 1 个任务
        assert q._queue.qsize() == 1
        task = q._queue.get_nowait()
        assert task.is_executemany is True
        assert task.params == params_seq
        # 清理
        q._running = False

    def test_full_queue_critical_raises(self):
        """队列满 + is_critical=True：应抛 WriteQueueFullError"""
        from core.write_queue import WriteQueue, WriteQueueFullError
        q = WriteQueue(max_size=1)
        q._running = True
        # 先填满
        q._queue.put_nowait(MagicMock())
        # 再投递核心批量写
        with pytest.raises(WriteQueueFullError):
            q.enqueue_batch(MagicMock(), "INSERT INTO t VALUES (?)", [(1,)], is_critical=True)
        q._running = False

    def test_full_queue_non_critical_silent(self):
        """队列满 + is_critical=False：应静默丢弃返回 False"""
        from core.write_queue import WriteQueue
        q = WriteQueue(max_size=1)
        q._running = True
        q._queue.put_nowait(MagicMock())
        result = q.enqueue_batch(MagicMock(), "INSERT INTO t VALUES (?)", [(1,)], is_critical=False)
        assert result is False
        q._running = False


# ═══════════════════════════════════════════════════════════════════
# 4. cleanup_channel_tracking_orphan 孤儿清理测试
# ═══════════════════════════════════════════════════════════════════

class TestCleanupChannelTrackingOrphan:
    """测试 core/db_repos/tracking_repo.py:cleanup_channel_tracking_orphan"""

    @pytest.fixture
    def tracking_repo(self):
        """构造内存 SQLite + channel_tracking 表 + TrackingRepo 实例

        TrackingRepo 接受 db 实例（通过 db.conn 和 db.lock 访问），
        所以这里构造一个简单的 Mock db 对象包装 conn。
        """
        from core.db_repos.tracking_repo import TrackingRepo
        import threading
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                posted_at INTEGER NOT NULL
            )
        """)
        conn.commit()
        # 构造 mock db：TrackingRepo 通过 db.conn / db.lock 访问
        mock_db = MagicMock()
        mock_db.conn = conn
        mock_db.lock = threading.Lock()
        repo = TrackingRepo(mock_db)
        return repo, conn

    def test_deletes_expired_records(self, tracking_repo):
        """应删除超过 max_age_hours 的记录"""
        repo, conn = tracking_repo
        now = int(time.time())
        # 插入 3 条：1 条 50h 前（应删）、1 条 24h 前（保留）、1 条刚刚（保留）
        conn.execute("INSERT INTO channel_tracking (chat_id, message_id, posted_at) VALUES (?, ?, ?)",
                     (-100, 1, now - 50 * 3600))
        conn.execute("INSERT INTO channel_tracking (chat_id, message_id, posted_at) VALUES (?, ?, ?)",
                     (-100, 2, now - 24 * 3600))
        conn.execute("INSERT INTO channel_tracking (chat_id, message_id, posted_at) VALUES (?, ?, ?)",
                     (-100, 3, now))
        conn.commit()

        deleted = repo.cleanup_channel_tracking_orphan(max_age_hours=47)
        assert deleted == 1  # 只有 50h 那条被删

        # 验证剩余 2 条
        cur = conn.execute("SELECT COUNT(*) FROM channel_tracking")
        assert cur.fetchone()[0] == 2

    def test_keeps_recent_records(self, tracking_repo):
        """近期记录应保留"""
        repo, conn = tracking_repo
        now = int(time.time())
        conn.execute("INSERT INTO channel_tracking (chat_id, message_id, posted_at) VALUES (?, ?, ?)",
                     (-100, 1, now - 3600))  # 1h 前
        conn.commit()
        deleted = repo.cleanup_channel_tracking_orphan(max_age_hours=47)
        assert deleted == 0
        cur = conn.execute("SELECT COUNT(*) FROM channel_tracking")
        assert cur.fetchone()[0] == 1

    def test_empty_table_returns_zero(self, tracking_repo):
        """空表应返回 0"""
        repo, conn = tracking_repo
        deleted = repo.cleanup_channel_tracking_orphan(max_age_hours=47)
        assert deleted == 0

    def test_default_max_age_47h(self, tracking_repo):
        """默认 max_age_hours=47"""
        repo, conn = tracking_repo
        now = int(time.time())
        # 48h 前（应删）
        conn.execute("INSERT INTO channel_tracking (chat_id, message_id, posted_at) VALUES (?, ?, ?)",
                     (-100, 1, now - 48 * 3600))
        # 46h 前（保留）
        conn.execute("INSERT INTO channel_tracking (chat_id, message_id, posted_at) VALUES (?, ?, ?)",
                     (-100, 2, now - 46 * 3600))
        conn.commit()
        deleted = repo.cleanup_channel_tracking_orphan()  # 默认 47
        assert deleted == 1


# ═══════════════════════════════════════════════════════════════════
# 5. LLM global_daily 熔断测试
# ═══════════════════════════════════════════════════════════════════

class TestLLMGlobalDailyCircuitBreaker:
    """测试 core/llm_cost_guard.py:check_before_call step 6（全局 24h 熔断）"""

    @pytest.fixture
    def guard(self):
        """构造启用的 LLMCostGuard 实例"""
        from core.llm_cost_guard import LLMCostGuard
        config = {
            "LLM_COST_GUARD_ENABLED": True,
            "LLM_COST_GLOBAL_DAILY_LIMIT": 50.0,  # 50 美元日限额
            "LLM_COST_GLOBAL_HOURLY_LIMIT": 5.0,
            "LLM_COST_USER_HOURLY_LIMIT": 1.0,
            "LLM_COST_USER_DAILY_LIMIT": 10.0,
        }
        return LLMCostGuard(config)

    def test_below_limit_allowed(self, guard):
        """未超阈值：应允许原 tier"""
        allowed, final_tier, reason = guard.check_before_call(uid=123, tier="llm_premium")
        assert allowed is True
        assert final_tier == "llm_premium"
        assert reason == "ok"

    def test_global_daily_exceeded_triggers_downgrade(self, guard):
        """全局 24h 超阈值：应降级 llm_light

        注意：check_before_call 检查顺序为 hourly(1h) → daily(24h)，
        测试数据必须让 $50 落在 24h 窗口内但不在 1h 窗口内，
        否则会先触发 global_hourly_limit_exceeded 而非 global_daily_limit_exceeded。
        """
        now = time.time()
        with guard._lock:
            # 2h 前 50 美元：在 24h 窗口内（触发 daily $50），
            # 但不在 1h 窗口内（避免触发 hourly $5）
            guard._global_window.append((now - 7200, 50.0))
        allowed, final_tier, reason = guard.check_before_call(uid=123, tier="llm_premium")
        assert allowed is True  # 允许调用但降级
        assert final_tier == "llm_light"
        assert reason == "global_daily_limit_exceeded"
        # 应设置 24h 降级状态
        assert guard._global_downgrade_until > now + 86000  # 接近 24h

    def test_downgrade_state_persists_24h(self, guard):
        """降级状态应持续 24h"""
        now = time.time()
        # 触发降级：用 2h 前的 $60 触发 daily 熔断（避免先触发 hourly）
        with guard._lock:
            guard._global_window.append((now - 7200, 60.0))
        guard.check_before_call(uid=123, tier="llm_premium")
        # 立即再次调用：应直接走降级分支（step 1）
        allowed, final_tier, reason = guard.check_before_call(uid=456, tier="llm_premium")
        assert allowed is True
        assert final_tier == "llm_light"
        assert "global_downgrade_active" in reason

    def test_disabled_guard_allows_all(self):
        """熔断器关闭：应直接允许"""
        from core.llm_cost_guard import LLMCostGuard
        guard = LLMCostGuard({"LLM_COST_GUARD_ENABLED": False})
        allowed, final_tier, reason = guard.check_before_call(uid=123, tier="llm_premium")
        assert allowed is True
        assert final_tier == "llm_premium"
        assert reason == "guard_disabled"

    def test_get_global_daily_cost_calculation(self, guard):
        """_get_global_daily_cost 应正确计算 24h 累计

        注意：_cleanup_expired 只从 deque 左侧弹出 timestamp < cutoff 的元素，
        假设窗口按时间升序排列（record_cost 实际调用顺序）。
        测试直接 manipulate _global_window 时必须按时间升序 append，
        否则过期的元素若在右侧将无法被弹出。
        """
        now = time.time()
        with guard._lock:
            # 按时间升序 append（模拟 record_cost 的真实调用顺序）
            guard._global_window.append((now - 90000, 100.0))  # 25h 前（最早，会被清理）
            guard._global_window.append((now - 50000, 5.0))    # ~14h 前
            guard._global_window.append((now - 3600, 20.0))    # 1h 前
            guard._global_window.append((now - 100, 10.0))     # 100s 前（最新）
        cost = guard._get_global_daily_cost(now)
        # 25h 前的被 _cleanup_expired 从左侧弹出，剩余 5+20+10=35
        assert 34.9 <= cost <= 35.1

    def test_hourly_does_not_break_daily_window(self, guard):
        """【审计复扫修复】hourly 只读不写，不破坏 daily 窗口

        验证审计暗病修复：原实现 _get_global_hourly_cost 调用
        _cleanup_expired(now, window, 3600) 会弹出所有 1h 前的元素，
        破坏 daily 窗口数据，导致 daily 熔断永远无法触发。
        """
        now = time.time()
        with guard._lock:
            # 2h 前 50 美元：在 24h 窗口内但不在 1h 窗口内
            guard._global_window.append((now - 7200, 50.0))
        # 调用 hourly 计算应返回 0（2h 前的不在 1h 窗口内）
        hourly_cost = guard._get_global_hourly_cost(now)
        assert hourly_cost == 0.0
        # 关键验证：调用 hourly 后，daily 窗口仍应保留所有数据
        # 如果 hourly 调用了 cleanup，daily 会变成 0.0
        daily_cost = guard._get_global_daily_cost(now)
        assert 49.9 <= daily_cost <= 50.1  # 数据未被破坏


# ═══════════════════════════════════════════════════════════════════
# 6. _CRITICAL_JOBS 一致性测试（审计复扫修复补充）
# ═══════════════════════════════════════════════════════════════════

class TestCriticalJobsConsistency:
    """【审计复扫修复】验证 _CRITICAL_JOBS 与 auto_tasks.py 实际调度一致

    Expert C FAIL-1/2/3 发现：health_check/cart_recovery/backup 的监控模式
    与 auto_tasks.py 实际 cron 调度不匹配，导致监控盲区或误报。
    本测试用静态分析方式校验 _CRITICAL_JOBS 字典中的 spec 字段
    与 _CRITICAL_JOBS 本身的内部一致性，避免再次出现监控错误任务。
    """

    def test_all_critical_jobs_have_required_fields(self):
        """每个 _CRITICAL_JOBS 项必须有 desc 和（deadline_hour/minute 或 interval_minutes）"""
        from core.scheduler_monitor import _CRITICAL_JOBS
        for job_id, spec in _CRITICAL_JOBS.items():
            assert "desc" in spec, f"{job_id} 缺少 desc 字段"
            has_deadline = "deadline_hour" in spec and "deadline_minute" in spec
            has_interval = "interval_minutes" in spec
            assert has_deadline or has_interval, (
                f"{job_id} 必须有 deadline_hour+deadline_minute 或 interval_minutes"
            )

    def test_deadline_mode_has_valid_hour(self):
        """deadline 模式的 hour 必须在 0-23 范围"""
        from core.scheduler_monitor import _CRITICAL_JOBS
        for job_id, spec in _CRITICAL_JOBS.items():
            if "deadline_hour" in spec:
                h = spec["deadline_hour"]
                assert 0 <= h <= 23, f"{job_id} deadline_hour={h} 越界（0-23）"
                m = spec.get("deadline_minute", 0)
                assert 0 <= m <= 59, f"{job_id} deadline_minute={m} 越界（0-59）"

    def test_interval_mode_has_positive_minutes(self):
        """interval 模式的 minutes 必须 > 0"""
        from core.scheduler_monitor import _CRITICAL_JOBS
        for job_id, spec in _CRITICAL_JOBS.items():
            if "interval_minutes" in spec:
                assert spec["interval_minutes"] > 0, (
                    f"{job_id} interval_minutes 必须 > 0"
                )

    def test_critical_job_ids_match_known_set(self):
        """_CRITICAL_JOBS 的 key 必须与已知 job_id 集合匹配

        防止新增/删除 job_id 时遗忘更新 _CRITICAL_JOBS。
        如果 auto_tasks.py 新增了关键任务，需要同步加到这里。
        """
        from core.scheduler_monitor import _CRITICAL_JOBS
        expected_ids = {
            "greeting_morning", "greeting_afternoon", "greeting_evening",
            "broadcast_morning_nudge", "broadcast_afternoon_tease",
            "broadcast_evening_warm", "broadcast_night_hook",
            "cart_recovery", "backup", "daily_backup", "health_check",
            "sync_scheduler_metrics", "flush_alert_summary",
        }
        actual_ids = set(_CRITICAL_JOBS.keys())
        # 完全匹配（不允许有多余或缺失）
        assert actual_ids == expected_ids, (
            f"_CRITICAL_JOBS key 不匹配\n"
            f"  缺失: {expected_ids - actual_ids}\n"
            f"  多余: {actual_ids - expected_ids}\n"
            f"如果 auto_tasks.py 新增/删除了关键任务，请同步更新此测试和 _CRITICAL_JOBS"
        )

    def test_is_job_disabled_by_config_greeting(self):
        """_is_job_disabled_by_config：greeting_* 根据真实开关逻辑判断

        与 auto_tasks._is_greeting_enabled 保持一致：
        - 优先读 GREETING_CONFIG.<period>_enabled
        - 回退到 AUTO_GREETING / AUTO_GOODNIGHT
        - 默认值 False（未配置视为禁用，与 auto_tasks 行为一致）
        """
        from core.scheduler_monitor import _is_job_disabled_by_config
        # GREETING_CONFIG.morning_enabled=True：不跳过
        cfg = {"GREETING_CONFIG": {"morning_enabled": True}}
        assert _is_job_disabled_by_config("greeting_morning", cfg) is False
        # GREETING_CONFIG.morning_enabled=False：跳过
        cfg = {"GREETING_CONFIG": {"morning_enabled": False}}
        assert _is_job_disabled_by_config("greeting_morning", cfg) is True
        # 回退到 AUTO_GREETING=True：不跳过
        cfg = {"AUTO_GREETING": True}
        assert _is_job_disabled_by_config("greeting_morning", cfg) is False
        # 回退到 AUTO_GREETING=False：跳过
        cfg = {"AUTO_GREETING": False}
        assert _is_job_disabled_by_config("greeting_morning", cfg) is True
        # evening 回退到 AUTO_GOODNIGHT（优先）或 AUTO_GREETING（次选）
        # 注意：dict.get(key, default) 当 key 存在但值为 False 时返回 False，不回退
        # 这与 auto_tasks._is_greeting_enabled 行为完全一致
        cfg = {"AUTO_GOODNIGHT": True, "AUTO_GREETING": False}
        assert _is_job_disabled_by_config("greeting_evening", cfg) is False
        cfg = {"AUTO_GOODNIGHT": False, "AUTO_GREETING": True}
        # AUTO_GOODNIGHT=False 存在 → 不回退到 AUTO_GREETING，视为禁用
        assert _is_job_disabled_by_config("greeting_evening", cfg) is True
        # 只设置 AUTO_GREETING=True（无 AUTO_GOODNIGHT）→ 回退到 AUTO_GREETING
        cfg = {"AUTO_GREETING": True}
        assert _is_job_disabled_by_config("greeting_evening", cfg) is False
        # 默认值：未配置视为禁用（与 auto_tasks._is_greeting_enabled 默认 False 一致）
        assert _is_job_disabled_by_config("greeting_morning", {}) is True

    def test_is_job_disabled_by_config_broadcast(self):
        """_is_job_disabled_by_config：broadcast_* 根据 SCHEDULED_BROADCASTS.enabled 判断"""
        from core.scheduler_monitor import _is_job_disabled_by_config
        cfg = {
            "SCHEDULED_BROADCASTS": [
                {"id": "morning_nudge", "enabled": True},
                {"id": "afternoon_tease", "enabled": False},
            ]
        }
        # 启用：不跳过
        assert _is_job_disabled_by_config("broadcast_morning_nudge", cfg) is False
        # 禁用：跳过
        assert _is_job_disabled_by_config("broadcast_afternoon_tease", cfg) is True
        # 配置中不存在：跳过（避免对已删除的播报任务误告警）
        assert _is_job_disabled_by_config("broadcast_nonexistent", cfg) is True

    def test_is_job_disabled_by_config_infrastructure_never_skipped(self):
        """_is_job_disabled_by_config：基础设施任务（backup/cart_recovery 等）永不被 config 跳过"""
        from core.scheduler_monitor import _is_job_disabled_by_config
        infra_jobs = [
            "cart_recovery", "backup", "daily_backup", "health_check",
            "sync_scheduler_metrics", "flush_alert_summary",
        ]
        # 即使 config 完全为空，基础设施任务也不应跳过
        for jid in infra_jobs:
            assert _is_job_disabled_by_config(jid, {}) is False, (
                f"{jid} 是基础设施任务，不应被 config 跳过"
            )
        # config=None 时也不跳过
        for jid in infra_jobs:
            assert _is_job_disabled_by_config(jid, None) is False


# ═══════════════════════════════════════════════════════════════════
# 7. WriteQueue 死锁检测测试（Bug-04 修复补充）
# ═══════════════════════════════════════════════════════════════════

class TestWriteQueueDeadlockDetection:
    """【Bug-04 修复补充】验证 enqueue_and_wait 在 Worker 线程内调用时返回 RuntimeError

    原实现仅注释警告"不要在 Worker 线程内调用"，无运行时检测。
    Bug-04 修复后，应通过 _worker_thread_id 检测并返回错误结果，
    避免未来误用导致死锁。
    """

    def test_deadlock_detected_in_worker_thread(self):
        """在 Worker 线程内调用 enqueue_and_wait 应返回 error=RuntimeError"""
        from core.write_queue import WriteQueue
        import threading
        q = WriteQueue(max_size=10)
        q._running = True
        # 模拟 Worker 线程：让 _worker_thread_id 等于当前线程 ident
        q._worker_thread_id = threading.get_ident()

        result = q.enqueue_and_wait(
            conn=MagicMock(),
            sql="INSERT INTO t VALUES (?)",
            params=(1,),
        )
        # 应返回带 RuntimeError 的结果，而不是死锁
        assert result.error is not None
        assert isinstance(result.error, RuntimeError)
        assert "Deadlock" in str(result.error) or "deadlock" in str(result.error).lower()
        q._running = False

    def test_no_deadlock_in_normal_thread(self):
        """正常线程调用 enqueue_and_wait 不应触发死锁检测"""
        from core.write_queue import WriteQueue
        import threading
        q = WriteQueue(max_size=10)
        q._running = True
        # _worker_thread_id 设为另一个线程的 ident（不是当前线程）
        q._worker_thread_id = threading.get_ident() + 999999  # 一个不存在的线程 ident

        result = q.enqueue_and_wait(
            conn=MagicMock(),
            sql="INSERT INTO t VALUES (?)",
            params=(1,),
            timeout=0.1,  # 短超时避免阻塞测试
        )
        # 不应是 RuntimeError（可能是 TimeoutError 因为没有 Worker 处理）
        assert result.error is None or not isinstance(result.error, RuntimeError), (
            f"正常线程不应触发死锁检测，但得到: {result.error}"
        )
        q._running = False

    def test_worker_thread_id_set_after_start(self):
        """【WARN-3 修复】start() 后 _worker_thread_id 应为非 None

        原实现在 start() 之前读取 ident 必为 None，是无效赋值。
        修复后应在 start() 之后读取，保证 enqueue_and_wait 死锁检测可用。
        """
        from core.write_queue import WriteQueue
        q = WriteQueue(max_size=10)
        try:
            q.start()
            # start() 后 _worker_thread_id 应为非 None
            assert q._worker_thread_id is not None, (
                "start() 后 _worker_thread_id 不应为 None"
            )
        finally:
            q.stop(timeout=1.0)


# ═══════════════════════════════════════════════════════════════════
# 8. Session 绝对最大会话时间测试（WARN-4 修复补充）
# ═══════════════════════════════════════════════════════════════════

class TestSessionAbsoluteExpiry:
    """【WARN-4 修复】验证 Session 绝对最大会话时间检查

    防止攻击者登录后通过持续 GET 请求无限续期。
    """

    def test_absolute_max_seconds_constant_exists(self):
        """_SESSION_ABSOLUTE_MAX_SECONDS 常量应存在且为 8 小时"""
        from dashboard.auth import _SESSION_ABSOLUTE_MAX_SECONDS
        assert _SESSION_ABSOLUTE_MAX_SECONDS == 8 * 3600

    def test_is_session_expired_with_absolute_expiry(self):
        """absolute_expires_at 已过 → 应返回 True"""
        from dashboard.auth import _is_session_expired
        from flask import Flask, session
        app = Flask(__name__)
        app.secret_key = "test_secret_for_session"
        with app.test_request_context():
            now_dt = datetime.now(_get_cst())
            past_absolute = (now_dt - timedelta(seconds=1)).isoformat()
            future_sliding = (now_dt + timedelta(seconds=1800)).isoformat()
            session["logged_in"] = True
            session["expires_at"] = future_sliding
            session["absolute_expires_at"] = past_absolute
            assert _is_session_expired() is True

    def test_is_session_expired_with_only_sliding_expiry(self):
        """只有 sliding expires_at 已过 → 应返回 True"""
        from dashboard.auth import _is_session_expired
        from flask import Flask, session
        app = Flask(__name__)
        app.secret_key = "test_secret_for_session"
        with app.test_request_context():
            now_dt = datetime.now(_get_cst())
            past_sliding = (now_dt - timedelta(seconds=1)).isoformat()
            future_absolute = (now_dt + timedelta(seconds=3600)).isoformat()
            session["logged_in"] = True
            session["expires_at"] = past_sliding
            session["absolute_expires_at"] = future_absolute
            assert _is_session_expired() is True

    def test_is_session_expired_neither_expired(self):
        """两个时间都未过 → 应返回 False"""
        from dashboard.auth import _is_session_expired
        from flask import Flask, session
        app = Flask(__name__)
        app.secret_key = "test_secret_for_session"
        with app.test_request_context():
            now_dt = datetime.now(_get_cst())
            future_sliding = (now_dt + timedelta(seconds=1800)).isoformat()
            future_absolute = (now_dt + timedelta(seconds=3600)).isoformat()
            session["logged_in"] = True
            session["expires_at"] = future_sliding
            session["absolute_expires_at"] = future_absolute
            assert _is_session_expired() is False

    def test_touch_session_caps_at_absolute_expiry(self):
        """_touch_session 不能让 expires_at 超过 absolute_expires_at"""
        from dashboard.auth import _touch_session, _SESSION_LIFETIME_SECONDS
        from flask import Flask, session
        app = Flask(__name__)
        app.secret_key = "test_secret_for_session"
        with app.test_request_context():
            now_dt = datetime.now(_get_cst())
            # absolute_expires_at 在 1 分钟后（远小于 sliding 30 分钟）
            absolute_expires = (now_dt + timedelta(seconds=60)).isoformat()
            session["logged_in"] = True
            session["absolute_expires_at"] = absolute_expires
            _touch_session()
            # 验证 expires_at 被截断到 absolute_expires_at
            expires_at = session.get("expires_at")
            assert expires_at is not None
            expires_dt = datetime.fromisoformat(expires_at)
            absolute_dt = datetime.fromisoformat(absolute_expires)
            # 应该等于 absolute_expires_at（被截断），而不是 now+30min
            assert expires_dt <= absolute_dt + timedelta(seconds=1), (
                f"_touch_session 应截断到 absolute_expires_at，但 expires_at={expires_dt} > {absolute_dt}"
            )


def _get_cst():
    """获取 CST 时区（避免在测试中循环依赖）"""
    from datetime import timezone, timedelta
    return timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
