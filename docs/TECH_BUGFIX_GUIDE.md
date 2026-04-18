# 🐛 技术Bug修复指南 v21.44

> **本文件记录所有已发现和修复的Bug，供后续开发者参考。**
> **格式：问题描述 → 根因分析 → 修复方案 → 涉及文件**
> **最后更新：2026-04-18 17:03**

---

## 📌 目录

1. **[v21.44] Bot 409 Conflict冲突**
2. **[v21.44] 阅后即焚追踪污染问题**
3. [v21.43] 新闻播报发两条 + 背刺泄密频率过高
4. [v21.42] 阅后即焚两大功能失效
5. [历史] Bot状态显示"已停止"

---

## [v21.44] Bug #1：Bot 409 Conflict冲突

### 问题描述
Bot日志中出现大量 `Error code: 409. Description: Conflict: terminated by other getUpdates request` 错误。

### 根因分析
有多个Bot进程同时运行，争用同一个Telegram API连接。

### 修复方案
```bash
# 1. 终止所有Bot进程
pkill -9 -f 'main.py'

# 2. 重新启动Bot
bash start.sh start
```

### 验证
```bash
bash start.sh status  # 应显示单一PID
tail -50 mory.log     # 不应有新的409错误
```

### 涉及文件
- 系统进程管理

---

## [v21.44] Bug #0：阅后即焚追踪污染

### 问题描述
1. `reply_tracking` 表为空，没有任何有效追踪记录
2. 日志中出现大量 `track_reply参数无效: user=0` 错误
3. 无法确认阅后即焚功能是否正常工作

### 根因分析

**问题A：主动消息错误调用追踪**

`auto_tasks.py` 中的 `_send_and_track()` 函数调用了 `track_reply()`：
```python
# 原代码 auto_tasks.py 第112-116行
if sent and chat_id < 0:  # 群聊才追踪
    with rm.locked('db'):
        rm.db.track_reply(sent.message_id, chat_id, user_msg_id)  # user_msg_id=0
```

但主动消息（早安问候、新闻播报、背刺泄密）传入的 `user_msg_id=0`，被 `database.py` 拒绝：
```python
# database.py 第329-331行
if not bot_msg_id or not chat_id or not user_msg_id:
    logger.error(f"📌 track_reply参数无效: bot={bot_msg_id} chat={chat_id} user={user_msg_id}")
    return
```

**问题B：日志级别过低**

关键追踪日志使用 `logger.debug` 级别，默认不输出：
```python
# main.py 第356行
logger.debug(f"📌 tracked_reply调用: chat={cid}, ...")
```

### 问题链条

1. `auto_tasks.py` 发送早安问候 → 调用 `track_reply(bot_msg, chat, 0)`
2. 数据库因 `user_msg_id=0` 拒绝记录 → 产生 ERROR 日志
3. `reply_tracking` 表保持为空（因为没有任何正常追踪）
4. DEBUG 日志不输出，无法确认 `_tracked_reply` 是否被调用

### 修复方案

**1. 移除 `_send_and_track` 中的追踪调用：**
```python
def _send_and_track(rm, chat_id, text, user_msg_id=0):
    """发送消息（主动消息不需要追踪）
    
    注意：主动消息（如早安问候、新闻播报）不需要阅后即焚追踪，
    因为它们没有对应的"原消息"需要探测是否被删除。
    """
    try:
        with rm.locked('bot'):
            sent = rm.bot.send_message(chat_id, text)
        # 【修复v21.44】主动消息不追踪，避免污染reply_tracking表
        return sent
    except Exception as e:
        logger.error(f"发送失败：{e}")
        return None
```

**2. 升级 main.py 的追踪日志为 INFO 级别：**
```python
# main.py 第356行
logger.info(f"📌 【阅后即焚】_tracked_reply被调用: chat={cid}, ...")
```

### 涉及文件
- `modules/auto_tasks.py`
- `main.py`

### 验证方法

1. Bot重启后无 `user=0` 错误
2. 群里有人发消息时，日志中出现 `【阅后即焚】_tracked_reply被调用`
3. `reply_tracking` 表有记录生成

---

## [v21.43] Bug #1：新闻播报发两条

