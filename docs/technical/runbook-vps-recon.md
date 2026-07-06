# Runbook: VPS 只读状态探针（vps-recon）

> 用途：任何涉及 VPS 服务 / 配置 / 进程的判断前，先拿实机证据，**禁止靠本地文件推断**。
> 安全铁律：本 runbook 只做只读探测，绝不 mutate（不 start / stop / rm / 写文件）。

## 触发场景
- 排查"某个服务属于哪个项目 / 是否真在跑"
- 部署前确认当前状态
- 任何关于 VPS 进程、端口、DB、目录的疑问

## 连接方式
临时脚本放 `scripts/_probe.py`，用 `core.vps_config.ssh_connect`（需先 `paramiko.SSHClient()`）：

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
# 1. 本仓库双核心服务状态 + 同机所有相关 unit
systemctl status mory-assistant mory-dashboard --no-pager
systemctl list-unit-files --type=service | grep -iE 'mory|media|ops|coo|bot'

# 2. 进程（精确路径，禁止 pkill -f main.py）
ps -ef | grep -E '/home/ubuntu/mory_assistant/main.py|/opt/moryfansbot' | grep -v grep

# 3. 端口监听
ss -tlnp | grep -E ':6616|:6617|:17860'

# 4. 生产库是否被打开（NOT_OPEN = 无进程持有）
lsof -w | grep -E 'mory.db|mory_media.db' || echo NOT_OPEN

# 5. 同机项目目录
ls -la /home/ubuntu/ /opt/

# 6. 资源
df -h / ; free -m

# 7. 健康检查
curl -s -o /dev/null -w '%{http_code}\n' localhost:6616/api/health
```

## 关键架构事实（判读时用）
- 本仓库 = `/home/ubuntu/mory_assistant`，双核心 `mory-assistant` + `mory-dashboard`。
- 媒体 / 宣发 Bot = **独立项目** `/opt/moryfansbot`（`bot.py` + `web_admin`），**不在本仓库**，读取本仓库 `mory.db` 的 `promotions` 表。
- 本仓库**无** `mory_media_assistant` 目录 / 服务（历史过期描述）。详见 `docs/technical/architecture-truth.md`。

## 输出
结构化报告：服务状态、进程、端口、DB 持有、目录清单、health，每条带命令与原始输出作为证据。
