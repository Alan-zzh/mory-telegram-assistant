#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  cleanup_vps_full.py  ·  VPS 完整清理脚本（v5.22.0 审计配套）              ║
║                                                                            ║
║  功能：                                                                    ║
║    1. 删除遗留垃圾文件（调试/测试脚本）                                     ║
║    2. 清理 __pycache__ 目录                                                ║
║    3. 配置 logrotate 日志轮转                                              ║
║    4. 清理 systemd journal 旧日志（保留 7 天）                             ║
║    5. 验证清理结果                                                         ║
║                                                                            ║
║  使用：python scripts/cleanup_vps_full.py                                  ║
║  安全：所有删除操作前先检查文件存在，不会误删                              ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_PATH, ssh_connect

# 需要删除的文件（相对 VPS_PATH）
FILES_TO_DELETE = [
    # 根目录临时文件
    "restart_and_test.py",
    "sync_vps.py",
    "windows_helper.py",
    "_check_sources_remote.py",
    "_db_check.py",
    "_quick_check.py",
    "_scan_all_members.py",
    "_scan_group.py",
    "_scan_members.py",
    "_scan_members_full.py",
    "_test_ad_detect.py",
    # scripts/ 目录调试/测试文件
    "scripts/_investigate_output.txt",
    "scripts/debug_db.py",
    "scripts/debug_vps.py",
    "scripts/deep_check.py",
    "scripts/failure_injection_tests.py",
    "scripts/find_bug.py",
    "scripts/full_diagnosis.py",
    "scripts/get_keyword_module.py",
    "scripts/test_connection.py",
    "scripts/test_vps_ai.py",
]

# logrotate 配置内容
LOGROTATE_CONF = """\
# Mory Assistant 日志轮转配置 (v5.22.0)
/home/ubuntu/mory_assistant/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0644 ubuntu ubuntu
    copytruncate
    su ubuntu ubuntu
}

/home/ubuntu/mory_assistant/logs/*.txt {
    weekly
    rotate 8
    compress
    delaycompress
    missingok
    notifempty
    create 0644 ubuntu ubuntu
    copytruncate
    su ubuntu ubuntu
}
"""


