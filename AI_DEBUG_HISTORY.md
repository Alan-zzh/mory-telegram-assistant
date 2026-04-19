# 🩺 AI_DEBUG_HISTORY.md · 调试病历本

> **本文件专门写给 AI 自己看。**
> 新会话开始时，AI 必须先读一遍此文件。
> **每次对话结束时，AI 必须自动更新此文件。**

---

## ⚠️ 重要：项目上下文

### 基本信息
- **项目**：Mory小助理 - Telegram群管机器人
- **技术栈**：Python 3 + Telegram Bot API + SQLite
- **VPS**：43.159.168.175（腾讯云）
- **VPS路径**：/root/mory
- **VPS密码**：066Sh9$YhG#Let（通过 .env 的 VPS_SSH_PASS 读取）

### 关键路径备忘（⚠️ 必须记住）
| 用途 | 路径 |
|------|------|
| Bot运行日志 | `/root/mory/mory.log`（⚠️ 不是 bot.log！） |
| PID文件 | `/root/mory/.mory.pid` |
| 启动命令 | `cd /root/mory && bash start.sh start` |
| 停止命令 | `cd /root/mory && bash start.sh stop` |
| 热更新 | `cd /root/mory && bash start.sh update` |
| 配置文件 | `/root/mory/config.json` |
| SSH连接 | 通过 `core/vps_config.py` 的 `ssh_connect()` 函数 |

### 核心功能
1. **阅后即焚** - 群聊消息24小时无人回复自动删除
2. **回复嗅探** - 由 `ReplySnifferMiddleware` 底层中间件统一捕获（v4.1.0升级）
3. **AI对话** - 基于通义千问的群聊AI助手
4. **自动任务** - 早安问候、新闻播报、醋意挽回等

---

## 📋 待办清单（跨会话自动执行）

> ⚠️ **新会话开始时，AI 必须先检查此处，如有未完成项则继续执行。**

### ✅ 已完成：根目录重度污染清理（v4.2.0）
- **完成时间**：2026-04-19
- **归档数量**：86 个文件
- **结果**：根目录从 70+ 文件精简到 25 个核心文件

### ✅ 已完成：VPS 同步部署（v4.2.0）
- **完成时间**：2026-04-19
- **操作**：`sync_and_restart.py` 脚本同步到 VPS 并重启机器人
- **结果**：机器人运行中 PID=2251911，内存 43.125MB，数据库 100K

### 🟡 可选：PM2 进程管理（替代 kill_bot.py）
- **问题**：`kill_bot.py` 和 `restart_bot.py` 过于业余
- **解决方案**：在 VPS 上安装 PM2
  ```bash
  npm install -g pm2
  pm2 start main.py --name mory-bot --interpreter python3
  ```
- **好处**：崩溃自动重启，无需手动杀进程

### ⚠️ VPS 部署说明
- **VPS 代码部署方式**：不是通过 git pull，而是通过 `_archive_scripts/sync_and_restart.py` 脚本
- **VPS 上没有 .git 仓库**：git pull 会报 `fatal: not a git repository`
- **当前部署方式**：使用 `bash start.sh restart` 直接重启（读取本地已有代码）

---

---

### ⚠️ pyTelegramBotAPI Handler 机制警示
**重要规则**：pyTelegramBotAPI 的 `@bot.message_handler` 是**独占式**的。
- 如果一个 handler 的 `func` 条件匹配，该消息**不会**继续流转到其他 handler
- 绝对不能把业务逻辑放在独立的 handler 里然后 `return False`！
- 正确做法：使用 `BaseMiddleware` 拦截所有消息，或在 `master_handler`/`_dispatch` 内处理

### ⚠️ v4.1.0 架构升级要点
**问题**：用户的图片/语音/贴纸回复不会被 `master_handler` 捕获
**原因**：`content_types=["text", "new_chat_members"]` 会过滤掉其他类型消息
**解决方案**：使用 `BaseMiddleware` 的 `ReplySnifferMiddleware` 类，在所有 handler 之前统一拦截所有类型消息

### 关键表结构
```sql
reply_tracking(bot_msg_id, chat_id, user_msg_id, ts, replied)
```

---

## ❌ 未解决的问题

### 1. 群组历史消息无法访问
**问题**：Bot使用getUpdates polling模式，无法获取群组历史消息
**影响**：无法自动清理Bot启动前的历史消息
**原因**：Telegram API限制，普通Bot无法使用getChatHistory
**状态**：无法解决（API限制）
**临时方案**：手动删除历史消息

### 2. 醋意挽回/购物车挽回403错误
**问题**：Bot无法主动给用户发私信
**原因**：Telegram平台限制，用户必须先联系Bot
**状态**：非Bug，平台限制
**解决方案**：让用户先主动联系Bot一次

