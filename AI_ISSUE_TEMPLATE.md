# AI问题排查指引模板

> 当需要其他AI协助排查Mory小助理问题时，请复制本文件并按实际填写。

---

## 0. VPS服务器连接信息

> **填写说明**：以下信息从本地 `.env` 文件中复制过来，直接粘贴给AI即可连接VPS。
> **安全提示**：此信息仅限当前问题排查使用，不要公开发布。

| 项目 | 值 |
|------|-----|
| VPS IP | `【填写VPS_HOST】` |
| SSH端口 | `22` |
| SSH用户 | `root` |
| SSH密码 | `【填写VPS_SSH_PASS】` |
| 项目路径 | `/root/mory` |
| 日志路径 | `/root/mory/mory.log` |
| 启动命令 | `cd /root/mory && bash start.sh start` |
| 停止命令 | `cd /root/mory && bash start.sh stop` |
| 重启命令 | `cd /root/mory && bash start.sh restart` |
| 查看状态 | `cd /root/mory && bash start.sh status` |
| 查看日志 | `cd /root/mory && bash start.sh log` |

---

## 1. 项目核心特性与技术栈

**产品名称**：Mory小助理 - Telegram群管机器人

**技术栈**：
- Python 3 + pyTelegramBotAPI + SQLite(WAL模式) + Flask
- 定时任务：APScheduler
- 部署：VPS (Linux) / Docker / Windows本地

**核心架构**：
- `core/ai_engine.py` - AI引擎（三层智能路由：轻量/标准/旗舰模型池，多模型轮换）
- `core/database.py` - SQLite数据层（13张表，线程安全，task_log持久化）
- `core/mory_bot.py` - Bot封装（BaseMiddleware中间件拦截所有消息）
- `core/optimizer.py` - 运营优化器（语义缓存+熔断器+令牌桶限流）
- `modules/auto_tasks.py` - 定时任务（早安/午安/晚安问候、新闻播报、塔罗搭讪等）
- `modules/admin_cmds.py` - 管理员指令
- `modules/natural_cmd.py` - 自然语言指令
- `dashboard/app.py` - Flask网页后台

**关键约束**：
- pyTelegramBotAPI handler是独占式的，`return False`不流转，必须用`BaseMiddleware`拦截所有消息
- 所有数据库操作受`_db_lock`保护
- 定时任务防重复机制：`_can_run()`检查 → 执行 → `_mark_done()`标记 → `task_log`表持久化
- VPS连接配置在 `core/vps_config.py`，从 `.env` 环境变量读取

---

## 2. 具体问题描述

### 2.1 问题现象
> 请描述：发生了什么？预期是什么？实际是什么？

### 2.2 错误信息
> 请粘贴：错误提示、异常堆栈、日志中的关键行（可通过SSH连VPS查看 `/root/mory/mory.log`）

### 2.3 复现步骤
> 1. 第一步
> 2. 第二步
> 3. ...

### 2.4 环境信息
- **操作系统**：Windows / Linux VPS
- **Python版本**：
- **部署方式**：直接运行 / Docker / VPS
- **最近是否修改过代码**：是/否（如有，改了哪些文件）

---

## 3. 排查范围

### 需要排查的模块（重点）
> 请指定：涉及的Python文件、函数名、功能模块

### 无需扫描的区域
> - `universal_ai_router/` - 通用AI路由模块，独立子项目，与本次问题无关
> - `scripts/` - 调试工具集，非运行时代码
> - `dashboard/app.py` - 仅当问题与网页后台相关时才需查看

---

## 4. 排查目标与期望输出

### 具体目标
> 请明确：要找到什么？（根因 / 修复方案 / 优化建议）

### 期望输出格式
```
1. 问题定位：具体到文件名:行号
2. 根因分析：为什么会出现
3. 修复方案：可执行的代码修改（SEARCH/REPLACE格式）
4. 验证方式：如何确认修复成功
```

---

## 5. 相关代码与配置

### 关键代码片段
> 仅粘贴与问题直接相关的函数/类，不要粘贴整个文件

### 相关配置
> config.json 中涉及的配置项（脱敏后）
> .env 中涉及的环境变量（脱敏后）

---

## 附录：快速参考

### 定时任务列表
| 任务 | 时间 | 防重复 |
|------|------|--------|
| 早安问候 | 8:05 | task_log持久化 |
| 早间新闻 | 9:05 | 同上 |
| 每日报告 | 9:10 | 同上 |
| 午安问候 | 12:35 | 同上 |
| 午间新闻 | 13:05 | 同上 |
| 塔罗搭讪 | 15:00 | 同上（30%概率） |
| TrendRadar播报 | 18:00 | 同上 |
| 晚间新闻 | 20:35 | 同上 |
| 晚安问候 | 23:05 | 同上 |

### 数据库表
users / points / blacklist / channel_tracking / cart_recovery / coupon_claims / daily_reports / badges / group_events / conversions / tarot_cache / task_log / keyword_triggers

### 可用模型名
- qwen-flash-character
- qwen3.6-flash-2026-04-16
- qwen3.5-plus-2026-04-20
- qwen3.6-plus-2026-04-02
- qwen3-max（简写可用）
- qwen3.6-max-preview
- glm-5.1

### 失败方案避让（绝对不要使用）
| 编号 | 失败方案 | 正确做法 |
|------|----------|----------|
| X-01 | return False让handler流转 | BaseMiddleware拦截 |
| X-02 | f-string拼接SQL列名 | if/else分支 |
| X-04 | 硬编码VPS IP/密码 | 环境变量读取 |
| X-11 | 裸except捕获所有异常 | except Exception |
| X-14 | fetchall()直接返回cursor结果 | 深拷贝或改用fetchone()循环 |
| X-15 | 依赖内存字典去重 | 数据库持久化task_log表 |
| X-19 | sync_vps.py只负责重启，无文件同步 | 使用deploy_vps.py |

> 完整避让清单见 `AI_DEBUG_HISTORY.md`
