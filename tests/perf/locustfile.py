# -*- coding: utf-8 -*-
"""[TRAE SOLO CN] v5.25.0 性能基准压测脚本

基于 Locust 模拟高并发请求，摸底系统性能。
支持两种压测场景：
  1. Webhook 场景：POST 模拟 Telegram Update（需配置 Webhook 模式）
  2. Dashboard 场景：GET Dashboard API 读接口（推荐，项目默认 Flask 端点）

仅本地开发环境使用，禁止对生产 VPS 压测。

运行：
  # Dashboard API 压测（推荐，无需 Webhook 配置）
  locust -f tests/perf/locustfile.py --host=http://localhost:6616

  # Webhook 压测（需先配置 Webhook 模式）
  PERF_SCENE=webhook locust -f tests/perf/locustfile.py --host=http://localhost:6616

  # 无头模式三档梯度压测
  locust -f tests/perf/locustfile.py --host=http://localhost:6616 --headless -u 20 -r 5 --run-time 60s   # 轻载
  locust -f tests/perf/locustfile.py --host=http://localhost:6616 --headless -u 100 -r 10 --run-time 60s  # 中载
  locust -f tests/perf/locustfile.py --host=http://localhost:6616 --headless -u 300 -r 20 --run-time 60s  # 极限

依赖：pip install locust（可选依赖，未安装时给出友好提示）
"""
import os
import sys
import time
import random
import threading

# ── Locust 可选依赖检查 ──
try:
    from locust import HttpUser, task, between, events
except ImportError:
    print("[ERROR] 未安装 locust，请执行：pip install locust")
    print("        安装后运行：locust -f tests/perf/locustfile.py --host=http://localhost:6616")
    sys.exit(1)

# ── 参数化配置（环境变量）──
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook/")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
USER_ID_START = int(os.environ.get("PERF_USER_ID_START", "100000"))
# 压测场景：dashboard（默认，压 Dashboard API）/ webhook（压 Webhook 端点）
PERF_SCENE = os.environ.get("PERF_SCENE", "dashboard").lower()

# ── 消息池：10 条不同意图（闲聊/问价/撒娇/咨询）──
MESSAGE_POOL = [
    "你好呀，在吗",                # 闲聊
    "你们这个怎么卖的",            # 问价
    "哥哥人家想你了嘛",            # 撒娇
    "我想咨询一下塔罗牌",          # 咨询
    "今天有什么新鲜事",            # 闲聊
    "能给我推荐点好玩的吗",        # 咨询
    "你真可爱，喜欢你",            # 撒娇
    "这个多少钱，怎么付费",        # 问价
    "晚上一个人好无聊",            # 撒娇
    "帮我看看运势怎么样",          # 咨询
]


class PerfStats:
    """线程安全的延迟/错误统计收集器，通过 events.request 注入自定义统计"""

    def __init__(self):
        self._lock = threading.Lock()
        self.latencies = []
        self.errors = 0
        self.total = 0
        self.start_ts = None

    def record(self, response_time_ms, is_error):
        with self._lock:
            if self.start_ts is None:
                self.start_ts = time.time()
            self.latencies.append(response_time_ms)
            self.total += 1
            if is_error:
                self.errors += 1

    def summary(self):
        with self._lock:
            if not self.latencies:
                return None
            lat = sorted(self.latencies)
            n = len(lat)
            elapsed = time.time() - (self.start_ts or time.time())
            return {
                "total": n,
                "errors": self.errors,
                "error_rate": (self.errors / n) * 100 if n else 0,
                "p50": lat[int(n * 0.5)],
                "p95": lat[min(int(n * 0.95), n - 1)],
                "p99": lat[min(int(n * 0.99), n - 1)],
                "rps": n / elapsed if elapsed > 0 else 0,
                "elapsed": elapsed,
            }


perf_stats = PerfStats()


@events.request.add_listener
def _on_request(response_time, exception, response, **kwargs):
    """监听每次请求，注入自定义统计（延迟/错误）"""
    is_error = exception is not None or (
        response is not None and getattr(response, "status_code", 200) >= 400
    )
    perf_stats.record(response_time or 0, is_error)


@events.test_stop.add_listener
def _on_test_stop(environment, **kwargs):
    """测试结束打印自定义统计摘要（P50/P95/P99/错误率/RPS）"""
    s = perf_stats.summary()
    if not s:
        return
    print("\n" + "=" * 60)
    print("[TRAE SOLO CN] 性能压测摘要")
    print("=" * 60)
    print(f"总请求数：{s['total']}")
    print(f"错误数：{s['errors']}  错误率：{s['error_rate']:.2f}%")
    print(f"吞吐量：{s['rps']:.2f} RPS")
    print(f"延迟 P50：{s['p50']:.0f} ms")
    print(f"延迟 P95：{s['p95']:.0f} ms")
    print(f"延迟 P99：{s['p99']:.0f} ms")
    print(f"持续时间：{s['elapsed']:.1f} s")
    print("=" * 60)


