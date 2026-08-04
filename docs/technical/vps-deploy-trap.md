# VPS 部署陷阱详解

> 本文档为独立技术说明，未被 AGENTS.md 直接索引 · 适用版本：v5.0.0+
> **最后更新**：2026-06-02（v5.12.1 .agents→AGENTS.md）

## 概述

Mory 小助理部署到腾讯云硅谷 VPS（43.159.168.175, ubuntu@22.04）。部署过程中反复踩过 8 大类陷阱，本文档逐一记录**现象 + 诊断命令 + 修复方案**。

## 适用场景

- 部署失败时按"陷阱清单"逐个排查
- 接手 VPS 运维时先读本文档建立认知
- 写新部署脚本时对照本文档避免重蹈覆辙

## 关键内容

### 一、VPS 环境约定

| 项 | 值 | 说明 |
|----|-----|------|
| 用户 | `ubuntu` | **禁止用 root**（root 上传的文件 ubuntu 无权限） |
| 项目路径 | `/home/ubuntu/mory_assistant/` | 固定 |
| Python | 3.10+ | systemd 启动用 `/usr/bin/python3` |
| 进程管理 | systemd | 禁止 start.sh / nohup |
| Dashboard 端口 | 6616 | 环境变量 `DASHBOARD_PORT` |
| Bot 模式 | 轮询（polling） | 不开 webhook |
| 数据库 | `mory.db` (SQLite WAL) | **禁止上传/覆盖** |
| 配置文件 | `config.json` + `.env` | 都 `.gitignore` |

### 二、陷阱清单（8 大类）

#### 陷阱 1：文件 owner 错乱（最高频）

- **现象**：`PermissionError: [Errno 13] Permission denied`（deploy_vps.py 第4步"上传代码文件"）
- **根因**：VPS 上 `core/modules/dashboard` 下的 .py 文件 owner 是 `root:root`（历史 sudo 操作造成），但 deploy_vps.py 用 `ubuntu` 用户连接 SFTP，权限不足无法覆盖
- **诊断**：
  ```bash
  # 找非 ubuntu owner 的 .py 文件
  find /home/ubuntu/mory_assistant -name "*.py" -not -user ubuntu
  ```
- **修复**：
  ```bash
  sudo chown -R ubuntu:ubuntu /home/ubuntu/mory_assistant/core \
                            /home/ubuntu/mory_assistant/modules \
                            /home/ubuntu/mory_assistant/dashboard
  sudo chown ubuntu:ubuntu /home/ubuntu/mory_assistant/main.py \
                          /home/ubuntu/mory_assistant/version.py \
                          /home/ubuntu/mory_assistant/start_dashboard.py \
                          /home/ubuntu/mory_assistant/windows_helper.py
  ```
- **预防**：`deploy_vps.py` 应在第1步（连接VPS）后插入自动 chown

#### 陷阱 2：systemd 缺 EnvironmentFile

- **现象**：`VPS_PASSWORD / DASHBOARD_PASSWORD / TELEGRAM_BOT_TOKEN` 取不到，Dashboard 登录失败
- **根因**：`mory-assistant.service` / `mory-dashboard.service` 没加 `EnvironmentFile=.env`
- **诊断**：
  ```bash
  grep EnvironmentFile /etc/systemd/system/mory-assistant.service
  grep EnvironmentFile /etc/systemd/system/mory-dashboard.service
  ```
- **修复**：
  ```ini
  # /etc/systemd/system/mory-assistant.service
  [Service]
  User=ubuntu
  EnvironmentFile=/home/ubuntu/mory_assistant/.env
  ExecStart=/usr/bin/python3 main.py
  Restart=always
  ```
  ```bash
  sudo systemctl daemon-reload
  sudo systemctl restart mory-assistant
  ```

#### 陷阱 3：config.json 缺新键

- **现象**：本地新增配置键后部署到 VPS，VPS 的 `config.json` 缺少新键，运行时 `KeyError: 'NEW_KEY'` 或 `config['NEW_KEY']` 崩
- **根因**：VPS 的 `config.json` 是历史文件，不会自动同步
- **诊断**：
  ```python
  # 对比 example 和 VPS config 的键数
  import json
  example = set(json.load(open('config.json.example')).keys())
  vps = set(json.load(open('/home/ubuntu/mory_assistant/config.json')).keys())
  print('example 有但 vps 无:', example - vps)  # 部署后应为空
  ```
