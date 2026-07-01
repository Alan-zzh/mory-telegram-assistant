#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Puzan OS Loop 6 层监控脚本 - v5.31.2

只读 VPS 监控，6 层 + 腾讯云 Lighthouse API：
  L1 VPS 实例层（CPU/MEM/DISK/LOAD/NET）
  L2 服务进程层（systemd 双 active + journalctl 错误）
  L3 应用健康层（/api/health + version 校验）
  L4 业务指标层（task_log/token_usage/llm_cost/conversion/orphan）
  L5 调度系统层（scheduler 日志 + 失败/运行中任务）
  L6 看门狗层（watchdog.log + v5312_monitor.log + cron）

用法：
  python scripts/puzan_loop_monitor.py                 # 6 轮，每轮 5 分钟
  python scripts/puzan_loop_monitor.py --once           # 仅 1 轮（基线）
  python scripts/puzan_loop_monitor.py --start-round 2 --rounds 5  # 从第 2 轮开始跑 5 轮

铁律：只读、不重启、不上传 db/config、凭据从 .env、异常先查病历。
"""
import os
import sys
import time
import json
import argparse
import traceback
import subprocess
import atexit
from pathlib import Path
from datetime import datetime, timezone, timedelta

import paramiko
from dotenv import dotenv_values

# ============ 常量 ============
_CST = timezone(timedelta(hours=8))
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_PATH = PROJECT_ROOT / ".env"
LOGS_DIR = PROJECT_ROOT / "logs"
LOCK_FILE = LOGS_DIR / ".puzan_loop_monitor.lock"
DEBUG_HISTORY = PROJECT_ROOT / "AI_DEBUG_HISTORY.md"
EXPECTED_VERSION = "v5.31.2"
HEALTH_URL = "http://localhost:6616/api/health"
MORY_DB = "/home/ubuntu/mory_assistant/mory.db"
ROUTER_DB = "/home/ubuntu/mory_assistant/data/router_usage.db"

# ============ .env 加载 ============
_env = dotenv_values(ENV_PATH)
HOST = _env.get("VPS_HOST", "")
PORT = int(_env.get("VPS_PORT", "22") or "22")
USER = _env.get("VPS_USER", "ubuntu")
PASS = _env.get("VPS_SSH_PASS", "")
REMOTE = _env.get("VPS_PATH", "/home/ubuntu/mory_assistant")
TC_SECRET_ID = _env.get("TENCENT_CLOUD_SECRET_ID", "")
TC_SECRET_KEY = _env.get("TENCENT_CLOUD_SECRET_KEY", "")
TC_INSTANCE_ID = "lhins-4ney4np5"
TC_REGION = _env.get("TENCENT_CLOUD_REGION", "na-siliconvalley")


def _is_process_alive(pid):
    """跨平台判断 PID 是否存活。
    - Windows 不支持 os.kill(pid, 0)，用 tasklist 判断。
    - Linux/macOS 用 os.kill(pid, 0)。
    """
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            return str(pid) in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def ensure_singleton():
    """单例锁：防止多个 Loop 监控实例并发写入同一日志。
    发现已存活实例则退出；发现残留锁文件则清理后继续。"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
            if old_pid and _is_process_alive(old_pid):
                print(f"[ERROR] 另一 Loop 监控实例正在运行 (PID={old_pid})，本次启动中止。"
                      f"如需重启，请先终止该进程。")
                sys.exit(1)
            else:
                print(f"[WARN] 发现残留锁文件 PID={old_pid}，进程已不存在，清理后继续。")
                LOCK_FILE.unlink(missing_ok=True)
        except Exception as e:
            print(f"[WARN] 锁文件状态异常，清理后重试: {e}")
            LOCK_FILE.unlink(missing_ok=True)
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(lambda: LOCK_FILE.unlink(missing_ok=True))


def now_cst_str():
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S CST")


def log_path():
    """当前监控日志路径（按启动时间命名）"""
    return LOGS_DIR / f"puzan_loop_monitor_{datetime.now(_CST).strftime('%Y%m%d_%H%M')}.log"