### 3. reply_tracking表为空
**问题**：Bot重启后，reply_tracking表没有记录
**原因**：
- Bot随机回复概率10%，可能没抽到回复
- 需要Bot回复群消息才会创建追踪记录
**状态**：正常现象，需要测试验证
**验证方法**：让Bot回复群消息，然后检查表记录

---

## ✅ 已解决的问题

### [2026-04-19] 提示词模板配置化 ✅ 已解决

**问题描述**：`core/ai_engine.py` 中的提示词模板（如晚间新闻、早安问候等）是**硬编码在源代码中**的，每次更新脚本都会直接覆盖 VPS 文件，导致在 VPS 上手动修改的提示词丢失。

**根因**：源代码文件（`.py`）的更新是**文件整体覆盖**，无法进行字段级合并。只要提示词写在代码里，就无法避免“更新即覆盖”的风险。

**修复方案**：
1. **抽离硬编码模板**：将 `ai_engine.py` 中的 `PROMPT_TEMPLATES` 字典（16个模板）全部移入 `config.json` 的 `PROMPT_TEMPLATES` 字段
2. **动态读取配置**：修改 `_build_persona` 方法，优先从配置读取模板，若无则使用硬编码后备
3. **配置合并保护**：模板现在存储在 `config.json` 中，`deploy_final.py` 的配置合并机制会自动保护 VPS 上已修改的模板，防止被覆盖
4. **双向同步可能**：用户可通过网页端修改 `config.json` 中的模板，一键部署自动同步到 VPS；VPS 上的修改也会在下次部署时拉回本地

**代码位置**：
- `config.json`：新增 `PROMPT_TEMPLATES` 字段
- `core/ai_engine.py`：`_build_persona` 方法第 380‑454 行重写

**验证**：
1. 检查 `config.json` 是否包含 `PROMPT_TEMPLATES` 字段（16个模板）
2. 运行 `main.py` 测试各模式是否正常（如 `mode="news"`）
3. 修改 `config.json` 中的某个模板，观察 AI 调用是否生效
4. 执行一键部署，确认 VPS 上的模板修改不会被覆盖

---

### [2026-04-19] 一键部署配置合并机制 ✅ 已解决

**问题描述**：`一键部署.bat` / `deploy_final.py` 存在隐藏风险：每次部署都会覆盖 VPS 上的 `config.json`，导致在 VPS 上修改的配置丢失。

**根因**：原部署流程是**单向推送**，未考虑 VPS 上配置可能已与本地不同步。

**修复方案**：
1. **部署前自动拉取 VPS 配置**：通过 SFTP 读取 `/root/mory/config.json`
2. **深度合并配置**：以 VPS 配置优先，保留本地新增项
3. **特殊字段处理**：`_CONFIG_VERSION`、`_CONFIG_UPDATED` 等以本地为准
4. **写回本地并上传**：合并后的配置写回本地文件，再上传到 VPS

**代码位置**：`deploy_final.py` 第 47-110 行（步骤 0）

**验证**：下次执行“一键部署”时，观察控制台输出“备份并合并VPS配置”步骤，并检查合并后的 `config.json` 是否保留了 VPS 上的关键修改。

---

### [2026-04-18] SQL语法错误（CRLF问题）✅ 已解决

**问题**：Bot日志报错 `sqlite3.OperationalError: near "?": syntax error`

**根因**：VPS上database.py使用Windows行尾(CRLF)，导致多行SQL解析错误
```
第421行: c.execute("""UPDATE reply_tracking SET replied=1
                     WHERE chat_id=? AND replied=0 AND ts>? AND ts<?""",
实际显示: D ts<?""",  ← CR被当成字符串内容
```

**修复**：
1. 本地读取database.py
2. 转换为Unix行尾(content.replace('\r\n', '\n'))
3. SFTP上传覆盖VPS文件
4. 重启Bot

**验证**：
```bash
tail -50 /root/mory/mory.log  # 无SQL错误
ps aux | grep main.py          # Bot运行中
```

---

### [2026-04-18] 阅后即焚追踪污染 ✅ 已解决

**问题**：reply_tracking表为空，日志有user=0错误

**根因**：`auto_tasks.py` 的 `_send_and_track()` 调用了 `track_reply(user_msg_id=0)`

**修复**：
```python
# modules/auto_tasks.py - _send_and_track函数
def _send_and_track(rm, chat_id, text, user_msg_id=0):
    sent = rm.bot.send_message(chat_id, text)
    # 【修复v21.44】主动消息不追踪，避免污染reply_tracking表
    return sent
```

