# Scripts

当前保留的都是还在用的运维脚本，不再保留那批一次性调试脚本说明。

## 脚本清单

| 脚本 | 用途 |
|------|------|
| cleanup_vps.py | 清理 VPS 上遗留的旧脚本和垃圾文件（基础版） |
| cleanup_vps_full.py | VPS 完整清理：垃圾文件 + __pycache__ + logrotate 配置 + journal 清理（v5.22.0 审计配套） |
| restart_bot.py | 远端重启 Bot 服务 |
| restore_after_reinstall.py | VPS 重装后恢复项目运行态 |
| ssh_helper.py | 统一 SSH 连接与命令执行辅助 |
