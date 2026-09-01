#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Puzan OS Loop 6 层监控脚本 - v5.31.4

只读 VPS 监控，6 层 + 腾讯云 Lighthouse API：
  L1 VPS 实例层（CPU/MEM/DISK/LOAD/NET）
  L2 服务进程层（systemd 双 active + journalctl 错误）
  L3 应用健康层（/api/health liveness + 远端 version.py 校验）
  L4 业务指标层（task_execution_history/token_usage/llm_cost/conversion/orphan）
  L5 调度系统层（持久化四态 + scheduler_metrics + journal）
  L6 看门狗层（watchdog.log + v5312_monitor.log + cron）

用法：
  python scripts/puzan_loop_monitor.py                 # 6 轮，每轮 5 分钟
  python scripts/puzan_loop_monitor.py --once           # 仅 1 轮（基线）
  python scripts/puzan_loop_monitor.py --start-round 2 --rounds 5  # 从第 2 轮开始跑 5 轮

铁律：只读、不重启、不上传 db/config、凭据从 .env、异常先查病历。
"""
import logging
import os
import sys
import time
import json
import argparse
import traceback
import subprocess
import atexit
import shlex
from pathlib import Path
from datetime import datetime, timezone, timedelta

import paramiko
from dotenv import dotenv_values

# ============ 常量 ============
_CST = timezone(timedelta(hours=8))
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from version import VERSION as EXPECTED_VERSION
from core.vps_config import ssh_connect

ENV_PATH = PROJECT_ROOT / ".env"
LOGS_DIR = PROJECT_ROOT / "logs"
LOCK_FILE = LOGS_DIR / ".puzan_loop_monitor.lock"
DEBUG_HISTORY = PROJECT_ROOT / "AI_DEBUG_HISTORY.md"
HEALTH_URL = "http://localhost:6616/api/health"
MORY_DB = "/home/ubuntu/mory_assistant/mory.db"
SCHEDULER_ERROR_SCOPE_SQL = (
    "CASE WHEN last_status='error' THEN 'current' "
    "WHEN COALESCE(last_error,'')='' THEN 'none' ELSE 'historical' END"
)

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
    ssh_connect(client, timeout=15)
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


def _parse_status_counts(rows_str):
    """解析 sqlite ``status|count`` 输出，未知状态保留但不制造假数字。"""
    counts = {"success": 0, "failed": 0, "aborted": 0, "running": 0}
    for line in (rows_str or "").splitlines():
        parts = line.split("|", 1)
        if len(parts) != 2:
            continue
        status = parts[0].strip().lower()
        try:
            counts[status] = int(parts[1].strip())
        except ValueError:
            continue
    return counts


def _parse_scheduler_failure_history(rows_str):
    """把累计失败行转换为不易混淆当前状态与历史错误的结构化证据。"""
    history = []
    for line_no, line in enumerate((rows_str or "").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split("|", 7)
        if len(parts) != 8:
            raise ValueError(f"row {line_no} has {len(parts)} columns, expected 8")
        try:
            fail_count = int(parts[2].strip())
            miss_count = int(parts[3].strip())
            last_run = int(parts[4].strip())
            last_status_at = int(parts[5].strip())
        except ValueError as exc:
            raise ValueError(f"row {line_no} has invalid numeric fields") from exc
        error_scope = parts[6].strip()
        if error_scope not in {"current", "historical", "none"}:
            raise ValueError(f"row {line_no} has invalid error_scope")
        history.append({
            "job_id": parts[0].strip(),
            "current_status": parts[1].strip(),
            "cumulative_fail_count": fail_count,
            "cumulative_miss_count": miss_count,
            "last_run": last_run,
            "last_status_at": last_status_at,
            "error_scope": error_scope,
            "last_failure_error": parts[7],
        })
    return history


def _compact_oom_scope(scope):
    """把内核 cgroup 路径压缩为不泄露主机目录的稳定来源标签。"""
    leaf = (scope or "unknown").rstrip("/").rsplit("/", 1)[-1]
    if leaf.startswith("docker-") and leaf.endswith(".scope"):
        container_id = leaf[len("docker-"):-len(".scope")]
        return f"docker:{container_id[:12]}"
    return leaf or "unknown"


def _format_ranked_counts(counts):
    """将来源/进程计数压缩为确定性证据字符串。"""
    return ",".join(
        f"{name}={count}"
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


def _parse_oom_journal(raw, mory_control_groups=()):
    """解析一小时 OOM 日志，分开压力来源 cgroup 与受害进程 cgroup。"""
    cgroup_total = None
    global_total = None
    matched_total = None
    journal_ok = False
    source_lines = 0
    non_memcg_source_lines = 0
    source_mory = 0
    source_external = 0
    source_unknown = 0
    victim_mory = 0
    sources = {}
    victims = {}
    evidence_lines = 0
    control_groups = {
        group.rstrip("/") or "/"
        for group in mory_control_groups
        if group and group.strip()
    }

    def _field(line, name):
        marker = f"{name}="
        if marker not in line:
            return ""
        return line.split(marker, 1)[1].split(",", 1)[0].strip()

    def _belongs_to_mory(scope):
        normalized = (scope or "").rstrip("/") or "/"
        return any(
            normalized == group or normalized.startswith(group + "/")
            for group in control_groups
        )

    for line in (raw or "").splitlines():
        line = line.strip()
        if line == "__OOM_JOURNAL_OK__=1":
            journal_ok = True
            continue
        if line.startswith("__OOM_CGROUP_TOTAL__="):
            try:
                cgroup_total = int(line.split("=", 1)[1])
            except ValueError:
                cgroup_total = None
            continue
        if line.startswith("__OOM_GLOBAL_TOTAL__="):
            try:
                global_total = int(line.split("=", 1)[1])
            except ValueError:
                global_total = None
            continue
        if line.startswith("__OOM_MATCHED_TOTAL__="):
            try:
                matched_total = int(line.split("=", 1)[1])
            except ValueError:
                matched_total = None
            continue
        if " oom-kill:" in line or line.startswith("oom-kill:"):
            evidence_lines += 1
            source_scope = _field(line, "oom_memcg")
            victim_scope = _field(line, "task_memcg")
            if victim_scope and victim_scope not in {"/", "(null)"} and _belongs_to_mory(victim_scope):
                victim_mory += 1
            if "constraint=CONSTRAINT_MEMCG" not in line:
                non_memcg_source_lines += 1
                continue
            source_lines += 1
            label = _compact_oom_scope(source_scope)
            sources[label] = sources.get(label, 0) + 1
            if source_scope.startswith("/"):
                if _belongs_to_mory(source_scope):
                    source_mory += 1
                elif control_groups or label.startswith("docker:"):
                    source_external += 1
                else:
                    source_unknown += 1
            else:
                source_unknown += 1
            continue
        killed_markers = (
            "Memory cgroup out of memory: Killed process ",
            "Out of memory: Killed process ",
        )
        killed_marker = next((marker for marker in killed_markers if marker in line), "")
        if killed_marker:
            evidence_lines += 1
            victim_part = line.split(killed_marker, 1)[1]
            if "(" in victim_part and ")" in victim_part:
                victim = victim_part.split("(", 1)[1].split(")", 1)[0].strip()
                if victim:
                    victims[victim] = victims.get(victim, 0) + 1

    totals = (cgroup_total, global_total, matched_total)
    if not journal_ok or any(value is None or value < 0 for value in totals):
        raise ValueError("missing or invalid OOM journal markers")
    total = cgroup_total + global_total
    source_unknown += (
        max(cgroup_total - source_lines, 0)
        + global_total
        + max(non_memcg_source_lines - global_total, 0)
    )
    truncated = matched_total > evidence_lines
    complete = (
        global_total == 0
        and source_lines == cgroup_total
        and source_unknown == 0
        and not truncated
        and (total == 0 or bool(control_groups))
    )
    return {
        "oom_kills_1h": total,
        "oom_cgroup_kills_1h": cgroup_total,
        "oom_global_kills_1h": global_total,
        "oom_source_mory_1h": source_mory,
        "oom_source_external_1h": source_external,
        "oom_source_unknown_1h": source_unknown,
        "oom_victim_mory_1h": victim_mory,
        "oom_source_labels_1h": _format_ranked_counts(sources),
        "oom_victim_processes_1h": _format_ranked_counts(victims),
        "oom_attribution_complete": complete,
        "oom_journal_ok": journal_ok,
        "oom_control_groups_available": bool(control_groups),
        "oom_evidence_truncated": truncated,
    }


def _resolve_oom_container_names(client, source_counts):
    """一次批量把已校验 Docker 短 ID 映射成容器名；失败时保留 ID。"""
    docker_counts = {}
    for item in (source_counts or "").split(",")[:5]:
        if "=" not in item:
            continue
        label, raw_count = item.rsplit("=", 1)
        if not label.startswith("docker:"):
            continue
        container_id = label.split(":", 1)[1]
        if len(container_id) < 12 or any(ch not in "0123456789abcdefABCDEF" for ch in container_id):
            continue
        try:
            count = int(raw_count)
        except ValueError:
            continue
        docker_counts[container_id] = docker_counts.get(container_id, 0) + count
    if not docker_counts:
        return ""
    output, _, rc = ssh_run(
        client,
        "docker inspect --format={{.Id}}:{{.Name}} " + " ".join(sorted(docker_counts)),
        timeout=10,
    )
    names = {}
    if rc == 0:
        for line in output.splitlines():
            full_id, separator, raw_name = line.strip().partition(":")
            if separator and full_id and raw_name:
                names[full_id[:12]] = raw_name.lstrip("/")
    resolved = {}
    for container_id, count in docker_counts.items():
        resolved_name = names.get(container_id, f"docker:{container_id}")
        resolved[resolved_name] = resolved.get(resolved_name, 0) + count
    return _format_ranked_counts(resolved)


# ============ L1 VPS 实例层 ============
def l1_vps_check(client):
    details = {}
    status = "OK"
    l1_evidence_gaps = []

    def _validate_required_command(name, rc, stderr, valid, missing_reason):
        """Require both command execution and the metric needed by L1."""
        reasons = []
        if rc != 0:
            reasons.append(f"rc={rc}")
        if stderr:
            reasons.append("stderr")
        if not valid:
            reasons.append(missing_reason)
        if reasons:
            l1_evidence_gaps.append(f"{name}({','.join(reasons)})")

    try:
        # CPU/进程
        top, top_err, top_rc = ssh_run(client, "top -bn1 | head -20", timeout=15)
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
        free_m, free_err, free_rc = ssh_run(client, "free -m", timeout=10)
        details["free_m"] = free_m
        # 磁盘
        df_h, df_err, df_rc = ssh_run(client, "df -h / /home", timeout=10)
        details["disk"] = df_h
        # 连接数
        conn, conn_err, conn_rc = ssh_run(client, "ss -tn state established | wc -l", timeout=10)
        details["net_conn"] = conn.strip()
        # 负载
        uptime_o, uptime_err, uptime_rc = ssh_run(client, "uptime", timeout=10)
        loadavg_o, loadavg_err, loadavg_rc = ssh_run(client, "cat /proc/loadavg", timeout=10)
        details["uptime"] = uptime_o
        details["loadavg"] = loadavg_o
        control_group_o, _, control_group_rc = ssh_run(
            client,
            "systemctl show mory-assistant.service mory-dashboard.service "
            "-p ControlGroup --value",
            timeout=10,
        )
        mory_control_groups = {
            line.strip()
            for line in control_group_o.splitlines()
            if control_group_rc == 0 and line.strip()
        }
        oom_o, oom_err, oom_rc = ssh_run(
            client,
            "set -eu; "
            "logs=\"$(journalctl -k --since '1 hour ago' --no-pager)\"; "
            "printf '__OOM_JOURNAL_OK__=1\\n'; "
            "printf '__OOM_CGROUP_TOTAL__=%s\\n' \"$(printf '%s\\n' \"$logs\" "
            "| awk '/Memory cgroup out of memory: Killed process/{count++} END{print count+0}')\"; "
            "printf '__OOM_GLOBAL_TOTAL__=%s\\n' \"$(printf '%s\\n' \"$logs\" "
            "| awk '/Out of memory: Killed process/{count++} END{print count+0}')\"; "
            "printf '__OOM_MATCHED_TOTAL__=%s\\n' \"$(printf '%s\\n' \"$logs\" "
            "| awk '/oom-kill:|Memory cgroup out of memory: Killed process|Out of memory: Killed process/{count++} END{print count+0}')\"; "
            "printf '%s\\n' \"$logs\" "
            "| grep -E 'oom-kill:|Memory cgroup out of memory: Killed process|Out of memory: Killed process' "
            "| tail -800",
            timeout=20,
        )
        if oom_rc != 0 or oom_err:
            details.update({
                "oom_kills_1h": "unavailable",
                "oom_cgroup_kills_1h": "unavailable",
                "oom_global_kills_1h": "unavailable",
                "oom_source_mory_1h": "unavailable",
                "oom_source_external_1h": "unavailable",
                "oom_source_unknown_1h": "unavailable",
                "oom_victim_mory_1h": "unavailable",
                "oom_source_labels_1h": "unavailable",
                "oom_victim_processes_1h": "unavailable",
                "oom_external_containers_1h": "unavailable",
                "oom_attribution_complete": False,
                "oom_journal_ok": False,
                "oom_control_groups_available": bool(mory_control_groups),
                "oom_evidence_truncated": "unavailable",
            })
            status = "WARN"
            details["_warn"] = details.get("_warn", "") + "oom_evidence_unavailable; "
        else:
            try:
                oom_evidence = _parse_oom_journal(oom_o, mory_control_groups)
            except ValueError:
                oom_evidence = {
                    "oom_kills_1h": "invalid",
                    "oom_cgroup_kills_1h": "invalid",
                    "oom_global_kills_1h": "invalid",
                    "oom_source_mory_1h": "invalid",
                    "oom_source_external_1h": "invalid",
                    "oom_source_unknown_1h": "invalid",
                    "oom_victim_mory_1h": "invalid",
                    "oom_source_labels_1h": "invalid",
                    "oom_victim_processes_1h": "invalid",
                    "oom_external_containers_1h": "invalid",
                    "oom_attribution_complete": False,
                    "oom_journal_ok": False,
                    "oom_control_groups_available": bool(mory_control_groups),
                    "oom_evidence_truncated": "invalid",
                }
            details.update(oom_evidence)
            if isinstance(details["oom_source_external_1h"], int) and details["oom_source_external_1h"] > 0:
                details["oom_external_containers_1h"] = _resolve_oom_container_names(
                    client,
                    details["oom_source_labels_1h"],
                )
            elif details["oom_source_external_1h"] == 0:
                details["oom_external_containers_1h"] = ""
            if details["oom_kills_1h"] == "invalid":
                status = "WARN"
                details["_warn"] = details.get("_warn", "") + "oom_evidence_invalid; "
            elif details["oom_source_mory_1h"] > 0 or details["oom_victim_mory_1h"] > 0:
                status = "CRITICAL"
                details["_crit"] = details.get("_crit", "") + (
                    f"mory_oom_source({details['oom_source_mory_1h']}); "
                    f"mory_oom_victim({details['oom_victim_mory_1h']}); "
                )
            if details["oom_kills_1h"] != "invalid":
                if not details["oom_attribution_complete"]:
                    status = "WARN" if status != "CRITICAL" else status
                    details["_warn"] = details.get("_warn", "") + "oom_attribution_incomplete; "
                if details["oom_global_kills_1h"] > 0:
                    status = "WARN" if status != "CRITICAL" else status
                    details["_warn"] = details.get("_warn", "") + f"global_oom_1h({details['oom_global_kills_1h']}); "
                if details["oom_source_unknown_1h"] > 0:
                    status = "WARN" if status != "CRITICAL" else status
                    details["_warn"] = details.get("_warn", "") + f"unknown_oom_source_1h({details['oom_source_unknown_1h']}); "
                if details["oom_source_external_1h"] > 0:
                    status = "WARN" if status != "CRITICAL" else status
                    details["_warn"] = details.get("_warn", "") + f"external_oom_source_1h({details['oom_source_external_1h']}); "

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
            except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
                logging.getLogger(__name__).debug(f'非致命忽略: {_e}')

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
                                    status = "WARN" if status != "CRITICAL" else status
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
                                status = "WARN" if status != "CRITICAL" else status
                                details["_warn"] = details.get("_warn", "") + f"disk_usage_high({use_pct}%); "
                        except ValueError:
                            pass

        load1 = ""
        if loadavg_o:
            load1 = loadavg_o.split()[0]
            details["load1"] = load1
            try:
                if float(load1) > 5.0:
                    status = "WARN" if status != "CRITICAL" else status
                    details["_warn"] = details.get("_warn", "") + f"load1_high({load1}); "
            except ValueError:
                pass

        # L1 是只读证据层：命令失败或关键指标为空时必须可见，不能假绿。
        _validate_required_command("top", top_rc, top_err, bool(cpu_usage), "cpu_missing")
        _validate_required_command(
            "free", free_rc, free_err, bool(mem_avail_pct), "mem_available_missing"
        )
        _validate_required_command("df", df_rc, df_err, bool(disk_usage_pct), "disk_usage_missing")
        conn_valid = False
        try:
            conn_valid = int(conn.strip()) >= 0
        except (TypeError, ValueError):
            pass
        _validate_required_command("ss", conn_rc, conn_err, conn_valid, "established_count_missing")
        uptime_valid = " up " in f" {uptime_o.strip().lower()} "
        _validate_required_command("uptime", uptime_rc, uptime_err, uptime_valid, "uptime_missing")
        loadavg_valid = False
        try:
            loadavg_valid = bool(loadavg_o.strip()) and float(loadavg_o.split()[0]) >= 0
        except (TypeError, ValueError, IndexError):
            pass
        _validate_required_command("loadavg", loadavg_rc, loadavg_err, loadavg_valid, "load1_missing")
        if l1_evidence_gaps:
            details["l1_evidence_gaps"] = l1_evidence_gaps
            # 保留跨层语义：纯粹“看不到资源证据”应由审计控制面映射为
            # evidence_gap；若此前已检测到真实资源/OOM异常，则仍是失败。
            details["l1_evidence_gap_only"] = status == "OK"
            status = "WARN" if status != "CRITICAL" else status
            details["_warn"] = details.get("_warn", "") + (
                "l1_evidence_gap=" + ",".join(l1_evidence_gaps) + "; "
            )
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

        # journalctl 错误过滤：排除业务抓取重试日志和正常调度事件
        # 排除项：HTTP请求失败(业务抓取重试)、CriticalJobsHealthTask(任务名含critical)、Running job/executed(正常调度)
        err_a, _, _ = ssh_run(
            client,
            r'journalctl -u mory-assistant --since "10 minutes ago" --no-pager '
            r'| grep -iE "error|critical|exception|traceback" '
            r'| grep -viE "EXECUTED|ERROR.*MISSED|EVENT_JOB_|scheduler_monitor.*EVENT|_job_critical|critical_jobs_health|CriticalJobsHealth|HTTP请求失败|HTTP请求成功|Running job|executed successfully|Added job" '
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
    """分别核验 health liveness 与远端版本，禁止从 health 猜部署版本。"""
    details = {}
    status = "OK"
    try:
        raw_health, health_err, health_rc = ssh_run(
            client,
            f"curl -sS -m 5 -w '\n%{{http_code}}' {HEALTH_URL}",
            timeout=10,
        )
        health_body, separator, health_code = raw_health.rpartition("\n")
        if not separator:
            health_body, health_code = raw_health, ""
        health_body = health_body.strip()
        health_code = health_code.strip()
        details["health_raw"] = health_body[:300]
        details["health_http_code"] = health_code

        health_ok = False
        try:
            health_ok = json.loads(health_body).get("status") == "ok"
        except (AttributeError, json.JSONDecodeError):
            health_ok = False
        if health_rc != 0 or health_err or health_code != "200" or not health_ok:
            status = "CRITICAL"
            details["_crit"] = (
                f"health_not_ok(rc={health_rc}, http={health_code or 'none'}, "
                f"error={health_err or 'none'})"
            )

        remote_dir = shlex.quote(str(REMOTE))
        version_cmd = (
            f"cd {remote_dir} && /usr/bin/python3 -c "
            "'from version import VERSION; print(VERSION)'"
        )
        remote_version, version_err, version_rc = ssh_run(client, version_cmd, timeout=10)
        remote_version = remote_version.strip()
        details["version"] = remote_version
        details["version_source"] = f"{REMOTE}/version.py"
        if version_rc != 0 or version_err or remote_version != EXPECTED_VERSION:
            if status != "CRITICAL":
                status = "WARN"
            details["_warn"] = details.get("_warn", "") + (
                f"version_mismatch(expect={EXPECTED_VERSION}, got={remote_version or 'none'}, "
                f"rc={version_rc}, error={version_err or 'none'}); "
            )
    except Exception as e:
        status = "ERROR"
        details["_exc"] = f"{type(e).__name__}: {e}"
    return status, details


# ============ L4 业务指标层 ============
def l4_biz_check(client):
    """schema 参考 core/database.py + AI_DEBUG_HISTORY.md Loop 13/6：
      - task_execution_history: 仅覆盖 TaskTransactionManager 事务任务的四态历史
      - task_log: 临时 claim/防重锁，不得用于执行量或成功率统计
      - llm_cost_logs（mory.db）: timestamp(REAL/INTEGER, 秒级 Unix 时间)，LLM 调用与成本真相源
      - conversion_events: ts(REAL, 秒级 Unix 时间)
      - orphan_cleanup_log: run_at(INTEGER, 秒) - 非 ts
    """
    details = {}
    status = "OK"
    try:
        # 事务任务执行量来自 task_execution_history；task_log 只是临时防重锁。
        q1h, e1 = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM task_execution_history "
            "WHERE start_ts >= strftime('%s', datetime('now', '-1 hour'));",
        )
        transactional_1h = q1h.strip() if not e1 else f"ERR: {e1}"
        details["transactional_task_1h"] = transactional_1h
        # 兼容旧审计消费者；对外展示使用带 coverage 的新字段。
        details["task_1h"] = transactional_1h
        q5m, e5 = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM task_execution_history "
            "WHERE start_ts >= strftime('%s', datetime('now', '-5 minutes'));",
        )
        transactional_5m = q5m.strip() if not e5 else f"ERR: {e5}"
        details["transactional_task_5min"] = transactional_5m
        details["task_5min"] = transactional_5m
        status_rows, status_err = sqlite_query(
            client, MORY_DB,
            "SELECT status, COUNT(*) FROM task_execution_history "
            "WHERE start_ts >= strftime('%s', datetime('now', '-1 hour')) GROUP BY status;",
        )
        transactional_status_1h = (
            _parse_status_counts(status_rows) if not status_err else {"error": status_err}
        )
        details["transactional_task_status_1h"] = transactional_status_1h
        details["task_status_1h"] = transactional_status_1h
        total, total_err = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM task_execution_history;",
        )
        details["task_history_total"] = total.strip() if not total_err else f"ERR: {total_err}"
        latest, latest_err = sqlite_query(
            client, MORY_DB,
            "SELECT task_key, status, start_ts FROM task_execution_history ORDER BY id DESC LIMIT 1;",
        )
        details["task_history_latest"] = latest if not latest_err else f"ERR: {latest_err}"
        details["task_history_coverage"] = "TaskTransactionManager_only"
        recent, er = sqlite_query(
            client, MORY_DB,
            "SELECT task_key, status, start_ts FROM task_execution_history ORDER BY id DESC LIMIT 10;",
        )
        details["recent_tasks"] = recent if not er else f"ERR: {er}"
        if e1 or e5 or status_err or total_err or latest_err or er:
            status = "ERROR"
            details["_crit"] = "task_execution_history_query_failed"

        # 旧 router_usage.db 自 4 月后无写入入口，已删除；LLM 次数/成本统一读
        # 实际由 LLMCostGuard 持续刷盘的 mory.db.llm_cost_logs。
        tu, et = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM llm_cost_logs WHERE timestamp >= strftime('%s', datetime('now', '-1 hour'));",
        )
        details["token_usage_1h"] = tu.strip() if not et else f"ERR: {et}"

        tu5, et5 = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM llm_cost_logs WHERE timestamp >= strftime('%s', datetime('now', '-5 minutes'));",
        )
        details["token_usage_5min"] = tu5.strip() if not et5 else f"ERR: {et5}"

        # LLM 请求成本：mory.db.llm_cost_logs.estimated_cost
        lc, el = sqlite_query(
            client, MORY_DB,
            "SELECT COALESCE(SUM(estimated_cost),0) FROM llm_cost_logs WHERE timestamp >= strftime('%s', datetime('now', '-1 hour'));",
        )
        details["token_cost_1h_sum"] = lc.strip() if not el else f"ERR: {el}"
        lce, lce_err = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM llm_cost_logs;",
        )
        details["llm_cost_logs_count"] = lce.strip() if not lce_err else f"ERR: {lce_err}"
        if et or et5 or el or lce_err:
            status = "ERROR"
            details["_crit"] = "llm_cost_logs_query_failed"

        # conversion_events（ts 秒级 Unix 时间；写入方使用 int(time.time())）
        cv, ec = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM conversion_events WHERE ts >= strftime('%s', datetime('now', '-1 hour'));",
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
    """以 task_execution_history + scheduler_metrics 为主，journal 只做补充。"""
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

        status_rows, status_err = sqlite_query(
            client, MORY_DB,
            "SELECT status, COUNT(*) FROM task_execution_history "
            "WHERE start_ts >= strftime('%s', datetime('now', '-1 hour')) GROUP BY status;",
        )
        if status_err:
            status = "ERROR"
            details["_crit"] = f"execution_history_query_failed: {status_err}"
            history_counts = _parse_status_counts("")
        else:
            history_counts = _parse_status_counts(status_rows)
        details["task_status_1h"] = history_counts
        details["transactional_task_status_1h"] = history_counts
        details["task_history_coverage"] = "TaskTransactionManager_only"
        details["failed_1h"] = history_counts["failed"]
        details["transactional_failed_1h"] = history_counts["failed"]
        details["running_1h"] = history_counts["running"]
        details["aborted_1h"] = history_counts["aborted"]

        stale_running, stale_err = sqlite_query(
            client, MORY_DB,
            "SELECT COUNT(*) FROM task_execution_history WHERE status='running' "
            "AND start_ts < strftime('%s', datetime('now', '-30 minutes'));",
        )
        try:
            stale_count = int(stale_running.strip()) if not stale_err else 0
        except ValueError:
            stale_count = 0
            stale_err = f"invalid count: {stale_running!r}"
        details["stale_running_30m"] = stale_count

        recent_failures, recent_failures_err = sqlite_query(
            client, MORY_DB,
            "SELECT task_key, status, COALESCE(error_msg,''), start_ts "
            "FROM task_execution_history WHERE status='failed' "
            "AND start_ts >= strftime('%s', datetime('now', '-1 hour')) "
            "ORDER BY id DESC LIMIT 10;",
        )
        details["recent_persisted_failures"] = (
            recent_failures if not recent_failures_err else f"ERR: {recent_failures_err}"
        )

        bad_metrics, metrics_err = sqlite_query(
            client, MORY_DB,
            "SELECT job_id, last_status, COALESCE(fail_count,0), COALESCE(miss_count,0), "
            "COALESCE(last_status_at,0), COALESCE(last_error,'') "
            "FROM scheduler_metrics WHERE last_status IN ('error','missed') "
            "AND COALESCE(last_status_at,0) >= strftime('%s', datetime('now', '-1 hour')) "
            "ORDER BY COALESCE(last_status_at,0) DESC LIMIT 10;",
        )
        details["scheduler_metrics_errors"] = bad_metrics if not metrics_err else f"ERR: {metrics_err}"

        cumulative_failures, cumulative_failures_err = sqlite_query(
            client, MORY_DB,
            "SELECT job_id, last_status, COALESCE(fail_count,0), COALESCE(miss_count,0), "
            "COALESCE(last_run,0), "
            f"{SCHEDULER_ERROR_SCOPE_SQL} AS error_scope, "
            "REPLACE(REPLACE(COALESCE(last_error,''), char(13), ' '), char(10), ' ') "
            "FROM scheduler_metrics WHERE COALESCE(fail_count,0) > 0 "
            "OR COALESCE(miss_count,0) > 0 "
            "ORDER BY (COALESCE(fail_count,0) + COALESCE(miss_count,0)) DESC, job_id LIMIT 20;",
        )
        details["scheduler_metrics_cumulative_failures"] = (
            cumulative_failures
            if not cumulative_failures_err
            else f"ERR: {cumulative_failures_err}"
        )
        structured_failures, structured_failures_err = sqlite_query(
            client, MORY_DB,
            "SELECT job_id, last_status, COALESCE(fail_count,0), COALESCE(miss_count,0), "
            "COALESCE(last_run,0), COALESCE(last_status_at,0), "
            f"{SCHEDULER_ERROR_SCOPE_SQL} AS error_scope, "
            "REPLACE(REPLACE(COALESCE(last_error,''), char(13), ' '), char(10), ' ') "
            "FROM scheduler_metrics WHERE COALESCE(fail_count,0) > 0 "
            "OR COALESCE(miss_count,0) > 0 "
            "ORDER BY (COALESCE(fail_count,0) + COALESCE(miss_count,0)) DESC, job_id LIMIT 20;",
        )
        failure_history_parse_err = ""
        details["scheduler_metrics_failure_history"] = []
        if not structured_failures_err:
            try:
                details["scheduler_metrics_failure_history"] = (
                    _parse_scheduler_failure_history(structured_failures)
                )
            except ValueError as exc:
                failure_history_parse_err = (
                    f"scheduler_metrics_failure_history_parse_failed: {exc}"
                )

        recent, er = sqlite_query(
            client, MORY_DB,
            "SELECT task_key, status, exec_date FROM task_execution_history ORDER BY id DESC LIMIT 10;",
        )
        details["recent_scheduled_tasks"] = recent if not er else f"ERR: {er}"

        db_errors = [
            err
            for err in (
                stale_err,
                recent_failures_err,
                metrics_err,
                cumulative_failures_err,
                structured_failures_err,
                failure_history_parse_err,
                er,
            )
            if err
        ]
        if db_errors:
            status = "ERROR"
            details["_crit"] = details.get("_crit", "") + "; ".join(db_errors)
        elif history_counts["failed"] > 0 or stale_count > 0 or bad_metrics:
            status = "WARN"
            if history_counts["failed"] > 0:
                details["_warn"] = details.get("_warn", "") + (
                    f"persisted_task_failures={history_counts['failed']}; "
                )
            if stale_count > 0:
                details["_warn"] = details.get("_warn", "") + f"stale_running={stale_count}; "
            if bad_metrics:
                details["_warn"] = details.get("_warn", "") + "scheduler_metrics_has_errors; "

        # journal 只补充当前窗口错误，不能替代持久化四态。
        fail_log, _, _ = ssh_run(
            client,
            r'journalctl -u mory-assistant --since "10 minutes ago" --no-pager '
            r'| grep -iE "\[(ERROR|CRITICAL)\]|level=(ERROR|CRITICAL)|traceback|(^|[^[:alnum:]_])(fail(ed|ure)?|error|exception)([^[:alnum:]_=]|$)" '
            r'| grep -viE "EXECUTED|ERROR.*MISSED|EVENT_JOB_|scheduler_monitor.*EVENT|no such|operationalerror|_job_critical|critical_jobs_health|CriticalJobsHealth|HTTP请求失败|HTTP请求成功|Running job|executed successfully|Added job" '
            r'| tail -15',
            timeout=15,
        )
        details["fail_log_10min"] = fail_log or "(none)"
        details["fail_log_10min_count"] = len(
            [line for line in (fail_log or "").splitlines() if line.strip()]
        )
        if fail_log:
            status = "WARN" if status != "ERROR" else "ERROR"
            details["_warn"] = details.get("_warn", "") + "journalctl_has_fail_logs; "

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
        if not cron:
            status = "WARN"
            details["_warn"] = details.get("_warn", "") + "cron_missing; "
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
    layer_statuses = []

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
        return {"round": round_no, "status": "evidence_gap", "ssh_fail": str(e)}

    try:
        # L1
        s1, d1 = l1_vps_check(client)
        layer_statuses.append(s1)
        line1 = (f"[L1 VPS] STATUS={s1} | cpu={d1.get('cpu_usage','?')} | mem_avail={d1.get('mem_avail_pct','?')} | "
             f"disk={d1.get('disk_usage_pct','?')} | load1={d1.get('load1','?')} | net_conn={d1.get('net_conn','?')}")
        if "_warn" in d1: line1 += f" | WARN={d1['_warn']}"
        print(line1); lines.append(line1)
        if s1 == "ERROR": exceptions.append(("L1", d1.get("_exc", "")))
        if s1 != "OK":
            need_review.append(f"L1 {d1.get('_warn') or d1.get('_exc') or s1}")

        # L2
        s2, d2 = l2_service_check(client)
        layer_statuses.append(s2)
        line2 = (f"[L2 SVC] mory-assistant={d2.get('mory-assistant','?')} | "
                 f"mory-dashboard={d2.get('mory-dashboard','?')} | "
                 f"errors_10min={'yes' if d2.get('mory-assistant_errors_10min') and d2.get('mory-assistant_errors_10min') != '(none)' else 'none'}")
        print(line2); lines.append(line2)
        if s2 == "CRITICAL" or s2 == "ERROR":
            exceptions.append(("L2", d2.get("_exc") or d2.get("_crit") or ""))
        if s2 != "OK":
            need_review.append(f"L2 {d2.get('_warn') or d2.get('_crit') or d2.get('_exc') or s2}")

        # L3
        s3, d3 = l3_app_check(client)
        layer_statuses.append(s3)
        line3 = (f"[L3 APP] health={'ok' if 'ok' in d3.get('health_raw','').lower() else 'FAIL'} | "
                 f"version={d3.get('version','?')} | "
                 f"health_http={d3.get('health_http_code','?')}")
        if s3 != "OK":
            line3 += f" | WARN={d3.get('_warn','')}{d3.get('_crit','')}"
        print(line3); lines.append(line3)
        if s3 == "CRITICAL" or s3 == "ERROR":
            exceptions.append(("L3", d3.get("_exc") or d3.get("_crit") or ""))
        if s3 != "OK":
            need_review.append(f"L3 {d3.get('_warn') or d3.get('_crit') or d3.get('_exc') or s3}")

        # L4
        s4, d4 = l4_biz_check(client)
        layer_statuses.append(s4)
        line4 = (f"[L4 BIZ] transactional_task_1h={d4.get('transactional_task_1h','?')} | "
                 f"transactional_task_5min={d4.get('transactional_task_5min','?')} | "
                 f"task_history_total={d4.get('task_history_total','?')} | "
                 f"task_history_latest={_short(d4.get('task_history_latest','?'), 80)} | "
                 f"coverage={d4.get('task_history_coverage','?')} | "
                 f"token_1h={d4.get('token_usage_1h','?')} | token_5min={d4.get('token_usage_5min','?')} | "
                 f"token_cost_1h={d4.get('token_cost_1h_sum','?')} | "
                 f"conversion_1h={d4.get('conversion_1h','?')} | orphan_1h={d4.get('orphan_1h','?')}")
        print(line4); lines.append(line4)
        if s4 == "ERROR":
            exceptions.append(("L4", d4.get("_exc", "")))
        if s4 != "OK":
            need_review.append(f"L4 {d4.get('_warn') or d4.get('_exc') or s4}")

        # L5
        s5, d5 = l5_scheduler_check(client)
        layer_statuses.append(s5)
        line5 = (f"[L5 SCHD] transactional_failed_1h={d5.get('transactional_failed_1h','?')} | "
                 f"coverage={d5.get('task_history_coverage','?')} | "
                 f"watchdog_usec={d5.get('watchdog_usec','?')}")
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
        if s5 != "OK":
            need_review.append(f"L5 {d5.get('_warn') or d5.get('_exc') or s5}")

        # L6
        s6, d6 = l6_watchdog_check(client)
        layer_statuses.append(s6)
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
        if s6 != "OK":
            need_review.append(f"L6 {d6.get('_warn') or d6.get('_exc') or s6}")

    finally:
        try:
            client.close()
        except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
            logging.getLogger(__name__).debug(f'非致命忽略: {_e}')

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
    if "ERROR" in layer_statuses:
        receipt_status = "evidence_gap"
    elif any(status in {"WARN", "CRITICAL"} for status in layer_statuses):
        receipt_status = "failed"
    else:
        receipt_status = "pass"
    return {"round": round_no, "status": receipt_status, "needs_review": need_review}


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
        result = run_single_round(1, 1, log_file)
        return {"pass": 0, "evidence_gap": 2, "failed": 3}[result["status"]]

    if args.loop:
        print(f"[LOOP MODE] 无限循环启动，间隔 {args.interval}s。按 Ctrl+C 终止。")
        i = args.start_round
        while True:
            if i > args.start_round:
                print(f"[SLEEP] waiting {args.interval}s before round {i}...")
                time.sleep(args.interval)
            run_single_round(i, 0, log_file)  # total=0 表示无限
            i += 1

    start = args.start_round
    total = args.rounds
    results = []
    for i in range(start, total + 1):
        # 第 1 轮不 sleep；续跑模式（start>1）第 2 轮起也 sleep，保证与基线间隔正确
        if i > 1:
            print(f"[SLEEP] waiting {args.interval}s before round {i}...")
            time.sleep(args.interval)
        results.append(run_single_round(i, total, log_file))

    print(f"\n[DONE] {total - start + 1} rounds finished. Log: {log_file}")
    statuses = {item["status"] for item in results}
    if "failed" in statuses:
        return 3
    if "evidence_gap" in statuses:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
