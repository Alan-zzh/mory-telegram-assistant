# 8 大类老坑详细反模式与验证命令

> **被 docs/technical/ 收录 · 适用版本：v5.12.0+**
> **最后更新**：2026-06-02（v5.12.1 拆分为 code/ops 两文件）

## 概述

本文件是 `AGENTS.md` 中"⚠️ 8 大类老坑铁律"章节的**详细版**（核心代码铁律）：
- `AGENTS.md` 只放精简的铁律要点 + 引用链接
- 本文件放完整的**反例/正例代码块**（**核心代码层面** 5 大类）
- 运维层面 3 大类（3, 5, 7）见 [anti-patterns-ops.md](anti-patterns-ops.md)

任何 AI 开工时可按需查阅。**8 大类与 AGENTS.md 一一对应**：1/2/4/6/8 见本文件，3/5/7 见 ops。

---

## 类别1：沉默失败 8 大反模式

> `try/except` 吞错导致功能从未生效。**项目最反复出现的问题**（v5.10.0 / v5.11.0 实际翻车，见 [AI_DEBUG_HISTORY.md](../../AI_DEBUG_HISTORY.md) v5.10.0 节 4 和 v5.11.0 节 坑1）。

### 铁律 1.1：核心 DB 调用不吞错

- **禁止**在 `track_reply` / `track_bot_message` / `track_broadcast` / `get_orphan_messages` 等关键路径外层套无操作 `try/except`
- 必须用 `logger.error` 记录失败原因（至少带变量名）

**反例**（v5.7.3 实际翻车）：
```python
try:
    db.track_reply(...)
except:
    pass  # 沉默失败，无人能发现
```

**正例**：
```python
try:
    db.track_reply(...)
except Exception as e:
    logger.error(f"track_reply 失败: {e}")
```

### 铁律 1.2：属性访问失败大声报

- DB 方法委托（`__getattr__` 委托到 `_REPO_METHOD_MAP`）找不到方法时，应直接抛 `AttributeError`，不要被 try/except 吞

**反例**（v5.11.0 实际翻车）：
```python
try:
    db.track_bot_message(...)
except AttributeError:
    pass  # 找不到方法就当没事？错！
```

### 铁律 1.3：字典键访问用 `.get()` 不用 `[]`

- 字典访问不存在的 key 会抛 `KeyError` —— 在 try/except 里被吞后变沉默失败

**反例**：`value = config['NEW_KEY']`（不存在就崩）
**正例**：`value = config.get('NEW_KEY', False)`（不存在用 False）

### 铁律 1.4：写文件/网络/DB 前检查返回值

- `sftp.put()` 失败时只抛 `PermissionError` 不带具体文件路径
- 必须在外层 `try/except` 里 `logger.error(f"sftp.put 失败: {local} -> {remote}")`
- 不要用裸 `except: pass` —— 会吞掉所有异常包括键盘中断

### 铁律 1.5：import 错误大声报

- 不要用 `try: import x except: x = None`，除非有充分理由
- 如果是 fallback，**必须 logger.warning** 说明走了 fallback

- 实际是 v5.10.0 `bot_initializer.py:405` 条件块内 `import threading` 与模块级同名 import 冲突，触发 `UnboundLocalError`（教训：要始终在模块顶部 import）

### 铁律 1.6：循环里异常不要"全跳过"

- 批量处理（如清理 100 条孤儿消息）时，单条失败应 `logger.debug` 继续，不要 `break` 跳出
- 但**必须**在循环外统计 success/fail 计数，最终打印汇总

### 铁律 1.7：异步任务异常有兜底

- `threading.Timer` / `apscheduler.add_job` / `asyncio.create_task` 启动的任务必须有 try/except
- APScheduler 任务的异常会进 scheduler logger，但可能不显眼
- 必须**外层包一层 try/except + logger.error**

### 铁律 1.8：删数据库记录前先确认消息已删

- 顺序：先 `bot.delete_message(chat_id, msg_id)` → 成功后才 `db.delete_tracked(bot_mid, cid)`
- 反过来会导致"消息没删但 DB 记录没了，下次无法重试"

### 🔍 验证命令（完整版）


---

## 类别2：配置一致性 5 条铁律

> 新增配置键只改代码不更新 example → 部署后崩。

### 铁律 2.1：新增配置键必须三处同步

- 三个地方必须同时改：
  1. `config.json.example`（示例文件）
  2. `core/settings.py` 或加载逻辑（默认值）
  3. Dashboard 设置面板（如适用）
- **不能**只改代码不更新 example，否则部署时 VPS 端会缺键

### 铁律 2.2：代码读取配置用 `.get(key, default)`

- **必须**用 `config.get('KEY', False)` 或 `config.get('KEY', 0)`
- **禁止**用 `config['KEY']` —— 缺键就崩

### 铁律 2.3：默认值在代码中显式声明

- 即使 `config.json.example` 写了默认值，代码中也要显式 `.get(key, default)`
- 原因：VPS 端老 config.json 不会自动同步新键，必须代码兜底

### 铁律 2.4：.env.example 列出所有 KEY

- 新增环境变量必须在 `.env.example` 末尾追加（不删除已有）
- 凭据只写 KEY_NAME，不写值
- 已在 `.env` 的 KEY 不动

