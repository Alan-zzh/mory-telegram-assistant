# HTTP 客户端统一重构技术文档

> 版本：v5.17.0 | 日期：2026-06-15 | 触发：网络请求异常处理缺失问题重构

---

## 1. 问题背景

项目中网络请求散落在多个模块，存在以下问题：

1. **超时不统一**：各模块硬编码 3s/5s/10s/15s 不等，部分甚至无超时
2. **无重试机制**：网络抖动直接失败，降低功能可用性
3. **异常处理缺失**：多处 `except Exception: pass` 静默吞错，无法排查
4. **代码重复**：每个模块各自实现 timeout/headers/exception 逻辑
5. **日志不完整**：请求失败时缺少 URL、状态码、耗时等关键信息

---

## 2. 解决方案

### 2.1 统一 HTTP 客户端（core/http_client.py）

| 特性 | 实现 |
|------|------|
| 默认超时 | 10 秒（可按请求覆盖） |
| 默认重试 | 2 次，间隔 1 秒 |
| 异常类型 | `HTTPTimeoutError` / `HTTPRequestError` |
| 后端 | requests（优先）→ urllib（回退） |
| 拦截器 | 支持 request/response 拦截器链 |
| 配置 | `config.json → HTTP_CLIENT_CONFIG`（可选） |

### 2.2 接口设计

```python
from core.http_client import get_http_client, init_http_client

# main.py 启动时初始化
init_http_client(CONFIG.get("HTTP_CLIENT_CONFIG", {}))

# 业务模块使用
client = get_http_client()
data = client.get("https://api.example.com/data", timeout=5)
data = client.post("https://api.example.com/submit", json_data={"key": "val"})
```

### 2.3 配置项（config.json → HTTP_CLIENT_CONFIG）

```json
{
  "HTTP_CLIENT_CONFIG": {
    "default_timeout": 10,
    "retry_times": 2,
    "retry_delay": 1,
    "enable_logging": true,
    "service_timeouts": {
      "cas": 5,
      "spamwatch": 5,
      "telegraph": 15,
      "url_shortener": 8
    }
  }
}
```

---

## 3. 重构模块清单

| 模块 | 原实现 | 新实现 | 变更 |
|------|--------|--------|------|
| `modules/spam_watch.py` | `requests.get` 直调 | `get_http_client().get()` | + 异常分类日志 |
| `modules/ad_detector.py` | `requests.get` 直调 | `get_http_client().get()` | + 缓存+异常处理 |
| `modules/telegraph.py` | `urllib` 调用 | `get_http_client().post()` | + 超时+重试 |
| `modules/url_shortener.py` | `requests.get` 直调 | `get_http_client().get()` | + 超时+日志 |
| `modules/search.py` | `urllib.request` 调用 | `get_http_client().get()` | + 超时+重试 |
| `modules/auto_tasks.py` | 多处 `except: pass` | 补全日志+默认值 | + 可观测性 |
| `main.py` | 无 HTTP 客户端初始化 | `init_http_client()` | + 启动初始化 |

---

## 4. 空异常处理修复

`modules/auto_tasks.py` 中发现多处 `except Exception: pass`，全部补全：

| 函数 | 原代码 | 修复后 |
|------|--------|--------|
| `_job_startup_history_cleanup` | `except Exception: pass` | `logger.warning(...)` + 默认空列表 |
| `_compute_health_score` | `except Exception: pass`（多处） | `logger.warning(...)` + 默认分数 |
| `_watchdog_check` | `except Exception: pass` | `logger.warning(...)` + 安全降级 |

---

## 5. 验证命令

```bash
# 语法检查
python -m py_compile core/http_client.py main.py modules/spam_watch.py modules/ad_detector.py

# 确认无残留 except: pass
grep -n "except Exception: pass" modules/auto_tasks.py

# 确认 HTTP 客户端已初始化
grep -n "init_http_client" main.py
```
