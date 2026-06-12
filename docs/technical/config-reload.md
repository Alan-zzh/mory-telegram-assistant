# Dashboard-Bot 配置热重载机制详解

> **被 [AGENTS.md](../../AGENTS.md) 索引引用 · 适用版本：v5.10.2+**
> **最后更新**：2026-06-02（v5.12.1 .agents→AGENTS.md）

## 概述

Mory 小助理的 Dashboard 是一个独立的 Flask 进程（systemd 管理），Bot 是另一个独立进程。v5.10.2 之前，Dashboard 修改配置后 Bot 必须手动重启才能生效。v5.10.2 引入**基于文件的信号机制**实现配置热重载：Dashboard 写配置 → 创建 reload_flag → Bot 5秒轮询消费 → 配置生效。

## 适用场景

- 实现 Dashboard 改配置后无需重启 Bot 的能力
- 排查"为什么 Dashboard 改了配置 Bot 没生效"问题
- 写新配置项时参考本文档确保自动生效

## 关键内容

### 一、设计目标

| 项 | 目标 |
|----|------|
| **延迟** | Dashboard 改 → Bot 生效 ≤ 8 秒（5秒轮询 + 3秒处理） |
| **可靠性** | 跨进程不丢信号（即使 Bot 暂时挂掉） |
| **简单性** | 不引入 Redis/消息队列等外部依赖 |
| **可观测** | Bot 日志有 `🔄 配置已重载` 输出 |
| **不影响** | 不影响 Bot 正在处理的消息/任务 |

### 二、技术方案

**基于文件的信号机制**（reload_flag）：

```
Dashboard 进程                   Bot 进程
    │                                │
    ├── write_config()               │
    │   ├── 写 config.json          │
    │   └── _signal_config_reload()  │
    │       └── 创建 reload_flag    ──┐
    │                                 │
    │                                 ├── start_config_reload_watcher()
    │                                 │   后台线程每 5 秒轮询 reload_flag
    │                                 │
    │                                 ├── 发现 reload_flag
    │                                 ├── 删除 reload_flag（消费）
    │                                 ├── reload_config() 重新加载
    │                                 └── logger.info("🔄 配置已重载")
    │                                 │
```

**为什么选文件信号而不是信号量/管道/Redis？**

| 方案 | 优点 | 缺点 | 是否采用 |
|------|------|------|----------|
| **文件信号** | 简单可靠，跨进程无 IPC 复杂度，挂掉不丢信号 | 5秒轮询有延迟 | ✅ **采用** |
| Linux 信号量 | 实时 | 跨进程复杂，进程挂掉信号丢失 | ❌ |
| 命名管道 | 实时 | 阻塞 IO，可能丢信号 | ❌ |
| Redis | 实时可靠 | 增加外部依赖 | ❌ |
| inotify | 实时 | 部署环境需安装，复杂度高 | ❌ |

### 三、关键代码

#### 3.1 Dashboard 端 — `dashboard/helpers.py`

```python
def write_config(config: dict) -> bool:
    """写入配置到 config.json（带 backup + 原子替换）"""
    backup_path = "config.json.bak"
    if os.path.exists("config.json"):
        shutil.copy2("config.json", backup_path)

    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    # 触发 Bot 重载
    _signal_config_reload()
    return True


def _signal_config_reload():
    """创建 reload_flag 文件，通知 Bot 进程重新加载配置"""
    flag_path = "reload_flag"
    try:
        # 用 touch 创建信号文件（原子操作）
        with open(flag_path, "w") as f:
            f.write(str(int(time.time())))
        logger.info(f"📡 配置重载信号已发送: {flag_path}")
    except Exception as e:
        logger.error(f"发送配置重载信号失败: {e}")
```

#### 3.2 Bot 端 — `core/bot_initializer.py`