### 铁律 2.5：config.json 部署用 `safe_upload_config`

- **必须**用 `core/deploy_utils.py` 的 `safe_upload_config()` 上传
- 禁止直接 `sftp.put('config.json', ...)` —— 覆盖会把 VPS 端的 token 清空

### 🔍 验证命令（完整版）


---

## 类别4：数据库方法注册 4 条铁律

> 在 `core/db_repos/*.py` 新增方法后**忘记**注册到 `core/database.py` 的 `_REPO_METHOD_MAP` → 抛 `AttributeError`（v5.11.0 实际翻车，潜伏多版本）。

### 铁律 4.1：`_REPO_METHOD_MAP` 是 db 方法委托的唯一真源

- **必须**在 `core/database.py` 的 `_REPO_METHOD_MAP` 字典中注册新方法：`'new_method': 'repo_name'`
- 其中 `repo_name` 是 `core/db_repos/{repo_name}_repo.py` 的前缀
- 不注册则 `db.new_method()` 会 `AttributeError: 'DB' object has no attribute 'new_method'`

### 铁律 4.2：新增方法后立即测试委托

- **必须**用 `db = DB(test.db); db.new_method()` 验证
- 不要只在 `repo` 实例上测（不会经过委托）

### 铁律 4.3：grep 验证注册完整性

- 每次新增 db_repos 方法后，跑下方验证命令确认

### 铁律 4.4：`__getattr__` 委托失败要大声报

- 当前 `__getattr__` 委托对未知属性会抛 `AttributeError`
- 不要在调用方用 `try/except` 吞这个异常 —— 立即修

### 🔍 验证命令（完整版）


---

## 类别6：关键路径 5 条铁律

> 核心功能（清理/告警/统计）只做语法/单元测试就上线，**实际生产从未生效**（v5.11.0 track_bot_message 漏注册就是这个模式）。

### 铁律 6.1：核心功能必须有端到端验证

- 不能只做 `py_compile` + 单元测试
- 必须模拟真实场景：发消息 → 等触发 → 看结果
- v5.12.0 新增 `scripts/verify_orphan_cleanup.py` 是这个模式的应用

### 铁律 6.2：DB 写入后立即回查

- 写入数据库后必须 `SELECT` 回查确认
- 不能"以为写入了"

### 铁律 6.3：清理/删除操作要可观测

- 每次清理必须写日志（成功/失败/跳过计数）
- 必须有 Dashboard API 或 status 脚本查询清理状态
- v5.12.0 新增 `orphan_cleanup_log` 表 + `/api/orphan/stats` 端点

### 铁律 6.4：状态开关关闭要告警

- 关键开关（如 `ENABLE_MESSAGE_DELETION`）关闭时，依赖该开关的清理任务**不应静默跳过**
- 应改为告警（发管理员私聊 + 写日志），让用户知道"开关关了所以没删"
- v5.12.0 新增 `_handle_orphan_disabled_alert()` 实现这个

### 铁律 6.5：依赖项缺失要降级但不沉默

- 依赖（如 APScheduler、Pyrogram、PyMySQL）不可用时，应 `logger.warning` 说明走了 fallback
- 不要直接 `try/except` 吞

### 🔍 验证命令（完整版）


---

## 类别8：VPS 部署 5 条铁律

> 本地改完 deploy_vps.py 部署失败，错误信息模糊。

### 铁律 8.1：每次部署前自动 chown

- 见铁律 3.3（deploy_vps.py 改造建议）

### 铁律 8.2：服务文件 owner 检查

- `/etc/systemd/system/mory-assistant.service` 应为 `root:root`（644）
- 不能是 `ubuntu:root`（systemd 加载可能有问题）

### 铁律 8.3：依赖完整性验证

- `python3 -c "import telegram"` 必须成功
- `python3 -c "import apscheduler"` 必须成功
- `python3 -c "import flask"` 必须成功
- 缺依赖时 `pip install -r requirements.txt` 自动补

### 铁律 8.4：deploy_vps.py 必须验证

- 部署后 5 大验证：
  1. Bot 进程 active
  2. Dashboard 进程 active
  3. `mory.db` 完整性
  4. `config.json` 完整性
  5. Bot 日志无 error

### 铁律 8.5：VPS 端 mory.db 不能从本地覆盖

- **永远不要** `sftp.put` 上传 `mory.db`
- 数据库是用户数据，部署只上传代码
- 如果 db 损坏，从 VPS 备份恢复（不是本地）

### 🔍 验证命令（完整版）


---

## 引用

- [AGENTS.md](../../AGENTS.md) — 精简铁律 + 引用本文件
- [orphan-cleanup.md](orphan-cleanup.md) — 孤儿清理机制
- [vps-deploy-trap.md](vps-deploy-trap.md) — VPS 部署陷阱
- [config-reload.md](config-reload.md) — 配置热重载
- [ad-detection.md](ad-detection.md) — 广告检测
- [anti-patterns-ops.md](anti-patterns-ops.md) — 运维铁律（部署/迁移/AI 自我审计/VPS 4 大类）

- 2026-06-02 (v5.12.0) — 首次创建，从 `.agents` 拆出 8 大类反模式详细示例