### 问题描述
早间新闻发了2条：
- 第一条：详细版（4条新闻 + 结尾金句）- 太长
- 第二条：总结版（5条新闻标题）- 重复发送

### 根因分析

**核心问题**：`ai_engine.py` 中 `_build_persona()` 方法的新闻模式没有正确接收真实新闻数据

```python
# 原代码问题位置：ai_engine.py 第437-438行
if mode in ("news", "afternoon_news", "evening_news"):
    persona = modes[mode].replace("{SEED}", f"种子{seed}")
    # ❌ BUG: 这里替换成占位符，而不是真实新闻
    persona = persona.replace("{NEWS_CONTENT}", "（请严格按照用户发给你的新闻列表内容进行播报！）")
```

**问题链条**：
1. `auto_tasks.py` 调用 `ai.ask(news_input, mode="news")` 时，真实新闻在 `news_input` 参数中
2. `ask()` 方法把 `news_input` 发到 `question` 参数
3. `_build_persona()` 构建 system prompt 时，`{NEWS_CONTENT}` 被替换成**占位符文本**
4. AI 因为没收到真实新闻数据，**自己生成了"总结"内容**

### 修复方案

**1. 修改 `_build_persona()` 方法签名，添加 `news_content` 参数：**
```python
def _build_persona(self, mode: str, seed: int = 0, news_content: str = "") -> str:
```

**2. 修改 `ask()` 方法，新闻模式时传入真实新闻：**
```python
# ai_engine.py 第518行
{"role": "system", "content": self._build_persona(mode, seed, question if mode in ("news", "afternoon_news", "evening_news") else "")},
```

**3. 增强 prompt 禁止词，防止AI生成多余内容：**
```
绝对禁止说"总结""下面""以上""摘要""回顾""导语"
绝对禁止加结尾金句/感悟/感想/祝福
```

**4. 更严格的字数限制：**
- 早间新闻：100字以内
- 午间新闻：100字以内
- 晚间新闻：80字以内

### 涉及文件
- `core/ai_engine.py`

---

## [v21.43] Bug #2：背刺泄密频率过高

### 问题描述
背刺泄密功能在短时间内连续触发多次（9:04、9:21、9:22各发一条），应该每周只触发1次。

### 根因分析

**核心问题**：`last_leak_week` 是模块级内存变量，每次代码热更新时被重置

```python
# 原代码问题位置：auto_tasks.py 第83行
last_leak_week = -1  # ISO周号，每周最多1次

# 第356行判断逻辑
if gid != 0 and current_week != last_leak_week and now.weekday() >= 2:
```

**问题链条**：
1. `last_leak_week` 定义在模块顶部
2. 每次执行 `bash start.sh update` 热更新代码时，Python模块被重新加载
3. `last_leak_week` 被重置为 `-1`
4. `current_week != -1` 永远为 True，导致每周1次限制**完全失效**

### 修复方案

**1. 将周号持久化到 config.json：**
```python
# 读取时从config.json获取
with rm.locked_multi(['config']):
    last_leak_week = rm.config.get("_LAST_LEAK_WEEK", -1)

# 发送成功后写入config.json
rm.config["_LAST_LEAK_WEEK"] = current_week
rm.save_config_fn()
```

**2. 移除模块级变量 `last_leak_week`（已不再需要）**

### 涉及文件
- `modules/auto_tasks.py`
- `config.json`（新增 `_LAST_LEAK_WEEK` 字段）

---

## [v21.42] Bug #3：阅后即焚"删除不回复自己的消息"失效

### 问题描述
群里发消息后，bot的回复消息即使没人回复，也不会被自动删除。

### 根因分析

**核心问题**：`auto_mark_group_active()` 会错误地将所有历史未回复消息标记为 `replied=1`

```python
# database.py 原代码
def auto_mark_group_active(self, chat_id: int, before_ts: int):
    c.execute("""UPDATE reply_tracking SET replied=1
                 WHERE chat_id=? AND replied=0 AND ts<?""",
              (chat_id, before_ts))
```

**问题链条**：
1. 群里**任何人发消息**时，`auto_mark_group_active()` 被调用
2. 该方法将群里**所有历史未回复消息**（`ts < before_ts`）标记为 `replied=1`
3. `get_orphan_messages()` 查询 `WHERE replied=0`，找不到任何消息
4. **24小时孤儿清理失效**