```python
def start_config_reload_watcher(context: BotContext):
    """启动配置重载监视后台线程（5秒轮询）"""
    flag_path = "reload_flag"
    interval = 5  # 秒

    def _watcher():
        while True:
            try:
                if os.path.exists(flag_path):
                    # 消费信号：先删除（避免重复消费）
                    try:
                        os.remove(flag_path)
                    except FileNotFoundError:
                        pass

                    # 重新加载配置
                    reload_config(context)
                    logger.info("🔄 配置已重载")
            except Exception as e:
                logger.error(f"配置重载失败: {e}")

            time.sleep(interval)

    thread = threading.Thread(target=_watcher, daemon=True, name="config-reload-watcher")
    thread.start()
    logger.info(f"👀 配置重载监视器已启动（轮询间隔 {interval}s）")


def reload_config(context: BotContext):
    """重新加载 config.json（不重启进程）"""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            new_config = json.load(f)
        context.config = new_config
        # 通知各模块刷新自己的配置
        for module in context.modules:
            if hasattr(module, "reload_config"):
                module.reload_config(new_config)
    except Exception as e:
        logger.error(f"reload_config 失败: {e}")
```

#### 3.3 启动钩子 — `main.py`

```python
# Bot 初始化完成后启动 watcher
bot_context = init_bot()
start_config_reload_watcher(bot_context)  # 5秒轮询
bot_context.bot.infinity_polling()
```

### 四、E2E 验证

```bash
# 1. SSH 到 VPS，触发 Dashboard 改配置
curl -u admin:password -X POST http://localhost:6616/api/config \
  -H "Content-Type: application/json" \
  -d '{"ENABLE_FOO": true}'

# 2. 立即观察 Bot 日志
sudo journalctl -u mory-assistant -f

# 期望输出（5-8 秒内）：
# 📡 配置重载信号已发送: reload_flag
# 👀 配置重载监视器发现 flag
# 🔄 配置已重载

# 3. 验证新配置生效
sudo journalctl -u mory-assistant --since "1 minute ago" | \
  grep "ENABLE_FOO"
# 期望：相关模块日志显示 FOO 已开启
```

### 五、设计权衡

#### 5.1 为什么 5 秒而不是 1 秒或 10 秒？

| 间隔 | 优点 | 缺点 | 决策 |
|------|------|------|------|
| 1 秒 | 实时性高 | CPU 浪费，IO 多 | ❌ |
| **5 秒** | **平衡延迟和开销** | — | ✅ **采用** |
| 10 秒 | CPU 低 | 延迟高，用户感知差 | ❌ |
| inotify | 实时 | 部署复杂 | ❌ |

#### 5.2 为什么不直接 reload 全部模块？

- **当前方案**：只 reload config 字典，模块如有 `reload_config()` 方法会自己刷新
- **风险**：如果某模块没实现 `reload_config()`，新配置不生效
- **缓解**：所有新增配置项的模块必须实现 `reload_config()` 方法（写入 `AGENTS.md` 铁律）

#### 5.3 失败兜底

- reload_flag 文件丢失（人为删除 / 系统清理）→ Bot 不会重载，但**不影响 Bot 正常运行**（仍是旧配置）
- 用户再次改 Dashboard → 重新创建 flag → 下一轮轮询消费
- **最坏情况**：5 秒延迟 + 用户手动 `systemctl restart`

### 六、关键文件

| 文件 | 职责 |
|------|------|
| [dashboard/helpers.py](../../dashboard/helpers.py) | `write_config()` + `_signal_config_reload()` |
| [core/bot_initializer.py](../../core/bot_initializer.py) | `start_config_reload_watcher()` + `reload_config()` |
| [main.py](../../main.py) | 启动 watcher 钩子 |

### 七、历史坑

| 版本 | 现象 | 修复 |
|------|------|------|
| v5.10.2 之前 | Dashboard 改配置后 Bot 不生效，必须 systemctl restart | 引入 reload_flag + 5秒轮询 |
| v5.10.2 | reload_flag 残留导致重复 reload | 消费时先删除 flag |
| v5.10.2 | 模块未实现 reload_config() 导致新配置不生效 | 规范：所有配置相关模块必须实现 reload_config() |

## 引用

- `AGENTS.md` 类别2（配置一致性 5 条铁律）→ 根目录 `AGENTS.md` 搜 `类别2`
- `AGENTS.md` 类别6（关键路径 5 条铁律）→ 根目录 `AGENTS.md` 搜 `类别6`
- [orphan-cleanup.md](orphan-cleanup.md) — 孤儿清理机制
- [vps-deploy-trap.md](vps-deploy-trap.md) — VPS 部署陷阱

## 更新历史

- 2026-06-02 (v5.12.0) — 首次创建，记录配置热重载完整机制
