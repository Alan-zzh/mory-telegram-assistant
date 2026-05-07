#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VPS Dashboard 统一修复脚本 - 诊断+修复+验证全流程"""

import paramiko
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS


def ssh_exec(client, cmd, timeout=15):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out, err


def step(client, name, cmd, show_output=True):
    print(f"\n{'='*60}")
    print(f"【{name}】")
    print('='*60)
    out, err = ssh_exec(client, cmd)
    if show_output:
        if out:
            print(out[:3000])
        if err and 'Warning' not in err:
            print(f"ERR: {err[:500]}")
    return out, err


def main():
    if not VPS_HOST or not VPS_PASS:
        print("❌ VPS配置缺失，请检查 .env 文件中的 VPS_HOST 和 VPS_SSH_PASS")
        sys.exit(1)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.WarningPolicy())

    print("🔌 连接VPS...")
    try:
        client.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASS, timeout=15)
    except Exception as e:
        print(f"❌ 连接失败：{e}")
        sys.exit(1)

    # ── Phase 1: 诊断 ──
    print("\n" + "═"*60)
    print("  Phase 1: 诊断")
    print("═"*60)

    step(client, "Dashboard服务状态", "systemctl status mory-dashboard --no-pager -l")
    step(client, "8080端口占用", "ss -tlnp | grep 8080 || echo '端口未被占用'")
    step(client, "Dashboard相关进程", "ps -ef | grep dashboard | grep -v grep || echo '无Dashboard进程'")
    step(client, "系统资源", "free -h && echo '---' && df -h /")

    # ── Phase 2: 修复 ──
    print("\n" + "═"*60)
    print("  Phase 2: 修复")
    print("═"*60)

    step(client, "停止Dashboard服务", "sudo systemctl stop mory-dashboard", show_output=False)
    time.sleep(1)

    step(client, "终止占用8080端口的进程", "sudo fuser -k 8080/tcp 2>/dev/null || true", show_output=False)
    time.sleep(1)

    step(client, "强制终止所有Dashboard进程", "sudo pkill -9 -f 'dashboard/app.py' || true; sudo pkill -9 -f 'start_dashboard.py' || true", show_output=False)
    time.sleep(2)

    step(client, "检查端口释放", "ss -tlnp | grep 8080 || echo '✅ 端口已释放'")

    # ── Phase 3: 重启 ──
    print("\n" + "═"*60)
    print("  Phase 3: 重启")
    print("═"*60)

    step(client, "重新加载systemd", "sudo systemctl daemon-reload", show_output=False)
    time.sleep(1)

    step(client, "启动Dashboard服务", "sudo systemctl start mory-dashboard", show_output=False)
    time.sleep(3)

    # ── Phase 4: 验证 ──
    print("\n" + "═"*60)
    print("  Phase 4: 验证")
    print("═"*60)

    step(client, "Dashboard服务状态", "systemctl status mory-dashboard --no-pager -l")
    step(client, "8080端口监听", "ss -tlnp | grep 8080 || echo '❌ 未监听'")

    client.close()
    print("\n=== Dashboard修复完成 ===")


if __name__ == "__main__":
    main()
