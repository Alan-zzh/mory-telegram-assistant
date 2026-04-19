# 📝 CHANGELOG · Mory 更新日志

---

## 2026-04-19 | v4.2.0 | 项目全面精简

### 清理内容
- 归档 111 个调试脚本和文档到 `_archive_scripts/`
- 删除 `docs/`、`backup_deploy/`、`scripts/` 目录
- 删除所有 `.pyc` 编译缓存
- 精简根目录批处理文件
- 创建 `.gitignore` 忽略运行时文件

### 驳回错误的"架构重构"建议
- pyTelegramBotAPI handler 独占机制，`return False` 不生效
- 使用 `BaseMiddleware` 是唯一正确方案

---

## 2026-04-19 | v4.1.0 | 架构级修复

### 核心修复
- `ReplySnifferMiddleware` 中间件解决"机器人眼瞎"问题
- 清理重复嗅探逻辑
- APScheduler Cron 语法修正

---

## 早期版本

详见 `_archive_scripts/docs/CHANGELOG.md`（归档）