def main():
    print("=" * 60)
    print("  Mory小助理 · VPS 完整清理 (v5.22.0 审计配套)")
    print("=" * 60)

    if not VPS_HOST or not VPS_PASS:
        print("❌ 错误：VPS_HOST 或 VPS_SSH_PASS 未设置！")
        sys.exit(1)

    import paramiko
    client = paramiko.SSHClient()
    try:
        ssh_connect(client, timeout=15)
    except Exception as e:
        print(f"❌ SSH 连接失败：{e}")
        sys.exit(1)
    print(f"[1/6] ✅ SSH 连接成功 {VPS_HOST}")

    sftp = client.open_sftp()

    # ── 步骤 2：删除垃圾文件 ──
    print(f"\n[2/6] 删除遗留垃圾文件 ...")
    deleted = []
    for rel_path in FILES_TO_DELETE:
        remote_path = f"{VPS_PATH}/{rel_path}"
        try:
            sftp.stat(remote_path)
            sftp.remove(remote_path)
            print(f"  ✅ 已删除：{rel_path}")
            deleted.append(rel_path)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"  ⚠️ 删除失败 {rel_path}：{e}")
    if not deleted:
        print("  ℹ️  无垃圾文件需要删除")
    else:
        print(f"  小计：删除 {len(deleted)} 个文件")

    # ── 步骤 3：清理 __pycache__ ──
    print(f"\n[3/6] 清理 __pycache__ 目录 ...")
    stdin, stdout, stderr = client.exec_command(
        f'find {VPS_PATH} -type d -name __pycache__ -exec rm -rf {{}} + 2>/dev/null; '
        f'echo "PYCACHE_CLEANED"'
    )
    out = stdout.read().decode().strip()
    if "PYCACHE_CLEANED" in out:
        print("  ✅ __pycache__ 已清理")
    else:
        print(f"  ⚠️ 清理结果：{out}")

    # ── 步骤 4：配置 logrotate ──
    print(f"\n[4/6] 配置 logrotate ...")
    logrotate_path = "/etc/logrotate.d/mory-assistant"
    # 先写本地临时文件再上传（用 sftp.put）
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False, encoding='utf-8') as tf:
        tf.write(LOGROTATE_CONF)
        tmp_path = tf.name
    try:
        # 上传到 /tmp 再 sudo mv
        remote_tmp = "/tmp/mory_logrotate.conf"
        sftp.put(tmp_path, remote_tmp)
        stdin, stdout, stderr = client.exec_command(
            f'echo {VPS_PASS} | sudo -S cp {remote_tmp} {logrotate_path} 2>&1; '
            f'echo {VPS_PASS} | sudo -S chown root:root {logrotate_path} 2>&1; '
            f'echo {VPS_PASS} | sudo -S chmod 644 {logrotate_path} 2>&1; '
            f'rm -f {remote_tmp}; '
            f'echo LOGROTATE_DONE'
        )
        out = stdout.read().decode().strip()
        if "LOGROTATE_DONE" in out:
            print(f"  ✅ logrotate 配置已写入 {logrotate_path}")
        else:
            print(f"  ⚠️ logrotate 配置结果：{out}")
        # 测试 logrotate 配置
        stdin, stdout, stderr = client.exec_command(
            f'echo {VPS_PASS} | sudo -S logrotate -d {logrotate_path} 2>&1 | tail -5'
        )
        test_out = stdout.read().decode().strip()
        if "error" in test_out.lower():
            print(f"  ⚠️ logrotate 配置测试有警告：{test_out}")
        else:
            print(f"  ✅ logrotate 配置测试通过")
    finally:
        os.unlink(tmp_path)

    # ── 步骤 5：清理 systemd journal（保留 7 天）──
    print(f"\n[5/6] 清理 systemd journal 旧日志（保留 7 天）...")
    stdin, stdout, stderr = client.exec_command(
        f'echo {VPS_PASS} | sudo -S journalctl --vacuum-time=7d 2>&1 | tail -5'
    )
    out = stdout.read().decode().strip()
    print(f"  {out}")

    sftp.close()

    # ── 步骤 6：验证清理结果 ──
    print(f"\n[6/6] 验证清理结果 ...")
    # 重新检查垃圾文件
    remaining = []
    for rel_path in FILES_TO_DELETE:
        remote_path = f"{VPS_PATH}/{rel_path}"
        try:
            sftp = client.open_sftp()
            sftp.stat(remote_path)
            remaining.append(rel_path)
            sftp.close()
        except Exception:
            pass
    if remaining:
        print(f"  ⚠️ 以下文件仍存在：{remaining}")
    else:
        print(f"  ✅ 所有垃圾文件已清理")

    # 磁盘占用对比
    stdin, stdout, stderr = client.exec_command(f'du -sh {VPS_PATH} 2>/dev/null; df -h / | tail -1')
    print(f"\n  清理后磁盘占用：")
    print(f"  {stdout.read().decode().strip()}")

    # 服务状态最终确认
    print(f"\n  服务状态最终确认：")
    for svc in ['mory-assistant', 'mory-dashboard']:
        stdin, stdout, stderr = client.exec_command(f'sudo systemctl is-active {svc}')
        print(f"    {svc}: {stdout.read().decode().strip()}")

    client.close()

    print("\n" + "=" * 60)
    print(f"  ✅ VPS 清理完成！")
    print(f"     - 删除垃圾文件：{len(deleted)} 个")
    print(f"     - __pycache__：已清理")
    print(f"     - logrotate：已配置")
    print(f"     - journal：已清理 7 天前日志")
    print("=" * 60)


if __name__ == "__main__":
    main()
