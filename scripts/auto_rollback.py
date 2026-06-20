#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动回滚脚本 - 检测部署后健康状态，不健康时自动回滚到上一版本

回滚流程：
1. 执行健康检查（带重试）
2. 如果不健康 → 停止服务 → 切换版本目录 → 重启服务 → 发送告警
3. 回滚后再次验证健康状态

注意：本脚本提供回滚框架，实际执行前需确认版本目录结构正确。
"""

import sys
import os
import json
import time
import paramiko
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.vps_config import ssh_connect

CONFIG_PATH = Path(__file__).parent / "rollback_config.json"


def load_config():
    """加载回滚配置"""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def ssh_exec(ssh_client, cmd, timeout=30):
    """执行远程命令，返回 (stdout, stderr, exit_code)"""
    stdin, stdout, stderr = ssh_client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    return out, err, code


def check_health_with_retry(config, ssh_client):
    """带重试的健康检查"""
    url = config["health_check_url"]
    retries = config.get("retry_count", 3)
    interval = config.get("retry_interval_seconds", 5)

    for attempt in range(1, retries + 1):
        print(f"  健康检查第 {attempt}/{retries} 次...")
        out, err, code = ssh_exec(ssh_client, f"curl -s -o /dev/null -w '%{{http_code}}' {url}")

        if out.strip() == "200":
            print("  ✓ 健康检查通过")
            return True

        print(f"  ✗ HTTP {out} (等待 {interval}s 后重试)")
        if attempt < retries:
            time.sleep(interval)

    return False


def stop_services(config, ssh_client):
    """停止所有服务"""
    print("\n[1/4] 停止服务...")
    for service in config["services"]:
        out, err, code = ssh_exec(ssh_client, f"sudo systemctl stop {service}")
        if code == 0:
            print(f"  ✓ {service} 已停止")
        else:
            print(f"  ✗ {service} 停止失败: {err}")


def swap_versions(config, ssh_client):
    """切换版本目录（当前 ↔ 上一版本）"""
    current = config["current_version_path"]
    previous = config["previous_version_path"]
    temp = f"{current}_rollback_tmp"

    print("\n[2/4] 切换版本目录...")

    # 检查上一版本目录是否存在
    out, _, _ = ssh_exec(ssh_client, f"test -d {previous} && echo 'exists' || echo 'missing'")
    if out != "exists":
        print(f"  ✗ 上一版本目录不存在: {previous}")
        print("  回滚中止！请先确保上一版本备份存在。")
        return False

    # 三步切换：current → temp, previous → current, temp → previous
    commands = [
        f"sudo rm -rf {temp}",
        f"sudo mv {current} {temp}",
        f"sudo mv {previous} {current}",
        f"sudo mv {temp} {previous}",
    ]

    for cmd in commands:
        _, err, code = ssh_exec(ssh_client, cmd)
        if code != 0:
            print(f"  ✗ 目录切换失败: {cmd} → {err}")
            # 尝试恢复
            ssh_exec(ssh_client, f"sudo test -d {temp} && sudo mv {temp} {current}")
            return False

    print(f"  ✓ 版本已切换: {current} ↔ {previous}")
    return True


def start_services(config, ssh_client):
    """重启所有服务"""
    print("\n[3/4] 重启服务...")
    for service in config["services"]:
        out, err, code = ssh_exec(ssh_client, f"sudo systemctl start {service}")
        if code == 0:
            print(f"  ✓ {service} 已启动")
        else:
            print(f"  ✗ {service} 启动失败: {err}")

    # 等待服务启动
    print("  等待服务启动 (5s)...")
    time.sleep(5)


def send_alert(config, reason):
    """发送告警通知（通过 Telegram Bot）"""
    alert_cfg = config.get("alert", {})
    if not alert_cfg.get("enabled", False):
        print("\n[4/4] 告警已禁用，跳过")
        return

    print("\n[4/4] 发送告警...")

    token_env = alert_cfg.get("telegram_bot_token_env", "TG_TOKEN")
    chat_id_env = alert_cfg.get("admin_chat_id_env", "ADMIN_ID")

    # 从 .env 读取凭据
    env_path = Path(__file__).resolve().parent.parent / ".env"
    env_vars = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip()

    token = env_vars.get(token_env, "")
    chat_id = env_vars.get(chat_id_env, "")

    if not token or not chat_id:
        print(f"  ✗ 告警凭据缺失 ({token_env} / {chat_id_env})，跳过")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = alert_cfg.get("message_template", "⚠️ 自动回滚触发\n时间: {timestamp}\n原因: {reason}")
    message = message.format(timestamp=timestamp, reason=reason)

    try:
        import requests
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=10,
        )
        if resp.status_code == 200:
            print("  ✓ 告警已发送到 Telegram")
        else:
            print(f"  ✗ Telegram 发送失败: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  ✗ 告警发送失败: {e}")


def verify_rollback(config, ssh_client):
    """回滚后验证健康状态"""
    print("\n[验证] 回滚后健康检查...")
    return check_health_with_retry(config, ssh_client)


def main():
    """主函数：检测 → 回滚 → 验证"""
    config = load_config()

    print("=" * 50)
    print("Mory小助理 · 自动回滚系统")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # 建立 SSH 连接
    client = paramiko.SSHClient()
    ssh_connect(client)

    # 第一步：健康检查
    print("\n[检测] 执行健康检查...")
    healthy = check_health_with_retry(config, client)

    if healthy:
        print("\n✓ 服务健康，无需回滚。")
        client.close()
        return {"action": "none", "status": "healthy"}

    print("\n✗ 服务不健康，准备回滚...")

    # 第二步：停止服务
    stop_services(config, client)

    # 第三步：切换版本目录
    swapped = swap_versions(config, client)
    if not swapped:
        # 目录切换失败，尝试重启原服务
        print("\n✗ 版本切换失败，尝试恢复原服务...")
        start_services(config, client)
        send_alert(config, "版本目录切换失败，已尝试恢复原服务")
        client.close()
        return {"action": "rollback_failed", "status": "failed"}

    # 第四步：重启服务
    start_services(config, client)

    # 第五步：验证回滚结果
    rollback_ok = verify_rollback(config, client)

    # 第六步：发送告警
    if rollback_ok:
        send_alert(config, "部署后健康检查失败，已自动回滚到上一版本，回滚后服务正常。")
    else:
        send_alert(config, "部署后健康检查失败，已自动回滚，但回滚后服务仍不健康！需人工介入！")

    client.close()

    result_status = "rolled_back_healthy" if rollback_ok else "rolled_back_unhealthy"
    print(f"\n{'=' * 50}")
    print(f"回滚完成: {result_status}")
    print(f"{'=' * 50}")

    return {"action": "rollback", "status": result_status}


if __name__ == "__main__":
    result = main()
    sys.exit(0 if result["status"] in ("healthy", "rolled_back_healthy") else 1)