- **修复**：`core/deploy_utils.py` 的 `safe_upload_config()` 已实现 `_patch_missing_keys()`，从 `config.json.example` 自动合并缺失键。**必须用 `safe_upload_config()` 上传**，禁止 `sftp.put('config.json', ...)` 直接覆盖（会清空 token）

#### 陷阱 4：mory.db 被覆盖（数据丢失！）

- **现象**：部署后用户数据（积分、签到、消息历史）全部丢失
- **根因**：`sftp.put('mory.db', ...)` 直接覆盖 VPS 数据库
- **诊断**：
  ```bash
  # 对比部署前后文件大小
  ls -la mory.db
  ```
- **修复**：
  - 部署只上传代码（`core/ modules/ dashboard/ *.py`）
  - **永远不要 sftp.put mory.db**
  - 如果 db 损坏，从 VPS 备份恢复（不是本地）
  - `deploy_vps.py` 已实现 `upload_files()` 自动跳过 `*.db`

#### 陷阱 5：多进程 409 Conflict

- **现象**：Bot 启动后立刻 `telegram.error.Conflict: terminated by other getUpdates request`
- **根因**：`start.sh` 和 systemd 双启同一个 Bot，或 nohup 残留进程
- **诊断**：
  ```bash
  ps -ef | grep '/home/ubuntu/mory_assistant/main.py' | grep -v grep
  ```
- **修复**：
  - 统一用 systemd：`sudo systemctl start/stop/restart mory-assistant`
  - 禁止 `start.sh` / `nohup python main.py &`
  - 杀残留进程：`sudo pkill -f '/home/ubuntu/mory_assistant/main.py'`
  - systemd `Restart=always` 兜底，崩了自动重启

#### 陷阱 6：Dashboard HTTP 无法登录

- **现象**：Dashboard 登录页提交后无反应
- **根因**：`dashboard/auth.py` 中 `SESSION_COOKIE_SECURE=True` 硬编码，HTTP 下 Cookie 不发送
- **诊断**：
  ```bash
  # 看是否是 HTTP
  curl -I http://localhost:6616
  # 看 auth.py
  grep SESSION_COOKIE_SECURE dashboard/auth.py
  ```
- **修复**：
  ```python
  # dashboard/auth.py
  SESSION_COOKIE_SECURE = os.environ.get('DASHBOARD_HTTPS', 'false').lower() == 'true'
  ```
  ```bash
  # .env
  DASHBOARD_HTTPS=false  # 不用 HTTPS 时
  ```

#### 陷阱 7：多 Bot 混淆误杀进程（路径精确匹配）

- **现象**：`pkill -f main.py` 误杀了同机其他 Bot 进程。
- **架构真相（2026-07-07 修订）**：VPS 上除本仓库 `mory_assistant`（`/home/ubuntu/mory_assistant`，双核心 `mory-assistant`+`mory-dashboard`）外，媒体/宣发 Bot 是**独立项目** `/opt/moryfansbot`（`bot.py` + `web_admin`），**不在本仓库**，且读取本仓库 `mory.db` 的 `promotions` 表做定时广播。本仓库**不存在** `mory_media_assistant` 目录/服务（该名称是历史过期描述，详见 `docs/technical/architecture-truth.md`）。
- **根因**：同机多 Bot 路径前缀相似（`/home/ubuntu/mory_assistant` vs `/opt/moryfansbot`），模糊匹配会跨项目误杀。
- **诊断**：
  ```bash
  # 精确匹配本仓库主进程
  ps -ef | grep '/home/ubuntu/mory_assistant/main.py' | grep -v grep
  # 独立宣发 Bot（另一项目，勿动）
  ps -ef | grep '/opt/moryfansbot' | grep -v grep
  ```
