# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  tests/load/locustfile.py  ·  Mory 助理三档梯度压测脚本（v5.26.0 阶段1-B）  ║
║                                                                            ║
║  目标：                                                                    ║
║    1. 提取 SQLite WriteQueue 背压黄金阈值                                  ║
║    2. 验证乐观锁冲突重试成功率                                             ║
║    3. 记录 WriteQueueFullError 首次抛出时的队列堆积长度                    ║
║                                                                            ║
║  三档梯度：                                                                ║
║    1 档（20 QPS）：只读为主，验证 Dashboard 读取性能                       ║
║    2 档（100 QPS）：读写混合，模拟 22:30 播报后高频互动                    ║
║    3 档（300 QPS）：极限压测，持续灌写直至 WriteQueueFullError             ║
║                                                                            ║
║  用法：                                                                    ║
║    # 安装 Locust（如未安装）                                               ║
║    pip install locust                                                      ║
║                                                                            ║
║    # 1 档压测（只读，20 QPS）                                              ║
║    locust -f tests/load/locustfile.py --host http://localhost:6616 \\      ║
║      --headless -u 20 -r 20 -t 60s --only-summary \\                       ║
║      --html logs/load_test_tier1.html --csv logs/load_test_tier1           ║
║                                                                            ║
║    # 2 档压测（读写混合，100 QPS）                                         ║
║    locust -f tests/load/locustfile.py --host http://localhost:6616 \\      ║
║      --headless -u 100 -r 50 -t 120s --only-summary \\                     ║
║      --html logs/load_test_tier2.html --csv logs/load_test_tier2           ║
║                                                                            ║
║    # 3 档极限压测（300 QPS，持续灌写）                                     ║
║    locust -f tests/load/locustfile.py --host http://localhost:6616 \\      ║
║      --headless -u 300 -r 100 -t 180s --only-summary \\                    ║
║      --html logs/load_test_tier3.html --csv logs/load_test_tier3           ║
║                                                                            ║
║  环境变量：                                                                ║
║    LOAD_TEST_TIER：1/2/3 指定压测档位（默认根据用户数自动判断）            ║
║    LOAD_TEST_WRITE_RATIO：写操作比例 0.0-1.0（默认 0.0 只读 / 0.3 混合）   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import random
import json
import time
from datetime import datetime

# Locust 导入（延迟到运行时，避免无 locust 时模块导入失败）
try:
    from locust import HttpUser, task, between, events
    _LOCUST_AVAILABLE = True
except ImportError:
    _LOCUST_AVAILABLE = False
    HttpUser = object  # 占位，允许模块导入
    def task(weight=1):
        def _decorator(func):
            return func
        return _decorator
    def between(a, b):
        return (a + b) / 2
    events = type("events", (), {"test_start": [], "test_stop": []})()


# ═══════════════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════════════

# 写操作比例（0.0=纯只读，0.3=30%写操作）
WRITE_RATIO = float(os.environ.get("LOAD_TEST_WRITE_RATIO", "0.0"))

# 模拟用户 ID 范围（用于写操作生成数据）
SIMULATED_UID_MIN = 100000
SIMULATED_UID_MAX = 999999

# 全局统计：记录 WriteQueueFullError 首次出现时间与指标
_write_queue_full_first_seen = {"ts": None, "stats": None}


# ═══════════════════════════════════════════════════════════════════════════
# 压测用户类
# ═══════════════════════════════════════════════════════════════════════════

class MoryDashboardUser(HttpUser):
    """模拟 Dashboard 访问用户

    根据用户数自动适配压测档位：
    - ≤20 用户：1 档（只读为主）
    - 21-100 用户：2 档（读写混合）
    - >100 用户：3 档（极限压测，高写比例）
    """

    # 请求间隔：0.5-1.5 秒（模拟真实用户行为）
    wait_time = between(0.5, 1.5)

    def on_start(self):
        """用户启动时初始化"""
        self.uid = random.randint(SIMULATED_UID_MIN, SIMULATED_UID_MAX)
        # 根据当前用户数动态调整写比例
        user_count = self.environment.runner.user_count if self.environment.runner else 1
        if user_count > 100:
            self._write_ratio = 0.5  # 3 档：50% 写操作
        elif user_count > 20:
            self._write_ratio = 0.3  # 2 档：30% 写操作
        else:
            self._write_ratio = WRITE_RATIO  # 1 档：按环境变量

    # ───────────────────────────────────────────────────────────────────────
    # 只读操作（1/2/3 档均执行）
    # ───────────────────────────────────────────────────────────────────────

    @task(10)
    def health_check(self):
        """健康检查（最轻量，验证服务存活）"""
        self.client.get("/api/health", name="GET /api/health")

    @task(8)
    def get_stats(self):
        """Dashboard 统计数据（只读，验证读取性能）"""
        self.client.get("/api/stats", name="GET /api/stats")

    @task(5)
    def get_engage_recent(self):
        """互动记录（只读，验证近期消息查询）"""
        self.client.get("/api/engage/recent?limit=20", name="GET /api/engage/recent")

    @task(3)
    def get_attribution_report(self):
        """归因报告（只读，验证聚合查询性能）"""
        self.client.get("/api/attribution/report?days=7", name="GET /api/attribution/report")

    @task(2)
    def get_scheduler_status(self):
        """调度状态（只读）"""
        self.client.get("/api/scheduler/status", name="GET /api/scheduler/status")

    @task(2)
    def get_db_migration_status(self):
        """DB 迁移监控（只读）"""
        self.client.get("/api/db-migration/status", name="GET /api/db-migration/status")

    @task(1)
    def get_bot_routing_list(self):
        """Bot 路由列表（只读）"""
        self.client.get("/api/bot-routing/list", name="GET /api/bot-routing/list")

    # ───────────────────────────────────────────────────────────────────────
    # 写操作（2/3 档执行，1 档跳过）
    # ───────────────────────────────────────────────────────────────────────

    @task(4)
    def write_engage_config(self):
        """更新互动配置（写操作，触发 WriteQueue）

        2/3 档执行，1 档跳过。
        """
        if self._write_ratio < 0.1:
            return  # 1 档跳过写操作

        if random.random() > self._write_ratio:
            return  # 按比例执行

        payload = {
            "enabled": True,
            "intensity": random.choice(["low", "medium", "high"]),
            "_load_test_uid": self.uid,
            "_load_test_ts": datetime.now().isoformat()
        }
        with self.client.post(
            "/api/engage/config",
            json=payload,
            name="POST /api/engage/config [write]",
            catch_response=True
        ) as resp:
            # 捕获 WriteQueueFullError 的 503 响应
            if resp.status_code == 503:
                _record_write_queue_full(resp)
                resp.failure("WriteQueueFullError")
            elif resp.status_code >= 500:
                resp.failure(f"Server error {resp.status_code}")

    @task(2)
    def write_rbac_request(self):
        """提交 RBAC 权限申请（写操作，触发 WriteQueue）

        2/3 档执行，验证审批流写入性能。
        """
        if self._write_ratio < 0.1:
            return

        if random.random() > self._write_ratio:
            return

        payload = {
            "target_user_id": self.uid,
            "requested_role": "viewer",
            "reason": f"load_test_{int(time.time())}"
        }
        with self.client.post(
            "/api/rbac/request",
            json=payload,
            name="POST /api/rbac/request [write]",
            catch_response=True
        ) as resp:
            if resp.status_code == 503:
                _record_write_queue_full(resp)
                resp.failure("WriteQueueFullError")
            elif resp.status_code >= 500:
                resp.failure(f"Server error {resp.status_code}")


