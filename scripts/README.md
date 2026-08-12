# Scripts

当前保留的都是还在用的运维脚本，不再保留那批一次性调试脚本说明。

## 脚本清单

| 脚本 | 用途 |
|------|------|
| cleanup_vps.py | 清理 VPS 上遗留的旧脚本和垃圾文件（基础版） |
| cleanup_vps_full.py | VPS 完整清理：垃圾文件 + __pycache__ + logrotate 配置 + journal 清理（v5.22.0 审计配套） |
| puzan_loop_monitor.py | 本地 6 层生产巡检：VPS / systemd / health / 业务指标 / 调度 / watchdog + 腾讯云状态，支持 `--once` 和 `--loop` |
| project_audit_control.py | 项目内只读巡检控制面：`production-truth` / `drift` / `monthly` / `all`，统一 JSON 回执及退出码 0/2/3 |
| manage_project_audit_timers.py | systemd timer 定义的 plan/install/verify/uninstall 入口；默认 plan，install/uninstall 必须显式 `--apply` |
| restart_bot.py | 远端重启 Bot 服务 |
| restore_after_reinstall.py | VPS 重装后恢复项目运行态 |
| ssh_helper.py | 统一 SSH 连接与命令执行辅助 |
| vps_watchdog.py | VPS 端外部看门狗：root cron 每 2 分钟检查 `/api/health`，连续 3 次失败重启 `mory-assistant` |

`health_check.py` / `auto_rollback.py` / `rollback_config.json` 已移除：旧入口会把 health 200 当整体健康，甚至自动停服务换目录，与当前只读取证控制面冲突。