def _build_update(user_id, update_id):
    """构造模拟 Telegram Update JSON（message 类型）"""
    name = f"PerfUser{user_id % 10000}"
    uname = f"perf_{user_id}"
    return {
        "update_id": update_id,
        "message": {
            "message_id": random.randint(1, 999999),
            "from": {"id": user_id, "is_bot": False,
                     "first_name": name, "username": uname},
            "chat": {"id": user_id, "first_name": name,
                     "username": uname, "type": "private"},
            "date": int(time.time()),
            "text": random.choice(MESSAGE_POOL),
        },
    }


def _webhook_url():
    """计算 Webhook 请求路径（BOT_TOKEN 存在时拼入路径，模拟 Telegram 真实 webhook）"""
    if BOT_TOKEN:
        base = WEBHOOK_PATH if WEBHOOK_PATH.endswith("/") else WEBHOOK_PATH + "/"
        return f"{base}{BOT_TOKEN}/"
    return WEBHOOK_PATH


class TelegramWebhookUser(HttpUser):
    """模拟 Telegram 用户向 Webhook 端点 POST Update"""
    # 请求间隔 1-5 秒随机
    wait_time = between(1, 5)
    # 每个虚拟用户独立 user_id（从 USER_ID_START 递增）
    _uid_counter = USER_ID_START
    _uid_lock = threading.Lock()

    def on_start(self):
        with self._uid_lock:
            self.user_id = self._uid_counter
            TelegramWebhookUser._uid_counter += 1
        self.update_id = self.user_id * 1000

    @task
    def send_message(self):
        """POST 模拟 Telegram Update 到 Webhook 端点"""
        self.update_id += 1
        payload = _build_update(self.user_id, self.update_id)
        headers = {"Content-Type": "application/json"}
        with self.client.post(_webhook_url(), json=payload, headers=headers,
                              catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
            else:
                resp.success()


# ── Dashboard API 压测端点池（只读接口，不破坏数据）──
DASHBOARD_ENDPOINTS = [
    "/api/health",                  # 健康检查（最轻量）
    "/api/scheduler/stats",         # 调度统计
    "/api/scheduler/jobs",          # 调度任务列表
    "/api/audit/stats",             # 审计统计
    "/api/attribution/report?days=7",  # 归因报表
    "/api/attribution/by-campaign?days=7",  # Campaign 维度
    "/api/attribution/by-hour?days=7",      # 时段维度
    "/api/attribution/by-persona?days=7",   # 人设桶维度
]


class DashboardApiUser(HttpUser):
    """模拟并发访问 Dashboard API 读接口（推荐场景）

    项目默认 Flask 用于 Dashboard（端口 6616），此场景压测真实端点。
    所有接口均为 GET 只读，不破坏数据。
    """
    # 请求间隔 0.5-2 秒（比 Webhook 场景更密集，模拟 Dashboard 高频查询）
    wait_time = between(0.5, 2)

    @task(3)
    def get_health(self):
        """健康检查（最高频，轻量）"""
        with self.client.get("/api/health", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
            else:
                resp.success()

    @task(2)
    def get_scheduler_stats(self):
        """调度统计"""
        with self.client.get("/api/scheduler/stats", catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
            else:
                resp.success()

    @task(1)
    def get_attribution_report(self):
        """归因报表（较重，涉及聚合查询）"""
        with self.client.get("/api/attribution/report?days=7",
                             catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
            else:
                resp.success()

    @task(1)
    def get_random_endpoint(self):
        """随机访问端点池（模拟混合负载）"""
        path = random.choice(DASHBOARD_ENDPOINTS)
        with self.client.get(path, catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
            else:
                resp.success()


# ── 场景路由：根据 PERF_SCENE 选择激活的 User 类 ──
if PERF_SCENE == "webhook":
    # Webhook 场景：禁用 DashboardApiUser
    DashboardApiUser.weight = 0
    print(f"[PERF] 场景=Webhook，压测端点={_webhook_url()}")
else:
    # Dashboard 场景（默认）：禁用 TelegramWebhookUser
    TelegramWebhookUser.weight = 0
    print(f"[PERF] 场景=Dashboard，压测 {len(DASHBOARD_ENDPOINTS)} 个 API 端点")