### 修复方案

**限制 `auto_mark_group_active()` 只标记探测窗口内的消息：**

```python
def auto_mark_group_active(self, chat_id: int, before_ts: int):
    # 只标记10分钟内的消息，避免历史消息被误标记
    window = 600
    cutoff = before_ts - window
    c.execute("""UPDATE reply_tracking SET replied=1
                 WHERE chat_id=? AND replied=0 AND ts>? AND ts<??""",
              (chat_id, cutoff, before_ts))
```

### 涉及文件
- `core/database.py`

---

## [v21.42] Bug #4：阅后即焚"删除删除的回复消息"失效

### 问题描述
用户删除消息后，bot的回复没有被同步删除。

### 根因分析

**核心问题**：`get_unconfirmed_messages()` 依赖 `replied` 状态，但该状态已被 `auto_mark_group_active()` 污染

```python
# database.py 原代码
def get_unconfirmed_messages(self, window: int = 300):
    c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                 WHERE ts>? AND replied=0""", (since,))
```

**问题链条**：
1. 群里发消息 → `auto_mark_group_active()` 将历史消息标记为 `replied=1`
2. 原消息探测调用 `get_unconfirmed_messages(3600)`
3. 查询条件 `WHERE replied=0` 过滤掉了已被标记的消息
4. **原消息探测失效**

### 修复方案

**1. 查询不再依赖 `replied` 状态：**
```python
def get_unconfirmed_messages(self, window: int = 3600):
    now = int(time.time())
    since = now - window
    c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                 WHERE ts>? AND user_msg_id>0""", (since,))
```

**2. 新增 `refresh_tracked()` 方法，探测成功后更新时间戳：**
```python
def refresh_tracked(self, bot_msg_id: int, chat_id: int):
    """刷新追踪记录的时间戳，避免被孤儿清理重复探测"""
    ts = int(time.time())
    self.conn.execute("UPDATE reply_tracking SET ts=? WHERE bot_msg_id=? AND chat_id=?",
                   (ts, bot_msg_id, chat_id))
```

**3. 修改孤儿清理，基于时间窗口判定：**
```python
def get_orphan_messages(self, window: int = 86400):
    cutoff = int(time.time()) - window
    # 基于时间窗口判定孤儿，不再依赖 replied 状态
    c.execute("""SELECT bot_msg_id, chat_id, user_msg_id FROM reply_tracking
                 WHERE ts<? AND user_msg_id>0""", (cutoff,))
```

**4. auto_tasks.py 探测成功时更新时间戳：**
```python
# 原消息还在，刷新追踪记录的时间戳
with rm.locked('db'):
    rm.db.refresh_tracked(bot_mid, cid)
```

### 涉及文件
- `core/database.py`
- `modules/auto_tasks.py`

---

## [历史] Bug #5：Bot状态显示"已停止"（实际在运行）

### 问题描述
Dashboard显示bot状态为"已停止"，但实际进程在正常运行。

### 根因分析
`get_vps_status()` 使用 `ps aux` 解析进程信息，不稳定。

### 修复方案
改用 `pgrep -f 'main.py'` 获取PID，再查询内存。

### 涉及文件
- `dashboard/app.py`

---

## 📝 维护规则

1. **每次修复Bug后，必须更新本文档**
2. **文档格式：问题描述 → 根因分析 → 修复方案 → 涉及文件**
3. **代码中必须添加版本标记注释**，如：`# 【修复v21.43】`
4. **config.json 的 `_CONFIG_VERSION` 必须同步更新**

---

## 🔧 代码审查清单

修改以下模块时需特别注意：

| 模块 | 风险点 |
|------|--------|
| `auto_tasks.py` | 定时任务、循环逻辑、热更新后变量重置 |
| `database.py` | replied状态污染、孤儿清理逻辑 |
| `ai_engine.py` | 新闻模式数据注入、prompt占位符替换 |
| `main.py` | monkey-patch `reply_to`、阅后即焚追踪 |

---

*文档版本：v21.44 | 最后更新：2026-04-18*