- **修复**：
  - 操作 `mory_assistant` 时**必须精确匹配完整路径**，禁止模糊 `pkill -f main.py`。
  - `/opt/moryfansbot` 是独立部署，排查/重启须到该目录，不要在本仓库动手。
  - 部署脚本 `deploy_vps.py` 只管本仓库双核心服务，不涉及 `/opt/moryfansbot`。

#### 陷阱 8：依赖缺失

- **现象**：`ModuleNotFoundError: No module named 'xxx'`
- **根因**：VPS 上没装某些 Python 依赖
- **诊断**：
  ```bash
  python3 -c "import telegram, apscheduler, flask, paramiko"  # 任一失败即依赖缺失
  ```
- **修复**：
  ```bash
  cd /home/ubuntu/mory_assistant && pip3 install -r requirements.txt
  ```

### 三、部署前 checklist

执行 `python deploy_vps.py` 前必查：

- [ ] 本地代码 `python -m py_compile` 无语法错误
- [ ] 本地测试 `scripts/verify_orphan_cleanup.py` 通过
- [ ] `config.json.example` 与代码 `config.get('KEY', default)` 键数一致
- [ ] `.env.example` 列了所有需要的 KEY
- [ ] `CHANGELOG.md` / `VERSION.md` 已更新
- [ ] `AI_DEBUG_HISTORY.md` 记录了新的失败/坑

### 四、部署后 5 大验证

`deploy_vps.py` 自动执行，也可手动 SSH 验证：

```bash
# 1. Bot 进程
sudo systemctl is-active mory-assistant  # 期望：active

# 2. Dashboard 进程
sudo systemctl is-active mory-dashboard  # 期望：active

# 3. Dashboard HTTP 200
curl -I http://localhost:6616  # 期望：HTTP/1.1 200 OK

# 4. 错误日志（无 error/exception）
sudo journalctl -u mory-assistant --since "1 hour ago" 2>&1 | \
  grep -iE "error|exception|traceback" | tail -10
# 期望：（无）或只有已知无害日志
# 5. config.json 键完整
python3 -c "import json; e=set(json.load(open('config.json.example'))); v=set(json.load(open('config.json'))); print('缺:', e-v)"
```

### 五、SSH 快速诊断脚本

```python
import paramiko
from core.vps_config import VPS_HOST, VPS_PASS, VPS_USER, VPS_PATH, ssh_connect

c = paramiko.SSHClient()
ssh_connect(c, timeout=15)

# 综合诊断
for cmd in [
    "systemctl is-active mory-assistant",
    "systemctl is-active mory-dashboard",
    "find /home/ubuntu/mory_assistant -name '*.py' -not -user ubuntu | wc -l",
    "grep -c EnvironmentFile /etc/systemd/system/mory-assistant.service",
    "ps -ef | grep '/home/ubuntu/mory_assistant/main.py' | grep -v grep | wc -l",
]:
    stdin, stdout, stderr = c.exec_command(cmd, timeout=10)
    out = stdout.read().decode().strip()
    print(f"{cmd[:60]}: {out}")
```

### 六、历史坑（病历本摘要）

| 版本 | 现象 | 根因 | 修复 |
|------|------|------|------|
| v5.10.3 | root/ubuntu 双用户权限冲突 | vps_config.py 默认用户 root | 改 ubuntu |
| v5.11.0 | deploy_vps.py PermissionError | 历史 sudo 导致文件 owner 错乱 | `sudo chown -R ubuntu:ubuntu` |
| v5.10.2 | Dashboard HTTP 无法登录 | SESSION_COOKIE_SECURE 硬编码 True | 改环境变量驱动 |
| v5.10.2 | 配置变更 Bot 不生效 | 无热重载机制 | reload_flag + 5秒轮询 |

## 引用

- [AGENTS.md](../../AGENTS.md) — 部署/VPS 铁律精简版
- [anti-patterns-ops.md](anti-patterns-ops.md) — 部署一致性 6 条铁律完整版
- [orphan-cleanup.md](orphan-cleanup.md) — 孤儿消息清理机制

## 更新历史

- 2026-06-02 (v5.12.0) 首次创建 / 记录 VPS 部署 8 大陷阱
- 2026-06-02 (v5.12.1) 活跃引用从 `.agents` 更新为 `AGENTS.md`（大写显式）
