#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v5.31.3 VPS 独立看门狗：每 2 分钟检查 /api/health，连续 3 次失败才自动重启服务
缓解 systemd 无 WatchdogSec 的死锁检测问题（P1-2）。
由 cron 每 2 分钟调用：*/2 * * * * cd /home/ubuntu/mory_assistant && /usr/bin/python3 -X utf8 scripts/vps_watchdog.py
"""
import os
import json
import sys
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

_CST = timezone(timedelta(hours=8))

VPS_PATH = "/home/ubuntu/mory_assistant"
LOG_FILE = f"{VPS_PATH}/logs/watchdog.log"
STATE_FILE = f"{VPS_PATH}/logs/watchdog_fail_count"
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 3
HEALTH_URL = "http://localhost:6616/api/health"
MAX_FAIL = 3  # 连续失败 3 次才重启
SERVICE = "mory-assistant"


def _rotate_log_if_needed():
    """限制看门狗日志体积，避免 cron 长期运行耗尽磁盘。"""
    path = Path(LOG_FILE)
    if not path.exists() or path.stat().st_size < MAX_LOG_BYTES:
        return
    path.with_name(f"{path.name}.{LOG_BACKUPS}").unlink(missing_ok=True)
    for index in range(LOG_BACKUPS - 1, 0, -1):
        source = path.with_name(f"{path.name}.{index}")
        target = path.with_name(f"{path.name}.{index + 1}")
        if source.exists():
            source.replace(target)
    path.replace(path.with_name(f"{path.name}.1"))


def log(msg, level="INFO"):
    ts = datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    _rotate_log_if_needed()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        detail = "\n".join(part.strip() for part in (r.stdout, r.stderr) if part.strip())
        return detail, r.returncode
    except Exception as e:
        return f"ERROR: {e}", -1


def get_fail_count():
    try:
        with open(STATE_FILE, "r") as f:
            return int(f.read().strip() or "0")
    except Exception:
        return 0


def set_fail_count(n):
    try:
        with open(STATE_FILE, "w") as f:
            f.write(str(n))
    except Exception as e:
        log(f"写入失败计数失败: {e}", "WARN")


def check_health():
    """返回 (ok, detail)"""
    out, code = run(["curl", "-fsS", "--max-time", "5", HEALTH_URL])
    if code != 0:
        return False, f"curl 失败 code={code}: {out[:100]}"
    try:
        payload = json.loads(out)
    except (TypeError, json.JSONDecodeError) as e:
        return False, f"health 非法JSON: {e}"
    if not isinstance(payload, dict) or str(payload.get("status", "")).lower() != "ok":
        return False, f"health 异常: {out[:100]}"
    return True, out[:100]


def _systemctl_command(*args):
    """root cron 直调 systemctl；手工非 root 运行时仅允许免密 sudo。"""
    is_root = callable(getattr(os, "geteuid", None)) and os.geteuid() == 0
    prefix = [] if is_root else ["sudo", "-n"]
    return [*prefix, "systemctl", *args]


def restart_service(reason):
    """重启服务（用 sudo，需要 ubuntu 用户免密 sudo 或 sudoers 配置）"""
    log(f"🚨 触发服务重启，原因: {reason}", "CRITICAL")
    # 1. 先检查服务状态
    status, _ = run(_systemctl_command("is-active", SERVICE))
    log(f"当前服务状态: {status}")

    # 2. 如果是 deactivating/activating，先强制 kill
    if status in ("deactivating", "activating"):
        log(f"服务卡在 {status}，强制 SIGKILL", "WARN")
        run(_systemctl_command("kill", SERVICE, "--signal=SIGKILL"), timeout=10)
        time.sleep(3)

    # 3. 重启服务
    out, code = run(_systemctl_command("restart", SERVICE), timeout=60)
    if code != 0:
        log(f"systemctl restart 失败 code={code}: {out}", "CRITICAL")
        return False

    # 4. 等待启动
    time.sleep(10)
    new_status, _ = run(_systemctl_command("is-active", SERVICE))
    log(f"重启后服务状态: {new_status}")

    # 5. 验证 /api/health
    ok, detail = check_health()
    if ok:
        log(f"✅ 服务重启成功，/api/health 恢复: {detail}")
        set_fail_count(0)
        return True
    else:
        log(f"🚨 重启后 /api/health 仍失败: {detail}", "CRITICAL")
        return False


def main():
    os.chdir(VPS_PATH)
    if VPS_PATH not in sys.path:
        sys.path.insert(0, VPS_PATH)
    log("=== 看门狗检查开始 ===")

    # 1. 检查 /api/health
    ok, detail = check_health()
    if ok:
        # 健康恢复，重置失败计数
        fail_count = get_fail_count()
        if fail_count > 0:
            log(f"✅ 服务健康恢复（之前失败 {fail_count} 次），重置计数。detail: {detail}")
            set_fail_count(0)
        else:
            log(f"✅ 服务健康: {detail}")
        return

    # 2. 不健康，增加失败计数
    fail_count = get_fail_count() + 1
    set_fail_count(fail_count)
    log(f"⚠️ /api/health 失败（第 {fail_count}/{MAX_FAIL} 次）: {detail}", "WARN")

    # 3. 检查服务状态
    status, _ = run(_systemctl_command("is-active", SERVICE))
    log(f"服务状态: {status}")

    # 4. 如果服务 inactive/failed，立即重启（不等 3 次）
    if status in ("inactive", "failed"):
        log(f"🚨 服务 {status}，立即重启", "CRITICAL")
        restart_service(f"服务 {status}")
        return

    # 5. 如果服务 active 但 /api/health 失败，可能是死锁，累计失败次数
    if fail_count >= MAX_FAIL:
        log(f"🚨 连续 {fail_count} 次失败，判定死锁，触发重启", "CRITICAL")
        restart_service(f"连续 {fail_count} 次 /api/health 失败，疑似死锁")
    else:
        log(f"等待下次检查（还需 {MAX_FAIL - fail_count} 次失败才重启）")


if __name__ == "__main__":
    main()