# ============ SSH 连接 ============
def make_ssh_client():
    """创建一个 SSH client（每次复用，避免每次命令都新建连接）"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST, PORT, USER, PASS,
        timeout=15, banner_timeout=15, auth_timeout=15,
        allow_agent=False, look_for_keys=False,
    )
    return client


def ssh_run(client, cmd, timeout=30):
    """执行 SSH 命令，返回 (stdout, stderr, exit_code)。异常时返回空串 + 错误信息。"""
    try:
        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=True)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return out.strip(), err.strip(), code
    except Exception as e:
        return "", f"ssh exec failed: {e}", -1


def sqlite_query(client, db_path, sql, timeout=20):
    """在 VPS 上用 sqlite3 查询，返回 (rows_str, error)"""
    # 用 -separator '|' 简化解析
    cmd = f'sqlite3 -separator "|" "{db_path}" "{sql}"'
    out, err, code = ssh_run(client, cmd, timeout=timeout)
    if code != 0:
        return "", f"sqlite3 err code={code}: {err or out}"
    return out, ""


# ============ L1 VPS 实例层 ============
def l1_vps_check(client):
    details = {}
    status = "OK"
    try:
        # CPU/进程
        top, _, _ = ssh_run(client, "top -bn1 | head -20", timeout=15)
        details["top_head"] = top
        # 提取 CPU idle / mem 行（粗解析）
        cpu_line = ""
        mem_line = ""
        for line in top.splitlines():
            if line.startswith("%Cpu") or line.startswith("Cpu(s)"):
                cpu_line = line
            elif line.startswith("MiB Mem") or line.startswith("KiB Mem"):
                mem_line = line
        details["cpu_line"] = cpu_line
        details["mem_line"] = mem_line

        # 内存
        free_m, _, _ = ssh_run(client, "free -m", timeout=10)
        details["free_m"] = free_m
        # 磁盘
        df_h, _, _ = ssh_run(client, "df -h / /home", timeout=10)
        details["disk"] = df_h
        # 连接数
        conn, _, _ = ssh_run(client, "ss -tn state established | wc -l", timeout=10)
        details["net_conn"] = conn.strip()
        # 负载
        uptime_o, _, _ = ssh_run(client, "uptime", timeout=10)
        loadavg_o, _, _ = ssh_run(client, "cat /proc/loadavg", timeout=10)
        details["uptime"] = uptime_o
        details["loadavg"] = loadavg_o

        # 提取关键指标
        cpu_usage = ""
        if cpu_line:
            try:
                # %Cpu(s): 13.6 us,  4.5 sy,  0.0 ni, 77.3 id, ...
                idle_match = [x for x in cpu_line.split(",") if "id" in x]
                if idle_match:
                    idle_val = float(idle_match[0].strip().split()[0])
                    cpu_usage = f"{100.0 - idle_val:.1f}%"
                    details["cpu_usage"] = cpu_usage
            except Exception:
                pass

        mem_avail_pct = ""
        if free_m:
            for line in free_m.splitlines():
                if line.startswith("Mem:"):
                    parts = line.split()
                    if len(parts) >= 7:
                        try:
                            total_mb = int(parts[1])
                            avail_mb = int(parts[6])
                            if total_mb > 0:
                                mem_avail_pct = f"{avail_mb / total_mb * 100:.1f}%"
                                details["mem_avail_pct"] = mem_avail_pct
                                if avail_mb / total_mb < 0.10:
                                    status = "WARN"
                                    details["_warn"] = details.get("_warn", "") + f"mem_avail_low({avail_mb}MB); "
                        except ValueError:
                            pass

        disk_usage_pct = ""
        if df_h:
            for line in df_h.splitlines():
                if line.startswith("/dev/"):
                    parts = line.split()
                    if len(parts) >= 5:
                        try:
                            use_pct = int(parts[4].rstrip("%"))
                            disk_usage_pct = f"{use_pct}%"
                            details["disk_usage_pct"] = disk_usage_pct
                            if use_pct > 90:
                                status = "WARN"
                                details["_warn"] = details.get("_warn", "") + f"disk_usage_high({use_pct}%); "
                        except ValueError:
                            pass

        load1 = ""
        if loadavg_o:
            load1 = loadavg_o.split()[0]
            details["load1"] = load1
            try:
                if float(load1) > 5.0:
                    status = "WARN"
                    details["_warn"] = details.get("_warn", "") + f"load1_high({load1}); "
            except ValueError:
                pass
    except Exception as e:
        status = "ERROR"
        details["_exc"] = f"{type(e).__name__}: {e}"
    return status, details


# ============ L2 服务进程层 ============
def l2_service_check(client):
    details = {}
    status = "OK"
    try:
        mory_active, _, c1 = ssh_run(client, "systemctl is-active mory-assistant", timeout=10)
        dash_active, _, c2 = ssh_run(client, "systemctl is-active mory-dashboard", timeout=10)
        details["mory-assistant"] = mory_active.strip()
        details["mory-dashboard"] = dash_active.strip()
        if mory_active.strip() != "active" or dash_active.strip() != "active":
            status = "CRITICAL"
            details["_crit"] = "service_not_active"

        # 详细状态
        sa, _, _ = ssh_run(client, "systemctl status mory-assistant --no-pager | head -25", timeout=10)
        sd, _, _ = ssh_run(client, "systemctl status mory-dashboard --no-pager | head -25", timeout=10)
        details["mory-assistant_status"] = sa
        details["mory-dashboard_status"] = sd

        # journalctl 错误过滤（注意：grep "ERROR" 会误匹配 EXECUTED/ERROR/MISSED，需排除）
        # 用 grep -E "error|critical|exception|traceback" -i，再排除 EXECUTED/MISSED 这种正常调度事件
        err_a, _, _ = ssh_run(
            client,
            r'journalctl -u mory-assistant --since "10 minutes ago" --no-pager '
            r'| grep -iE "error|critical|exception|traceback" '
            r'| grep -viE "EXECUTED|ERROR.*MISSED|EVENT_JOB_|scheduler_monitor.*EVENT|_job_critical|critical_jobs_health" '
            r'| tail -20',
            timeout=15,
        )
        err_d, _, _ = ssh_run(
            client,
            r'journalctl -u mory-dashboard --since "10 minutes ago" --no-pager '
            r'| grep -iE "error|critical|exception|traceback" '
            r'| tail -20',
            timeout=15,
        )
        details["mory-assistant_errors_10min"] = err_a or "(none)"
        details["mory-dashboard_errors_10min"] = err_d or "(none)"
        if err_a:
            status = "WARN" if status != "CRITICAL" else "CRITICAL"
            details["_warn"] = details.get("_warn", "") + "mory-assistant_has_errors; "
    except Exception as e:
        status = "ERROR"
        details["_exc"] = f"{type(e).__name__}: {e}"
    return status, details


# ============ L3 应用健康层 ============
def l3_app_check(client):
    """health/version/uptime 都从 /api/health 一个端点解析（health_api.py 仅暴露 /health 路由）"""
    details = {}
    status = "OK"
    try:
        # health（响应内含 status + version）
        h, _, _ = ssh_run(client, f"curl -s -m 5 {HEALTH_URL}", timeout=10)
        details["health_raw"] = h[:300]
        home_code, _, _ = ssh_run(
            client,
            f'curl -s -m 5 -o /dev/null -w "%{{http_code}}" http://localhost:6616/',
            timeout=10,
        )
        details["home_http_code"] = home_code.strip()

        # 从 health 响应解析 version（响应形如 {"status":"ok","version":"v5.31.2"}）
        ver_ok = False
        ver = ""
        if h:
            try:
                vj = json.loads(h)
                ver = vj.get("version") or vj.get("data", {}).get("version", "")
            except Exception:
                # 非合法 JSON，尝试文本匹配
                pass
            if not ver:
                # 文本搜索 v5.xx
                import re
                m = re.search(r"v\d+\.\d+\.\d+", h)
                if m:
                    ver = m.group(0)
            details["version"] = ver
            ver_ok = (ver == EXPECTED_VERSION)
        if not ver_ok:
            status = "WARN"
            details["_warn"] = details.get("_warn", "") + f"version_mismatch(expect={EXPECTED_VERSION}, got={ver or 'none'}); "

        # health 校验
        if '"ok"' not in h.lower() and '"status":"ok"' not in h.lower().replace(" ", ""):
            status = "CRITICAL"
            details["_crit"] = "health_not_ok"
        if home_code.strip() != "200":
            status = "WARN" if status != "CRITICAL" else "CRITICAL"
            details["_warn"] = details.get("_warn", "") + f"home_code={home_code.strip()}; "
    except Exception as e:
        status = "ERROR"
        details["_exc"] = f"{type(e).__name__}: {e}"
    return status, details


# ============ L4 业务指标层 ============
def l4_biz_check(client):
    """schema 参考 core/database.py + AI_DEBUG_HISTORY.md Loop 13/6：
      - task_log: id, task_key, exec_date, exec_ts(REAL, 秒级 Unix 时间) - 无 status 列（只记成功执行）
      - token_usage（router_usage.db）: timestamp(TEXT, datetime isoformat) - 非 created_at
      - llm_cost_logs（mory.db）: timestamp(REAL/INTEGER, 秒级 Unix 时间)，成本熔断器刷盘日志
      - conversion_events: ts(REAL, 毫秒)
      - orphan_cleanup_log: run_at(INTEGER, 秒) - 非 ts
    """
    details = {}
    status = "OK"
    try:
        # task_log 最近 1h / 5min（exec_ts 秒级 Unix 时间）
        q1h, e1 = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM task_log WHERE exec_ts >= strftime('%s', datetime('now', '-1 hour'));",
        )
        details["task_1h"] = q1h.strip() if not e1 else f"ERR: {e1}"
        q5m, e5 = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM task_log WHERE exec_ts >= strftime('%s', datetime('now', '-5 minutes'));",
        )
        details["task_5min"] = q5m.strip() if not e5 else f"ERR: {e5}"
        # task_log 无 status 列，只查 task_key/exec_date/exec_ts
        recent, er = sqlite_query(
            client, MORY_DB,
            "SELECT task_key, exec_date, exec_ts FROM task_log ORDER BY id DESC LIMIT 10;",
        )
        details["recent_tasks"] = recent if not er else f"ERR: {er}"

        # router_usage.db: token_usage（timestamp 列为带 +08:00 的 ISO 字符串）。
        # 用 strftime('%s', timestamp) 统一转 UTC epoch，避免 CST/UTC 字符串互比错位。
        tu, et = sqlite_query(
            client, ROUTER_DB,
            "SELECT COUNT(*) FROM token_usage WHERE CAST(strftime('%s', timestamp) AS INTEGER) >= CAST(strftime('%s', 'now', '-1 hour') AS INTEGER);",
        )
        details["token_usage_1h"] = tu.strip() if not et else f"ERR: {et}"

        tu5, et5 = sqlite_query(
            client, ROUTER_DB,
            "SELECT COUNT(*) FROM token_usage WHERE CAST(strftime('%s', timestamp) AS INTEGER) >= CAST(strftime('%s', 'now', '-5 minutes') AS INTEGER);",
        )
        details["token_usage_5min"] = tu5.strip() if not et5 else f"ERR: {et5}"

        # LLM 请求用量成本：router_usage.db.token_usage.cost
        lc, el = sqlite_query(
            client, ROUTER_DB,
            "SELECT COALESCE(SUM(cost),0) FROM token_usage WHERE CAST(strftime('%s', timestamp) AS INTEGER) >= CAST(strftime('%s', 'now', '-1 hour') AS INTEGER);",
        )
        details["token_cost_1h_sum"] = lc.strip() if not el else f"ERR: {el}"

        # 成本熔断器刷盘成本：mory.db.llm_cost_logs.estimated_cost
        guard_cost, guard_err = sqlite_query(
            client, MORY_DB,
            "SELECT COALESCE(SUM(estimated_cost),0) FROM llm_cost_logs WHERE timestamp >= strftime('%s', datetime('now', '-1 hour'));",
        )
        details["guard_cost_1h_sum"] = guard_cost.strip() if not guard_err else f"ERR: {guard_err}"
        lce, _ = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM llm_cost_logs;",
        )
        details["llm_cost_logs_count"] = lce.strip() if lce.strip() else "0"

        # conversion_events（ts 毫秒）
        cv, ec = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM conversion_events WHERE ts >= strftime('%s', datetime('now', '-1 hour'))*1000;",
        )
        details["conversion_1h"] = cv.strip() if not ec else f"ERR: {ec}"

        # orphan_cleanup_log（run_at 列，秒级 INTEGER）
        oc, eo = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM orphan_cleanup_log WHERE run_at >= strftime('%s', datetime('now', '-1 hour'));",
        )
        details["orphan_1h"] = oc.strip() if not eo else f"ERR: {eo}"

    except Exception as e:
        status = "ERROR"
        details["_exc"] = f"{type(e).__name__}: {e}"
    return status, details


# ============ L5 调度系统层 ============
def l5_scheduler_check(client):
    """task_log 无 status 列（AI_DEBUG_HISTORY Loop 13 P0-3 确认：表语义只记成功执行）。
    失败任务通过 journalctl 检测，不查 task_log.status。
    """
    details = {}
    status = "OK"
    try:
        # scheduler 日志
        sch, _, _ = ssh_run(
            client,
            r'journalctl -u mory-assistant --since "10 minutes ago" --no-pager '
            r'| grep -iE "scheduler|apscheduler|_job_|task_transaction|claim_task" '
            r'| tail -30',
            timeout=15,
        )
        details["scheduler_log_10min"] = sch or "(none)"

        # task_log 无 status 列，改为查最近 10 条调度记录（用 exec_ts 倒序）
        recent, er = sqlite_query(
            client, MORY_DB,
            "SELECT task_key, exec_date FROM task_log "
            "ORDER BY id DESC LIMIT 10;",
        )
        details["recent_scheduled_tasks"] = recent if not er else f"ERR: {er}"

        # 失败任务：通过 journalctl 检测（task_log 无 status 列）
        fail_log, _, _ = ssh_run(
            client,
            r'journalctl -u mory-assistant --since "10 minutes ago" --no-pager '
            r'| grep -iE "fail|exception|error" '
            r'| grep -viE "EXECUTED|ERROR.*MISSED|EVENT_JOB_|scheduler_monitor.*EVENT|no such|operationalerror|_job_critical|critical_jobs_health" '
            r'| tail -15',
            timeout=15,
        )
        details["fail_log_10min"] = fail_log or "(none)"
        if fail_log:
            status = "WARN"
            details["_warn"] = details.get("_warn", "") + "journalctl_has_fail_logs; "

        # task_log 无 status 列 - 标记为 N/A（病历已确认）
        details["failed_1h"] = "N/A(task_log无status列,见Loop13病历)"

        # WatchdogSec 检查（已知未配置，参考 AI_DEBUG_HISTORY Loop 5）
        ws, _, _ = ssh_run(
            client,
            "systemctl show mory-assistant -p WatchdogUSec --value | cat",
            timeout=10,
        )
        details["watchdog_usec"] = ws.strip()
        if ws.strip() == "0" or not ws.strip():
            details["watchdog_note"] = "WatchdogSec not configured (see AI_DEBUG_HISTORY Loop 5/P1-2)"
    except Exception as e:
        status = "ERROR"
        details["_exc"] = f"{type(e).__name__}: {e}"
    return status, details


# ============ L6 看门狗层 ============
def l6_watchdog_check(client):
    details = {}
    status = "OK"
    try:
        wd, _, _ = ssh_run(client, f"tail -50 {REMOTE}/logs/watchdog.log", timeout=10)
        details["watchdog_log_tail"] = wd or "(empty or missing)"
        vm, _, _ = ssh_run(client, f"tail -30 {REMOTE}/logs/v5312_monitor.log", timeout=10)
        details["v5312_monitor_tail"] = vm or "(empty or missing)"
        va, _, _ = ssh_run(client, f"tail -30 {REMOTE}/logs/v5312_alerts.log", timeout=10)
        details["v5312_alerts_tail"] = va or "(empty or missing)"
        ls_logs, _, _ = ssh_run(client, f"ls -la {REMOTE}/logs/ | tail -20", timeout=10)
        details["logs_listing"] = ls_logs
        cron, _, _ = ssh_run(
            client,
            r'(crontab -l 2>/dev/null; sudo crontab -l 2>/dev/null; '
            r'sudo grep -R "mory_assistant" /var/spool/cron/crontabs /etc/cron* 2>/dev/null || true) '
            r'| grep -E "mory_assistant|vps_watchdog" | sort -u',
            timeout=10,
        )
        details["cron_tasks"] = cron or "(none)"
        # 旧监控脚本 _vps_monitor_cron.py 残留报错识别
        old_cron_err, _, _ = ssh_run(
            client,
            f'tail -30 {REMOTE}/logs/v5312_monitor.log 2>/dev/null | grep -i "_vps_monitor_cron.py" | tail -5',
            timeout=10,
        )
        details["legacy_cron_residue"] = old_cron_err or "(none)"

        # 检查 watchdog.log 最后写入时间是否过旧（>5min 视为可能停摆）
        wd_mtime, _, _ = ssh_run(
            client,
            f'stat -c "%Y" {REMOTE}/logs/watchdog.log 2>/dev/null',
            timeout=10,
        )
        now_ts, _, _ = ssh_run(client, "date +%s", timeout=10)
        if wd_mtime.strip().isdigit() and now_ts.strip().isdigit():
            age = int(now_ts) - int(wd_mtime)
            details["watchdog_log_age_sec"] = age
            if age > 600:
                status = "WARN"
                details["_warn"] = details.get("_warn", "") + f"watchdog_log_stale({age}s); "
    except Exception as e:
        status = "ERROR"
        details["_exc"] = f"{type(e).__name__}: {e}"
    return status, details


# ============ 腾讯云 Lighthouse API ============
def tencent_lighthouse_check():
    """可选补充。失败时记录但不中断。"""
    details = {}
    if not TC_SECRET_ID or not TC_SECRET_KEY:
        details["status"] = "TENCENT_API_SKIPPED"
        details["reason"] = "TENCENT_CLOUD_SECRET_ID/KEY not set in .env"
        return details
    try:
        # 延迟导入，避免未安装时影响主流程
        import tencentcloud.common as tc_common
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.lighthouse.v20200324 import lighthouse_client, models

        cred = credential.Credential(TC_SECRET_ID, TC_SECRET_KEY)
        # HttpProfile 不接受 timeout 参数（SDK 版本差异），用 reqTimeout 替代
        http = HttpProfile()
        http.reqTimeout = 10
        prof = ClientProfile(httpProfile=http)
        client = lighthouse_client.LighthouseClient(cred, TC_REGION, prof)

        # 1. DescribeInstances
        try:
            req = models.DescribeInstancesRequest()
            req.InstanceIds = [TC_INSTANCE_ID]
            resp = client.DescribeInstances(req)
            insts = resp.InstanceSet if resp else []
            if insts:
                inst = insts[0]
                details["instance_state"] = inst.InstanceState
                details["instance_name"] = inst.InstanceName
                details["public_ip"] = inst.PublicAddresses[0] if inst.PublicAddresses else ""
            else:
                details["instance_state"] = "NOT_FOUND"
        except Exception as e:
            details["describe_instances_err"] = f"{type(e).__name__}: {e}"

        # 2. 性能指标：Lighthouse SDK 不暴露 CPU/MEM 监控，由 L1 SSH top/free/df 提供。
        # 本层仅标记为 from_ssh，不在云端重复拉取。
        details["metrics_note"] = "cpu/mem/disk/net via L1 SSH (Lighthouse SDK has no public metric API)"

        details["status"] = "ok"
    except ImportError:
        details["status"] = "TENCENT_API_SKIPPED"
        details["reason"] = "tencentcloud-sdk-lighthouse not installed"
    except Exception as e:
        details["status"] = "TENCENT_API_ERROR"
        details["err"] = f"{type(e).__name__}: {e}"
    return details


# ============ 病历查询 ============
def grep_debug_history(keyword):
    """在 AI_DEBUG_HISTORY.md 中搜索关键词，返回前 5 行匹配（不读全文件）"""
    if not DEBUG_HISTORY.exists():
        return "(AI_DEBUG_HISTORY.md not found)"
    try:
        result = subprocess.run(
            ["python", "-c",
             f"import sys; "
             f"lines=open(r'{DEBUG_HISTORY}', encoding='utf-8').readlines(); "
             f"matched=[l.rstrip() for l in lines if {keyword!r} in l][:5]; "
             f"print('\\n'.join(matched) if matched else '(no match)')"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or "(no match)"
    except Exception as e:
        return f"grep_err: {e}"


# ============ 单轮执行 ============
def run_single_round(round_no, total_rounds, log_file):
    """执行一轮 6 层 + 腾讯云监控，写入 log_file"""
    ts = now_cst_str()
    header = f"========== Loop Round {round_no}/{total_rounds} | {ts} =========="
    print(header)
    lines = [header]

    # 异常收集
    exceptions = []
    need_review = []

    # 单 SSH client 复用所有命令
    client = None
    try:
        client = make_ssh_client()
    except Exception as e:
        msg = f"[SSH_CONNECT_FAIL] {type(e).__name__}: {e}"
        print(msg)
        lines.append(msg)
        # 查病历
        hint = grep_debug_history("SSH connect")
        lines.append(f"[AI_DEBUG_HISTORY_HINT] {hint}")
        lines.append("========================================")
        _append_log(log_file, "\n".join(lines))
        return {"round": round_no, "ssh_fail": str(e)}

    try:
        # L1
        s1, d1 = l1_vps_check(client)
        line1 = (f"[L1 VPS] STATUS={s1} | cpu={d1.get('cpu_usage','?')} | mem_avail={d1.get('mem_avail_pct','?')} | "
             f"disk={d1.get('disk_usage_pct','?')} | load1={d1.get('load1','?')} | net_conn={d1.get('net_conn','?')}")
        if "_warn" in d1: line1 += f" | WARN={d1['_warn']}"
        print(line1); lines.append(line1)
        if s1 == "ERROR": exceptions.append(("L1", d1.get("_exc", "")))

        # L2
        s2, d2 = l2_service_check(client)
        line2 = (f"[L2 SVC] mory-assistant={d2.get('mory-assistant','?')} | "
                 f"mory-dashboard={d2.get('mory-dashboard','?')} | "
                 f"errors_10min={'yes' if d2.get('mory-assistant_errors_10min') and d2.get('mory-assistant_errors_10min') != '(none)' else 'none'}")
        print(line2); lines.append(line2)
        if s2 == "CRITICAL" or s2 == "ERROR":
            exceptions.append(("L2", d2.get("_exc") or d2.get("_crit") or ""))
            need_review.append("L2 service not active or ssh error")

        # L3
        s3, d3 = l3_app_check(client)
        line3 = (f"[L3 APP] health={'ok' if 'ok' in d3.get('health_raw','').lower() else 'FAIL'} | "
                 f"version={d3.get('version','?')} | "
                 f"home_status={d3.get('home_http_code','?')}")
        if s3 != "OK":
            line3 += f" | WARN={d3.get('_warn','')}{d3.get('_crit','')}"
        print(line3); lines.append(line3)
        if s3 == "CRITICAL" or s3 == "ERROR":
            exceptions.append(("L3", d3.get("_exc") or d3.get("_crit") or ""))

        # L4
        s4, d4 = l4_biz_check(client)
        line4 = (f"[L4 BIZ] task_1h={d4.get('task_1h','?')} | task_5min={d4.get('task_5min','?')} | "
                 f"token_1h={d4.get('token_usage_1h','?')} | token_5min={d4.get('token_usage_5min','?')} | "
                 f"token_cost_1h={d4.get('token_cost_1h_sum','?')} | "
                 f"guard_cost_1h={d4.get('guard_cost_1h_sum','?')} | "
                 f"conversion_1h={d4.get('conversion_1h','?')} | orphan_1h={d4.get('orphan_1h','?')}")
        print(line4); lines.append(line4)
        if s4 == "ERROR":
            exceptions.append(("L4", d4.get("_exc", "")))

        # L5
        s5, d5 = l5_scheduler_check(client)
        line5 = (f"[L5 SCHD] failed_1h={d5.get('failed_1h','?')} | watchdog_usec={d5.get('watchdog_usec','?')}")
        if s5 != "OK":
            line5 += f" | WARN={d5.get('_warn','')}"
        # recent_scheduled_tasks 只取前 3 行避免日志过长
        recent_jobs = d5.get("recent_scheduled_tasks", "(none)")
        if recent_jobs and recent_jobs != "(none)":
            recent_jobs_short = "; ".join(recent_jobs.splitlines()[:3])
        else:
            recent_jobs_short = "(none)"
        line5 += f" | recent_tasks={recent_jobs_short}"
        # fail_log_10min 简要展示
        fail_log_short = _short(d5.get("fail_log_10min", "(none)"), 100)
        line5 += f" | fail_log_10min={fail_log_short}"
        print(line5); lines.append(line5)
        if s5 == "ERROR":
            exceptions.append(("L5", d5.get("_exc", "")))

        # L6
        s6, d6 = l6_watchdog_check(client)
        wd_tail_short = _short(d6.get("watchdog_log_tail", ""), 200)
        vm_tail_short = _short(d6.get("v5312_monitor_tail", ""), 200)
        alerts_short = _short(d6.get("v5312_alerts_tail", ""), 100)
        line6 = (f"[L6 WATCH] watchdog_age_sec={d6.get('watchdog_log_age_sec','?')} | "
                 f"cron={'yes' if d6.get('cron_tasks') and d6.get('cron_tasks') != '(none)' else 'none'} | "
                 f"legacy_cron_residue={'yes' if d6.get('legacy_cron_residue') and d6.get('legacy_cron_residue') != '(none)' else 'none'}")
        if s6 != "OK":
            line6 += f" | WARN={d6.get('_warn','')}"
        print(line6); lines.append(line6)
        if s6 == "ERROR":
            exceptions.append(("L6", d6.get("_exc", "")))

    finally:
        try:
            client.close()
        except Exception:
            pass

    # 腾讯云（独立，不依赖 SSH）
    try:
        tc = tencent_lighthouse_check()
        tc_status = tc.get("status", "unknown")
        tc_line = (f"[TENCENT] status={tc_status} | "
                   f"instance={tc.get('instance_state','?')} | "
                   f"public_ip={tc.get('public_ip','?')} | "
                   f"note={tc.get('metrics_note','?')}")
        if tc_status not in ("ok",):
            tc_line += f" | err={tc.get('err') or tc.get('reason') or ''}"
        print(tc_line); lines.append(tc_line)
    except Exception as e:
        print(f"[TENCENT] EXCEPTION {e}"); lines.append(f"[TENCENT] EXCEPTION {e}")

    # 异常汇总
    if exceptions:
        ex_lines = ["[EXCEPTION] " + "; ".join(f"{k}:{v}" for k, v in exceptions)]
        for layer, msg in exceptions:
            hint = grep_debug_history(_extract_keyword(msg))
            ex_lines.append(f"[AI_DEBUG_HISTORY_HINT][{layer}] {hint}")
        print("\n".join(ex_lines)); lines.extend(ex_lines)
    else:
        lines.append("[EXCEPTION] none")
        print("[EXCEPTION] none")

    # 建议
    if need_review:
        rec = "[RECOMMEND] [NEEDS_REVIEW] " + "; ".join(need_review)
    else:
        rec = "[RECOMMEND] all normal"
    print(rec); lines.append(rec)

    sep = "========================================"
    print(sep); lines.append(sep)

    _append_log(log_file, "\n".join(lines) + "\n")
    return {"round": round_no, "status": "ok"}


def _short(v, n=120):
    """缩短字符串用于单行展示"""
    if v is None:
        return ""
    s = str(v).replace("\n", " ").replace("\r", " ").strip()
    if len(s) > n:
        return s[:n] + "..."
    return s


def _extract_keyword(exc_msg):
    """从异常信息提取病历搜索关键词"""
    msg = str(exc_msg).lower()
    for kw in ("permission denied", "409 conflict", "operationalerror", "timeout", "connection refused"):
        if kw in msg:
            return kw
    return exc_msg[:40] if exc_msg else "unknown"


def _append_log(log_file, content):
    """追加写入日志文件"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(content + "\n")


