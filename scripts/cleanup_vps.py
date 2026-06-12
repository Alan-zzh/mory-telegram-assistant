#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  cleanup_vps.py  ·  VPS 服务器垃圾文件清理脚本                            ║
║                                                                            ║
║  功能：连接 VPS → 列出目录 → 识别垃圾文件 → 安全删除                        ║
║  使用：python scripts/cleanup_vps.py                                       ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent

# 导入 VPS 配置
sys.path.insert(0, str(ROOT))
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_PATH, ssh_connect

# 需要删除的文件名模式
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
    "scripts/test_vps_ai.py",
]


def main():
    print("=" * 60)
    print("  Mory小助理 · VPS 服务器垃圾文件清理")
    print("=" * 60)

    # 1. 前置检查
    if not VPS_HOST or not VPS_PASS:
        print("❌ 错误：VPS_HOST 或 VPS_SSH_PASS 未设置！")
        print("   请在 .env 文件中配置 VPS_HOST 和 VPS_SSH_PASS")
        sys.exit(1)

    # 2. 连接 VPS
    print(f"\n[1/4] 连接 VPS {VPS_HOST}:{VPS_PORT} ...")
    import paramiko
    client = paramiko.SSHClient()
    try:
        ssh_connect(client, timeout=15)
    except Exception as e:
        print(f"❌ SSH 连接失败：{e}")
        sys.exit(1)
    print("  ✅ 连接成功")

    sftp = client.open_sftp()

    # 3. 列出项目目录结构
    print(f"\n[2/4] 列出服务器项目目录 {VPS_PATH} ...")
    try:
        files = sftp.listdir(VPS_PATH)
        print("  根目录文件：")
        for f in sorted(files):
            print(f"    - {f}")

        # 列出 scripts/ 目录
        try:
            sftp.listdir(f"{VPS_PATH}/scripts")
            print("\n  scripts/ 目录存在")
        except Exception:
            print("\n  scripts/ 目录不存在")
    except Exception as e:
        print(f"  ⚠️ 列出目录失败：{e}")

    # 4. 删除垃圾文件
    print(f"\n[3/4] 开始删除垃圾文件 ...")
    deleted = []
    for rel_path in FILES_TO_DELETE:
        remote_path = f"{VPS_PATH}/{rel_path}"
        try:
            # 检查文件是否存在
            sftp.stat(remote_path)
            # 删除文件
            sftp.remove(remote_path)
            print(f"  ✅ 已删除：{rel_path}")
            deleted.append(rel_path)
        except FileNotFoundError:
            print(f"  ℹ️  不存在：{rel_path}")
        except Exception as e:
            print(f"  ⚠️ 删除失败 {rel_path}：{e}")

    # 5. 验证结果
    print(f"\n[4/4] 验证清理结果 ...")
    remaining = []
    for rel_path in FILES_TO_DELETE:
        remote_path = f"{VPS_PATH}/{rel_path}"
        try:
            sftp.stat(remote_path)
            remaining.append(rel_path)
        except Exception:
            pass

    sftp.close()
    client.close()

    # 总结
    print("\n" + "=" * 60)
    if deleted:
        print(f"  ✅ 清理完成！共删除 {len(deleted)} 个文件")
        for f in deleted:
            print(f"    - {f}")
    else:
        print("  ℹ️  服务器上没有需要清理的垃圾文件")

    if remaining:
        print(f"\n  ⚠️ 以下文件仍存在：")
        for f in remaining:
            print(f"    - {f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
