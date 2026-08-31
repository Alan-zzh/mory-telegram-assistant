# AI 调试病历溢出归档（2026-08-31）

> 从根目录 `AI_DEBUG_HISTORY.md` 按 50 条上限迁出；内容完整保留。

### 68. 启动成员扫描把 API 参数错误吞成零人成功
- 问题|根因|解法|预防：旧任务曾零人假成功，后续又混淆 username/消息证据及 Bot API 400/Profile 失败。扫描现隔离证据、限速并发，并分层门禁成员/Profile/评估/真实传输覆盖；个人频道增强不可用单列，生产先报告再复核处置。

### 66. SSH helper sudo PTY 回显与命令引用失真
- 问题|根因|解法|预防：root 分支分配 PTY 可能回显 stdin 密码，且用 Python repr 拼 Bash 多行/单引号命令会语法失败；改为无 PTY 的 sudo -S、POSIX shlex 引用与统一脱敏，并用 mock、真实 UID 和多行探针固定边界。