# ============ 主入口 ============
def main():
    parser = argparse.ArgumentParser(description="Puzan OS Loop 6 层监控")
    parser.add_argument("--once", action="store_true", help="仅执行 1 轮（基线模式）")
    parser.add_argument("--loop", action="store_true", help="无限 LOOP 模式（配合 --interval 持续监控，直到手动终止）")
    parser.add_argument("--start-round", type=int, default=1, help="起始轮次（默认 1）")
    parser.add_argument("--rounds", type=int, default=6, help="总轮次（默认 6，--loop 时忽略）")
    parser.add_argument("--interval", type=int, default=300, help="轮间间隔秒数（默认 300）")
    parser.add_argument("--log-file", type=str, default="", help="指定日志文件路径（追加模式，默认按时间新建）")
    args = parser.parse_args()

    # 单例锁：防止多个实例并发写入同一日志导致轮次混乱
    ensure_singleton()

    if args.log_file:
        log_file = Path(args.log_file)
    else:
        log_file = log_path()
    # 日志头（仅新文件写入；追加模式不重写头）
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if not log_file.exists():
        header = f"# Puzan OS Loop Monitor Log | started={now_cst_str()} | host={HOST} | version={EXPECTED_VERSION}\n"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(header)
        print(header.strip())
    else:
        print(f"# Appending to existing log: {log_file}")

    if args.once:
        run_single_round(1, 1, log_file)
        return

    if args.loop:
        print(f"[LOOP MODE] 无限循环启动，间隔 {args.interval}s。按 Ctrl+C 终止。")
        i = args.start_round
        while True:
            if i > args.start_round:
                print(f"[SLEEP] waiting {args.interval}s before round {i}...")
                time.sleep(args.interval)
            run_single_round(i, 0, log_file)  # total=0 表示无限
            i += 1
        return

    start = args.start_round
    total = args.rounds
    for i in range(start, total + 1):
        # 第 1 轮不 sleep；续跑模式（start>1）第 2 轮起也 sleep，保证与基线间隔正确
        if i > 1:
            print(f"[SLEEP] waiting {args.interval}s before round {i}...")
            time.sleep(args.interval)
        run_single_round(i, total, log_file)

    print(f"\n[DONE] {total - start + 1} rounds finished. Log: {log_file}")


if __name__ == "__main__":
    main()
