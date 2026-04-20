# 🩺 AI_DEBUG_HISTORY.md · 调试病历本

> **本文件专门写给 AI 自己看。**
> 新会话开始时，AI 必须先读一遍此文件。

---

## ⚠️ 重要：项目上下文

### 基本信息
- **项目**：Mory小助理 - Telegram群管机器人
- **技术栈**：Python 3 + Telegram Bot API + SQLite
- **VPS**：43.159.168.175（腾讯云）
- **VPS路径**：/root/mory

### 关键路径
| 用途 | 路径 |
|------|------|
| Bot日志 | `/root/mory/mory.log` |
| 启动 | `bash start.sh start` |
| 停止 | `bash start.sh stop` |
| 重启 | `bash start.sh restart` |
| 日志 | `bash start.sh log` |

### 核心功能
1. **阅后即焚** - 由 `ReplySnifferMiddleware` 中间件捕获回复
2. **AI对话** - 基于通义千问
3. **自动任务** - 早安问候、新闻播报等

---

## ⚠️ pyTelegramBotAPI Handler 机制警示

**pyTelegramBotAPI 的 `@bot.message_handler` 是独占式的！**
- `return False` 不会让消息流转到下一个 handler
- **唯一正确方案**：`BaseMiddleware` 拦截所有消息

---

## ❌ 已知的平台限制（无法解决）

1. **群组历史消息无法访问** - Telegram API限制
2. **Bot主动私信403** - 用户必须先联系Bot

---

## 🩹 已修复的问题

### v4.2.1 | AI问候跑偏
- **现象**：早安/午安/晚安生成时事政治内容
- **原因**：prompt 太弱，没有强制包含关键词
- **方案**：加强 prompt，强制要求包含"早安"/"晚安"等关键词，并禁止时事政治内容

---

*最后更新：2026-04-20 v4.2.1*
