# VERSION

## 2026-04-29

- 增加服务器重装后一键恢复能力。
- 增加 Windows PowerShell `8009001d` 启动失败修复脚本。
- 完成 Ubuntu 24.04 VPS 生产恢复部署。
- 完成 VPS SSH 密码轮换同步与服务重启验证。
- 完成本项目 Telegram Bot Token 统一与多项目服务器边界记录。

## 2026-04-30

- 明确生产进程管理红线：`mory_assistant` 只允许 systemd 管理（禁止 pm2 / `bash start.sh start` / 手动启动 `python main.py`），避免 Telegram `409 Conflict`。
- 记录后台任务防冲突环境变量 `BOT_ROLE` 与同机 `mory_media_assistant` 读取 `promotions` 表的协作边界。
