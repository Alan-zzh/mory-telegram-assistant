# 性能基准压测（阶段3-E）

> [TRAE SOLO CN] 基于 Locust 的轻量级异步压测脚本，模拟高并发 Telegram Webhook 请求，用于摸底系统性能。

---

## ⚠️ 重要约束

- **仅在本地开发环境运行**，不要对生产 VPS 压测。
- 压测前请确认目标服务（Bot Webhook / Dashboard）已在本地启动。
- Locust 是可选依赖，未安装时脚本会给出友好提示。

---

## 📦 安装依赖

```bash
pip install locust
```

---

## 🚀 运行方式

### 1. 启动本地目标服务

确保被测的 Webhook 端点已在本地运行（默认端口 6616）。

### 2. 启动 Locust Web UI

```bash
locust -f tests/perf/locustfile.py --host=http://localhost:6616
```

浏览器打开 `http://localhost:8089`，在界面中配置：

- **Number of users**：模拟并发用户数（建议 50-100）
- **Ramp up**：每秒启动用户数（建议 5-10）
- **Host**：已通过 `--host` 指定

### 3. 无头模式运行（可选）

```bash
locust -f tests/perf/locustfile.py --host=http://localhost:6616 \
  --headless -u 100 -r 10 --run-time 60s
```

---

## ⚙️ 参数化配置（环境变量）

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `WEBHOOK_PATH` | `/webhook/` | Webhook 端点路径 |
| `BOT_TOKEN` | 空 | Bot Token，设置后拼入路径模拟 Telegram 真实 webhook（`/webhook/<TOKEN>/`） |
| `PERF_USER_ID_START` | `100000` | 虚拟用户 user_id 起始值，每个用户递增 |

示例：

```bash
# Windows PowerShell
$env:BOT_TOKEN="123456:ABC-DEF"; locust -f tests/perf/locustfile.py --host=http://localhost:6616

# Linux/macOS
BOT_TOKEN="123456:ABC-DEF" WEBHOOK_PATH="/webhook/" locust -f tests/perf/locustfile.py --host=http://localhost:6616
```

---

## 📊 测试场景说明

| 场景 | 说明 |
|------|------|
| 并发用户 | 50-100 个虚拟 Telegram 用户同时在线 |
| 请求间隔 | 每用户 1-5 秒随机间隔发送消息 |
| 消息内容 | 从 10 条预设消息随机选取（闲聊/问价/撒娇/咨询 4 类意图） |
| 用户标识 | 每个虚拟用户独立 user_id（从 100000 递增），独立 chat_id |
| 请求格式 | 标准 Telegram Update JSON（message 类型） |

---

## 📈 核心观测指标

脚本通过 `events.request` 注入自定义统计，测试结束自动打印摘要：

| 指标 | 说明 |
|------|------|
| **P50 / P95 / P99 延迟** | 响应延迟分布（毫秒） |
| **错误率** | 非 200 响应占比 |
| **吞吐量 RPS** | 每秒请求数 |
| **总请求数** | 测试期间累计请求数 |

Locust Web UI 同时提供实时图表和 CSV 导出。

---

## 📁 文件结构

```
tests/perf/
├── locustfile.py   # Locust 压测脚本（独立运行，不依赖项目内部模块）
└── README.md       # 本文件
```