---

### [2026-04-18] 阅后即焚两大功能失效 ✅ 已解决

**问题**：
1. 孤儿消息不被清理
2. 原消息被删后bot回复不被删除

**根因**：
```python
# auto_mark_group_active() 把所有历史消息标记为 replied=1
c.execute("""UPDATE reply_tracking SET replied=1
             WHERE chat_id=? AND replied=0 AND ts<?""",
          (chat_id, before_ts))
# 导致 get_orphan_messages() 永远找不到 replied=0 的消息
```

**修复**：
1. `auto_mark_group_active()` 只标记10分钟内的消息
2. `get_orphan_messages()` 基于时间窗口判定
3. 新增 `refresh_tracked()` 更新时间戳

---

### [2026-04-18] Bot 409 Conflict冲突 ✅ 已解决

**问题**：多个Bot进程争用Telegram API

**修复**：
```bash
pkill -9 -f 'main.py'  # 终止所有进程
bash start.sh start    # 重新启动
```

---

## 🔧 调试命令备忘

### 检查Bot状态
```python
# SSH连接VPS
ssh root@43.159.168.175
# 密码: 066Sh9$YhG#Let

# 查看Bot进程
ps aux | grep main.py | grep -v grep

# 查看日志
tail -100 /root/mory/mory.log

# 检查reply_tracking表
cd /root/mory && sqlite3 mory.db "SELECT COUNT(*) FROM reply_tracking"
```

### 重启Bot
```bash
cd /root/mory
pkill -9 -f 'main.py'
nohup python3 main.py > bot.log 2>&1 &
```

### 从本地部署到VPS
```python
# 使用项目中的部署脚本
import paramiko
ssh = paramiko.SSHClient()
ssh.connect('43.159.168.175', username='root', password='066Sh9$YhG#Let')
# 上传文件后重启
```

---

## 📁 关键文件位置

| 文件 | 作用 | 备注 |
|------|------|------|
| main.py | 主程序入口 | 消息处理、阅后即焚追踪 |
| core/database.py | 数据库操作 | reply_tracking表操作 |
| modules/auto_tasks.py | 后台任务 | 孤儿清理、醋意挽回 |
| modules/admin_cmds.py | 管理命令 | 清群、踢人等 |
| config.json | 配置文件 | Bot配置、群ID等 |
| mory.db | SQLite数据库 | 所有数据存储 |

---

## 🚀 部署到VPS的命令

```bash
# 一键部署脚本
python vps_deploy.py
# 或
.\vps_one_click_update.bat update
```

---

## ⚠️ 注意事项

1. **修改database.py后要转LF行尾** - Windows默认CRLF会上传到VPS导致SQL错误
2. **Bot polling模式限制** - 无法访问群历史消息
3. **reply_tracking表为空是正常的** - 只有Bot回复群消息才会创建记录
4. **VPS有两个IP** - 43.159.168.175（旧）和 47.236.112.209（新）

---

---

## [2026-04-18] 文档结构整理

### 目标
根目录只保留核心文档，其他归档到docs/目录

### 执行
1. 根目录核心文档：
   - CHANGELOG.md - 更新日志
   - AI_DEBUG_HISTORY.md - 技术调试手册
   - README.md - 快速入口
2. docs/目录归档：
   - BACKUP_COMPARISON.md
   - backup_design.md
   - DATA_BACKUP_FINAL_GUIDE.md
   - final_checklist.md
   - PROJECT_SUMMARY.md
   - README.md
   - TECH_BUGFIX_GUIDE.md

---

---

## [2026-04-18] 全量代码诊断

### 执行
- VPS日志全量扫描
- 所有模块功能检查
- Bug分类整理

### 结果
- ✅ 所有核心Bug已修复
- ⚠️ 3个"错误"其实是Telegram平台限制，非代码Bug
- 📁 创建 FULL_BUG_ANALYSIS.md

---

### [2026-04-18 23:15] Bot@消息不回复问题 ✅ 已解决

**问题描述**：用户在群组中 @MoryMateBot 发消息，Bot 完全无响应

**排查过程**（按时间顺序）：
1. 检查 Privacy Mode → ✅ 已关闭，Bot 有管理员权限
2. 检查 Webhook/Pending Updates → ✅ 无冲突
3. 在 `_dispatch()` 入口添加 `[MSG_IN]` 全量 DEBUG 日志
4. 部署新代码到 VPS 并重启 Bot
5. **关键发现**：日志文件路径搞混了！VPS上有 `bot.log`、`mory.log`、`mory.log` 三个日志文件，正确的是 `/root/mory/mory.log`
6. **核心发现**：Bot 进程在启动后处理完一条消息就**静默退出**了
   - PID 文件存在（1900999），但进程已死
   - 日志停在 22:55:25 处理完"签到"后无任何新输出
   - **没有任何 ERROR/CRITICAL/Traceback 日志**
   - dmesg 也无 OOM killer 记录