# ═══════════════════════════════════════════════════════════════════════════
# WriteQueueFullError 记录
# ═══════════════════════════════════════════════════════════════════════════

def _record_write_queue_full(response):
    """记录 WriteQueueFullError 首次出现的时间与上下文"""
    global _write_queue_full_first_seen
    if _write_queue_full_first_seen["ts"] is None:
        _write_queue_full_first_seen["ts"] = time.time()
        _write_queue_full_first_seen["stats"] = {
            "first_seen_at": datetime.now().isoformat(),
            "status_code": response.status_code,
            "response_body": response.text[:500] if response.text else "",
        }
        # 写入日志文件供分析脚本读取
        try:
            log_dir = "logs"
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "load_test_wq_full_first_seen.json"), "w", encoding="utf-8") as f:
                json.dump(_write_queue_full_first_seen["stats"], f, ensure_ascii=False, indent=2)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# Locust 事件钩子
# ═══════════════════════════════════════════════════════════════════════════

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """压测开始时输出配置信息"""
    print("\n" + "=" * 70)
    print("Mory 助理压测启动")
    print("=" * 70)
    print(f"目标主机: {environment.host}")
    print(f"用户数: {environment.parsed_options.num_users}")
    print(f"孵化速率: {environment.parsed_options.spawn_rate}/s")
    print(f"持续时间: {environment.parsed_options.run_time}")
    print(f"写操作比例: {WRITE_RATIO}")
    print("=" * 70 + "\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """压测结束时输出 WriteQueueFullError 首次出现信息"""
    print("\n" + "=" * 70)
    print("压测结束 - 关键指标摘要")
    print("=" * 70)

    if _write_queue_full_first_seen["ts"]:
        stats = _write_queue_full_first_seen["stats"]
        print(f"⚠️  WriteQueueFullError 首次出现: {stats['first_seen_at']}")
        print(f"   响应状态码: {stats['status_code']}")
        print(f"   响应体: {stats['response_body'][:200]}")
    else:
        print("✅ 未触发 WriteQueueFullError")

    # 输出统计摘要
    if environment.stats:
        stats = environment.stats
        print(f"\n总请求数: {stats.total.num_requests}")
        print(f"失败请求数: {stats.total.num_failures}")
        print(f"平均响应时间: {stats.total.avg_response_time:.2f} ms")
        print(f"P95 响应时间: {stats.total.get_response_time_percentile(0.95):.2f} ms")
        print(f"P99 响应时间: {stats.total.get_response_time_percentile(0.99):.2f} ms")

    print("=" * 70 + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# 模块入口（支持直接 python 运行检查依赖）
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not _LOCUST_AVAILABLE:
        print("❌ Locust 未安装，请先安装：")
        print("   pip install locust")
        print("\n安装后使用以下命令运行压测：")
        print("   locust -f tests/load/locustfile.py --host http://localhost:6616 --headless -u 20 -r 20 -t 60s")
    else:
        print("✅ Locust 已安装，可用以下命令运行压测：")
        print("\n# 1 档（只读，20 QPS）:")
        print("locust -f tests/load/locustfile.py --host http://localhost:6616 \\")
        print("  --headless -u 20 -r 20 -t 60s --only-summary \\")
        print("  --html logs/load_test_tier1.html --csv logs/load_test_tier1")
        print("\n# 2 档（读写混合，100 QPS）:")
        print("locust -f tests/load/locustfile.py --host http://localhost:6616 \\")
        print("  --headless -u 100 -r 50 -t 120s --only-summary \\")
        print("  --html logs/load_test_tier2.html --csv logs/load_test_tier2")
        print("\n# 3 档（极限，300 QPS）:")
        print("locust -f tests/load/locustfile.py --host http://localhost:6616 \\")
        print("  --headless -u 300 -r 100 -t 180s --only-summary \\")
        print("  --html logs/load_test_tier3.html --csv logs/load_test_tier3")
