# Runbook: VPS 只读状态探针（vps-recon）

> 用途：任何涉及 VPS 服务 / 配置 / 进程的判断前，先拿实机证据，**禁止靠本地文件推断**。
> 安全铁律：本 runbook 只做只读探测，绝不 mutate（不 start / stop / rm / 写文件）。

## 触发场景
- 排查"某个服务属于哪个项目 / 是否真在跑"
- 部署前确认当前状态
- 任何关于 VPS 进程、端口、DB、目录的疑问

## 连接方式
优先复用 `core.vps_config.ssh_connect` 和现有只读探针；确需临时脚本时放系统临时目录或 `scripts/_probe.py`，任务结束即删且不得进入提交：

```python
import paramiko
from core.vps_config import ssh_connect

client = paramiko.SSHClient()
ssh_connect(client)

def run(client, cmd, timeout=30):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return rc, out, err

# ... 下面探测清单里的命令 ...
client.close()
```

跑完即删脚本，不入库。

## 只读探测清单（在 VPS 上执行）
```bash
# 1. 本仓库双核心服务状态、PID、重启计数 + 同机所有相关 unit
systemctl show mory-assistant mory-dashboard -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecMainStartTimestamp
systemctl list-unit-files --type=service | grep -iE 'mory|media|ops|coo|bot'

# 2. 进程（精确路径，禁止 pkill -f main.py）
ps -ef | grep -E '/home/ubuntu/mory_assistant/main.py|/opt/moryfansbot' | grep -v grep

# 3. 端口监听
ss -tlnp | grep -E ':6616|:6617|:17860'

# 4. 生产库是否被打开（NOT_OPEN = 无进程持有）
lsof -w | grep -E 'mory.db|mory_media.db' || echo NOT_OPEN

# 5. 同机项目目录与运行版本（health 不提供版本证据）
ls -la /home/ubuntu/ /opt/
cd /home/ubuntu/mory_assistant && /usr/bin/python3 -c 'from version import VERSION; print(VERSION)'
cd /home/ubuntu/mory_assistant && sha256sum version.py

# 6. 资源与进程压力
df -h / ; free -m ; nproc ; cat /proc/loadavg
ps -eo stat,ppid,pid,comm,args | awk '$1 ~ /^Z/ {print}' | head -50

# 7. 健康检查：保留响应体与状态码，仅判 liveness
curl -sS -w '\nHTTP=%{http_code}\n' localhost:6616/api/health

# 8. 数据库完整性与持久任务四态（task_execution_history 不是全量注册表）
cd /home/ubuntu/mory_assistant && sqlite3 mory.db 'PRAGMA integrity_check; PRAGMA foreign_key_check;'
cd /home/ubuntu/mory_assistant && sqlite3 mory.db "SELECT status,COUNT(*) FROM task_execution_history WHERE start_ts >= strftime('%s',datetime('now','-24 hours')) GROUP BY status;"
cd /home/ubuntu/mory_assistant && sqlite3 mory.db "SELECT COUNT(*),SUM(CASE WHEN fail_count>0 THEN 1 ELSE 0 END) FROM scheduler_metrics;"
journalctl -u mory-assistant --since '1 hour ago' --no-pager | grep -E 'Running job|ERROR|CRITICAL|Traceback' | tail -100

# 9. 权限与 root 执行链（只读，不输出凭据内容）
stat -c '%U:%G %a %n' /etc/systemd/system/mory-assistant.service /etc/systemd/system/mory-dashboard.service
stat -c '%U:%G %a %n' /home/ubuntu/mory_assistant/.env /home/ubuntu/mory_assistant/config.json /home/ubuntu/mory_assistant/mory.db
sudo -n crontab -l | grep -F 'vps_watchdog.py' || true
# 对上一步读到的真实脚本路径再 stat；禁止仅检查仓库同名文件
```

## 关键架构事实（判读时用）
- 本仓库 = `/home/ubuntu/mory_assistant`，双核心 `mory-assistant` + `mory-dashboard`。
- 媒体 / 宣发 Bot = **独立项目** `/opt/moryfansbot`（`bot.py` + `web_admin`），**不在本仓库**，读取本仓库 `mory.db` 的 `promotions` 表。
- 本仓库**无** `mory_media_assistant` 目录 / 服务（历史过期描述）。详见 `docs/technical/architecture-truth.md`。

## 输出
结构化报告必须区分：

1. **当前存活**：服务/PID/重启计数、端口、health 原文；
2. **版本与部署一致性**：VPS `version.py` 或受影响文件 hash；
3. **业务与调度 coverage**：真实业务探针、当前执行日志、事务四态、历史 metrics 分开标注；
4. **数据与安全**：DB 完整性、文件 owner/mode、root cron 真实目标；
5. **证据缺口**：journal 轮转、权限不足、缺少 sqlite3/业务探针时明确写 `evidence_gap`，不得回填成健康。

本地 `config.json` 不是生产运行配置真相；配置审计只比较键名/非敏感开关和 hash，不读取、复制或输出 Token/密码。