7. 用 `bash start.sh start` 正确重启后：
   - **@MoryMateBot hello 立刻被接收并回复！**
   - 日志链路完整：MSG_IN → 阅后即焚追踪 → AI回复

**根因**：Bot 进程因未知原因静默退出（可能是之前部署操作 kill 后 nohup 重启失败），之后一直没有正确运行。**代码本身没有 bug！**

**修复措施**：
1. 在 `_dispatch()` 入口添加永久 `[MSG_IN]` DEBUG 日志
2. 正确使用 `start.sh start` 启动 Bot
3. 记住正确的日志路径：`/root/mory/mory.log`

**教训/备忘**：
- ⚠️ VPS 上有多个 .log 文件，**正确的运行日志是 `/root/mory/mory.log`**
- ⚠️ 检查 Bot 是否存活不能只看 PID 文件，要用 `kill -0 $(cat pid)` 验证
- ⚠️ 部署新代码后**必须验证进程是否真的在运行**

---

*最后更新：2026-04-19*

---

## [2026-04-19] v4.0.3 二次审计修复

### 发现的问题

**1. 消息路由"黑洞" - 独立 handler 独占消息**
- 根因：之前把 `global_reply_sniffer` 做成独立的 `@bot.message_handler`，pyTelegramBotAPI 的 handler 是独占式的，消息被嗅探器捕获后不会继续流转
- 教训：pyTelegramBotAPI 的 `func` 条件匹配后，消息不会自动流转到下一个 handler
- 修复：删除独立 handler，将嗅探逻辑内置于 `_dispatch()` 函数最开始处

**2. Dashboard 三重安全隐患**
- 根因：secret_key 每次重启随机生成、端口绑定 0.0.0.0、密码有默认提示值
- 修复：
  - secret_key 从环境变量读取，固定不变
  - 端口改为 127.0.0.1，强制要求 Nginx 反向代理
  - 密码无默认值提示，必须设置环境变量

**3. auto_tasks 空转浪费**
- 根因：`_job_burn_probe` 已降级为空函数，但每分钟依然被调度
- 修复：调度频率改为每5分钟一次

---

## [2026-04-19] v4.1.0 三次审计修复

### 发现的问题

**1. BaseMiddleware 中间件 - 解决"机器人眼瞎"问题**
- 问题：用户的图片/语音/贴纸回复不会被 `master_handler` 捕获
- 原因：`content_types=["text", "new_chat_members"]` 会过滤掉其他类型消息
- 解决方案：引入 `ReplySnifferMiddleware` 底层中间件
  - 继承自 `telebot.handler_backends.BaseMiddleware`
  - 在 `pre_process` 中拦截所有类型的消息
  - 在消息到达任何 handler 之前统一捕获回复嗅探
- 涉及：`main.py` 新增 `ReplySnifferMiddleware` 类 + `bot.setup_middleware(db)`

**2. 清理重复嗅探逻辑**
- 问题：`_dispatch` 函数中仍有嗅探代码，与中间件功能重复
- 解决：删除 `_dispatch` 中的嗅探代码，统一由中间件处理

**3. APScheduler Cron 语法确认**
- 确认：`minute="*/5"` 语法正确
- `_job_burn_probe` 已是空操作，不消耗 API 配额

---

## [2026-04-19] v4.1.1 审查驳回：拒绝无效重构

### 事件
收到声称来自"全栈软件架构中枢"的 v5.0 重构建议。

### 审查结论
**该报告存在致命错误，会让机器人重新变瞎！**

| 报告建议 | 实际后果 |
|----------|----------|
| 添加独立 `global_reply_listener` handler + `return False` | **重回黑洞问题！** pyTelegramBotAPI handler 独占消息 |
| 简化 `mory_bot.py` 删除追踪逻辑 | 破坏已有稳定架构 |

### 关键教训
1. **pyTelegramBotAPI handler 机制**：消息被一个 handler 捕获后，`return False` **不会**让消息继续流转到下一个 handler
2. **BaseMiddleware 是唯一解决方案**：必须在 `pre_process` 中拦截所有消息类型
3. **不要轻信"架构审查"**：即使是看似专业的报告，也要核实技术细节

### 执行操作
1. ✅ 驳回无效重构建议
2. ✅ 确认现有代码架构扎实
3. ✅ 清理调试碎片（删除 5 个 check_burn*.py）

---
