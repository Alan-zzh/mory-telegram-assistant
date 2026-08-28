#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时 SSH 助手 - 读取 .env 凭据并执行远程命令"""
import sys
import paramiko
from dotenv import dotenv_values
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"  # [v5.15.4 修复] 项目根目录 .env
sys.path.insert(0, str(ENV_PATH.parent))
from core.vps_config import secure_paramiko_connect_kwargs

env = dotenv_values(ENV_PATH)

HOST = env.get("VPS_HOST", "43.159.168.175")
PORT = int(env.get("VPS_PORT", "22"))
USER = env.get("VPS_USER", "ubuntu")
PASS = env.get("VPS_SSH_PASS", "")
REMOTE = env.get("VPS_PATH", "/home/ubuntu/mory_assistant")


def run_ssh(cmd, timeout=60, as_root=False):
    """执行远程命令，返回 (stdout, stderr, exit_code)"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, PORT, USER, PASS, timeout=15, banner_timeout=15,
                       auth_timeout=15, allow_agent=False, look_for_keys=False,
                       **secure_paramiko_connect_kwargs())
    except Exception as e:
        return "", f"SSH connect failed: {e}", -1

    full_cmd = cmd
    if as_root:
        # 密码经 stdin 写入（get_pty），不再拼进命令行，避免远端 ps 可见
        full_cmd = f"sudo -S -p '' bash -c {cmd!r}"

    try:
        stdin, stdout, stderr = client.exec_command(full_cmd, timeout=timeout, get_pty=True)
        if as_root and PASS:
            stdin.write(PASS + "\n")
            stdin.flush()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        return out, err, exit_code
    except Exception as e:
        return "", f"exec failed: {e}", -1
    finally:
        client.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python _ssh_helper.py <cmd>")
        sys.exit(1)
    cmd = sys.argv[1]
    out, err, code = run_ssh(cmd)
    if out:
        print(out)
    if err:
        print("[STDERR]", err, file=sys.stderr)
    sys.exit(code)
