#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  deploy_vps.py  ·  一键部署脚本（systemd管理）                           ║
║                                                                            ║
║  功能：停止Bot → 上传代码 → 安全合并配置 → 启动Bot → 验证部署             ║
║  使用：python deploy_vps.py                                               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import io
import json
import os
import sys
import time
from pathlib import Path

# Windows 终端默认 GBK，强制用 UTF-8 输出，防止 emoji 等 Unicode 字符炸裂
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", write_through=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", write_through=True)

import paramiko

# 项目根目录
ROOT = Path(__file__).resolve().parent

# 导入部署工具
sys.path.insert(0, str(ROOT))
from core.deploy_utils import safe_upload_config, upload_files, verify_deployment, sync_runtime_fields_from_vps, sync_env_api_key, ensure_remote_dir
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_KEY_FILES, VPS_PATH, ssh_connect

# 绝不上传的文件名（含垃圾/临时/凭据/旧备份，v5.16.5 补）
EXCLUDE_NAMES = {
    "config.json", ".env", "mory.db", "deploy_vps.py", "__pycache__", ".pyc",
    # 垃圾/临时/凭据备份
    ".env.bak", "_ssh_known_hosts", "dashboard.log", "fault_alerts.log",
    # 旧部署脚本残留（v5.16.5 删除本地后防御）
    "start.sh", "deploy.bat", "start_dashboard.bat", "docker_deploy.sh",
}

# 【死代码清理列表】本地已删除的文件，部署时自动从服务器删除，保持服务器干净
# 新增死代码直接加进来，部署时自动清理
DEAD_REMOTE_FILES = [
    "core/cache_manager.py",
    "core/migrate.py",
    "core/monitoring.py",
    "core/rate_limiter.py",
    "core/router_statistics.py",
    "modules/predictive_patrol.py",
    "docs/review-report-20260621.md",
]

# 需要动态扫描的目录（递归收集所有 .py 文件）
SCAN_DIRS = ["core", "modules", "dashboard", "scripts", "tasks"]  # [v5.31.2] 修复：tasks/ 任务调度器模块必须同步部署

# 根目录下需要上传的文件
ROOT_FILES = ["main.py", "version.py", "windows_helper.py", "start_dashboard.py"]

# 需要上传到 /etc/systemd/system/ 的服务文件
# [v5.31.2 整改] 只保留双核心服务；mory-media-* 是引用不存在的 `main.py --media`
# 参数的坏桩（启动必崩），已从仓库删除，不再部署。
SERVICE_FILES = [
    "config/mory-dashboard.service",
    "config/mory-assistant.service",
]


def _collect_upload_files():
    """动态收集所有需要上传的 .py 文件"""
    files = []
    # 根目录文件
    for f in ROOT_FILES:
        if (ROOT / f).exists():
            files.append(f)
    # 递归扫描子目录
    for dir_name in SCAN_DIRS:
        dir_path = ROOT / dir_name
        if not dir_path.exists():
            continue
        for py_file in sorted(dir_path.rglob("*.py")):
            rel = py_file.relative_to(ROOT).as_posix()
            # 跳过排除文件
            if any(exc in rel for exc in EXCLUDE_NAMES):
                continue
            files.append(rel)
    return files


UPLOAD_FILES = _collect_upload_files()


def _cleanup_old_backups(backup_dir: str = "backups", keep: int = 2):
    """清理本地备份目录，只保留最近 keep 个备份"""
    backup_path = ROOT / backup_dir
    if not backup_path.exists():
        return
    # 按名称排序（名称含时间戳，自然排序即时间顺序）
    all_backups = sorted([d for d in backup_path.iterdir() if d.is_dir() and d.name.startswith("server_pull_")])
    to_delete = all_backups[:-keep] if len(all_backups) > keep else []
    for d in to_delete:
        try:
            # 删除目录及其内容
            import shutil
            shutil.rmtree(str(d))
            print(f"  🗑 已清理旧备份：{d.name}")
        except Exception as e:
            print(f"  ⚠️ 清理 {d.name} 失败：{e}")


def main():
    print("=" * 60)
    print("  Mory小助理 · 一键部署到VPS")
    print("=" * 60)

    # 1. 前置检查
    if not VPS_HOST or (not VPS_PASS and not VPS_KEY_FILES):
        print("❌ 错误：VPS_HOST 或 SSH 凭据未设置！")
        print("   请在 .env 文件中配置 VPS_HOST，并配置 VPS_SSH_PASS 或 VPS_SSH_KEY")
        sys.exit(1)

    local_config_path = ROOT / "config.json"
    if not local_config_path.exists():
        print("❌ 错误：本地 config.json 不存在！")
        print("   请先从 config.json.example 复制并填写配置")
        sys.exit(1)

    with open(local_config_path, "r", encoding="utf-8") as f:
        local_cfg = json.load(f)

    # 2. 连接VPS
    print(f"\n[1/5] 连接VPS {VPS_HOST}:{VPS_PORT} ...")
    client = paramiko.SSHClient()
    try:
        ssh_connect(client, timeout=15)
    except Exception as e:
        print(f"❌ SSH连接失败：{e}")
        sys.exit(1)
    print("  ✅ 连接成功")

    sftp = client.open_sftp()
    try:
        sftp.get_channel().settimeout(60)
    except Exception as e:
        print(f"  ⚠️ SFTP超时设置失败（非致命）：{e}")

    # 记录是否已停止服务（finally 块需要知道要不要重启）
    services_stopped = False
    deploy_ok = False

    # ═══════════════════════════════════════════════════════════════
    #  核心部署块：任何异常或超时，finally 保证服务重启
    # ═══════════════════════════════════════════════════════════════
    try:
        # 3. 拉回线上运行时配置（投喂内容以线上为准）
        print("\n[2/5] 同步线上运行时配置到本地 ...")
        try:
            from core.deploy_utils import fetch_remote_config
            vps_cfg = fetch_remote_config(sftp, VPS_PATH)
            if vps_cfg:
                local_cfg, synced = sync_runtime_fields_from_vps(local_cfg, vps_cfg)
                if synced:
                    with open(local_config_path, "w", encoding="utf-8") as f:
                        json.dump(local_cfg, f, ensure_ascii=False, indent=2)
                    print(f"  ✅ 已同步 {len(synced)} 个字段：{', '.join(synced[:5])}{'...' if len(synced) > 5 else ''}")
                else:
                    print("  ℹ️ 线上配置与本地一致，无需同步")
            else:
                print("  ⚠️ 无法读取VPS配置，跳过同步")
        except Exception as e:
            print(f"  ⚠️ 同步失败（非致命）：{e}")

        # 4. 停止Bot（systemd）→ 标记 services_stopped
        print("\n[3/5] 停止Bot服务 ...")
        stdin, stdout, stderr = client.exec_command("sudo systemctl stop mory-assistant mory-dashboard", timeout=30)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code == 0:
            print("  ✅ Bot和Dashboard已停止")
        else:
            err = stderr.read().decode("utf-8", errors="replace").strip()
            print(f"  ⚠️ 停止服务返回码 {exit_code}：{err}")
        services_stopped = True  # 不管停没停成功，保险都标记

        time.sleep(2)

        # 5. 上传代码文件
        print("\n[4/5] 上传代码文件 ...")
        files_to_upload = []
        for rel_path in UPLOAD_FILES:
            local_full = ROOT / rel_path
            if local_full.exists():
                remote_path = f"{VPS_PATH}/{rel_path}"
                files_to_upload.append((rel_path, remote_path))

        uploaded = upload_files(sftp, str(ROOT), VPS_PATH, files_to_upload,
            progress_cb=lambda done, total: print(f"  ⏳ 上传进度: {done}/{total}", end="\r") if done % 20 == 0 or done == total else None)
        print(f"\r  ✅ 已上传 {len(uploaded)}/{len(files_to_upload)} 个文件" + " " * 20)

        # 【死代码清理】删除本地已移除的文件，保持服务器整洁
        print("\n  清理服务器死代码文件 ...")
        deleted_count = 0
        for dead_rel in DEAD_REMOTE_FILES:
            remote_dead = f"{VPS_PATH}/{dead_rel}"
            try:
                sftp.stat(remote_dead)
                sftp.remove(remote_dead)
                print(f"  🗑 已删除死代码：{dead_rel}")
                deleted_count += 1
            except FileNotFoundError:
                pass  # 文件本来就不存在，跳过
            except Exception as e:
                print(f"  ⚠️ 删除 {dead_rel} 失败：{e}")
        if deleted_count == 0:
            print("  ℹ️ 无死代码需要清理")

        # 确保 logs/ + config/ 目录存在
        ensure_remote_dir(sftp, f"{VPS_PATH}/logs")
        ensure_remote_dir(sftp, f"{VPS_PATH}/config")

        # 上传其他非Python文件。requirements.lock 存在时一并上传，生产环境优先使用锁定依赖。
        for extra in ["requirements.lock", "requirements.txt", "requirements.in", "Dockerfile", "docker-compose.yml"]:
            local_extra = ROOT / extra
            if local_extra.exists():
                try:
                    sftp.put(str(local_extra), f"{VPS_PATH}/{extra}")
                    print(f"  ✅ {extra}")
                except Exception as e:
                    print(f"  ⚠️ {extra} 上传失败：{e}")

        print("\n  安装/同步 Python 依赖 ...")
        install_cmd = (
            f"cd {VPS_PATH} && "
            "(python3 -m pip install --user -r requirements.lock --break-system-packages "
            "|| python3 -m pip install --user -r requirements.lock) "
            "&& python3 -m pip check"
        )
        stdin, stdout, stderr = client.exec_command(install_cmd, timeout=300)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
        if exit_code == 0:
            print("  ✅ requirements.lock 已安装，pip check 通过")
        else:
            print(f"  ❌ requirements.lock 安装/校验失败（返回码 {exit_code}）")
            tail = "\n".join((out + "\n" + err).splitlines()[-40:])
            print(tail)
            raise RuntimeError("VPS Python 依赖同步失败")

        print("\n  清理远端运行态缓存 ...")
        cleanup_cmd = (
            f"cd {VPS_PATH} && "
            "find . -type d \\( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \\) "
            "-prune -exec rm -rf {} + && "
            "find . -type f -name '*.pyc' -delete && "
            "rm -f reload_flag"
        )
        stdin, stdout, stderr = client.exec_command(cleanup_cmd, timeout=60)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code == 0:
            print("  ✅ 远端缓存与 reload_flag 已清理")
        else:
            err = stderr.read().decode("utf-8", errors="replace").strip()
            print(f"  ⚠️ 远端缓存清理返回码 {exit_code}：{err}")

        # 上传systemd服务文件到 /etc/systemd/system/
        print("\n  上传systemd服务文件 ...")
        for svc_rel in SERVICE_FILES:
            local_svc = ROOT / svc_rel
            if local_svc.exists():
                svc_name = Path(svc_rel).name
                try:
                    sftp.put(str(local_svc), f"/tmp/{svc_name}")
                    stdin, stdout, stderr = client.exec_command(
                        f"sudo mv /tmp/{svc_name} /etc/systemd/system/{svc_name}", timeout=10)
                    exit_code = stdout.channel.recv_exit_status()
                    if exit_code == 0:
                        print(f"  ✅ {svc_name} → /etc/systemd/system/")
                    else:
                        err = stderr.read().decode("utf-8", errors="replace").strip()
                        print(f"  ⚠️ {svc_name} 移动失败：{err}")
                except Exception as e:
                    print(f"  ⚠️ {svc_name} 上传失败：{e}")

        # daemon-reload + enable dashboard
        stdin, stdout, stderr = client.exec_command(
            "sudo systemctl daemon-reload && sudo systemctl enable mory-dashboard", timeout=15)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code == 0:
            print("  ✅ daemon-reload完成，mory-dashboard已enable")
        else:
            err = stderr.read().decode("utf-8", errors="replace").strip()
            print(f"  ⚠️ daemon-reload/enable返回码 {exit_code}：{err}")

        # 安全上传config.json
        print("\n  安全上传 config.json ...")
        merged = safe_upload_config(sftp, local_cfg, VPS_PATH)
        print("  ✅ config.json 已安全合并上传（密钥字段已保护）")

        # 同步.env中的API密钥和Token
        api_key = local_cfg.get("API_KEY", "")
        token = local_cfg.get("TOKEN", "")
        if api_key or token:
            try:
                sync_env_api_key(sftp, VPS_PATH, api_key, token)
            except Exception as e:
                print(f"  ⚠️ .env同步失败（非致命）：{e}")

        sftp.close()

        # 清理旧备份
        print("\n  清理本地旧备份 ...")
        _cleanup_old_backups()
        try:
            stdin, stdout, stderr = client.exec_command(
                f"ls -td {VPS_PATH}/backups/server_pull_*/ 2>/dev/null | tail -n +3 | head -20", timeout=10)
            old_dirs = stdout.read().decode("utf-8", errors="replace").strip().split("\n")
            for old_dir in old_dirs:
                if old_dir.strip():
                    client.exec_command(f"rm -rf {old_dir.strip()}", timeout=10)
                    print(f"  🗑 VPS旧备份已清理：{old_dir.strip().split('/')[-1]}")
        except Exception as e:
            print(f"  ⚠️ VPS备份清理跳过：{e}")

        # gunicorn+gevent 检查（已安装则跳过，避免 apt 超时）
        print("\n  检查 gunicorn + gevent ...")
        try:
            stdin, stdout, stderr = client.exec_command(
                "python3 -c 'import gunicorn, gevent; print(\"already installed\")' 2>&1", timeout=15)
            g_installed = stdout.read().decode("utf-8", errors="replace").strip()
            if "already installed" in g_installed:
                print(f"  ✅ gunicorn+gevent 已就绪")
            else:
                print("  ⏳ 安装 gunicorn+gevent ...")
                stdin, stdout, stderr = client.exec_command(
                    "sudo apt install -y python3-gunicorn python3-gevent 2>&1", timeout=180)
                out = stdout.read().decode("utf-8", errors="replace").strip()
                exit_code = stdout.channel.recv_exit_status()
                print(f"  ✅ gunicorn+gevent 已就绪" if exit_code == 0 else f"  ⚠️ apt安装输出: {err[:200]}")
        except Exception as e:
            print(f"  ⚠️ gunicorn检查/安装失败（非致命）: {e}")

        # 6. 启动Bot（systemd）→ 取消保险标记
        print("\n[5/5] 启动Bot服务 ...")
        stdin, stdout, stderr = client.exec_command("sudo systemctl start mory-assistant mory-dashboard", timeout=30)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code == 0:
            print("  ✅ Bot和Dashboard已启动")
            services_stopped = False  # 已重启成功，finally 不用再管
        else:
            err = stderr.read().decode("utf-8", errors="replace").strip()
            print(f"  ❌ 启动失败：{err}")
            # services_stopped 仍为 True，finally 会兜底重试

        time.sleep(3)

        # 7. 验证部署
        print("\n验证部署结果 ...")
        deploy_ok = verify_deployment(client, VPS_PATH)

    except Exception as e:
        print(f"\n❌ 部署过程异常：{e}")
        print("  保险机制将自动恢复服务...")

    finally:
        # ── 🛡️ 保险：无论部署成功/失败/超时，确保服务在跑 ──
        if services_stopped:
            print("\n🛡️ [保险触发] 检测到服务可能未启动，自动恢复中...")
            retry_count = 0
            while retry_count < 3:
                try:
                    stdin_r, stdout_r, stderr_r = client.exec_command(
                        "sudo systemctl start mory-assistant mory-dashboard", timeout=30)
                    rc = stdout_r.channel.recv_exit_status()
                    if rc == 0:
                        print("  ✅ 保险恢复成功：mory-assistant + mory-dashboard 已启动")
                        services_stopped = False
                        break
                    retry_count += 1
                    time.sleep(2)
                except Exception as ex:
                    print(f"  ⚠️ 保险恢复第{retry_count+1}次异常：{ex}")
                    retry_count += 1
                    time.sleep(2)
            if services_stopped:
                print("  ❌ 保险恢复失败，请手动执行：")
                print("     sudo systemctl start mory-assistant mory-dashboard")
        # 关闭 SSH
        try:
            client.close()
        except Exception as e:
            logger.debug(f"操作异常: {e}")
    # ── 输出最终结果 ──
    if deploy_ok:
        print("\n" + "=" * 60)
        print("  ✅ 部署成功！")
        print("=" * 60)
    elif not services_stopped:
        # deploy_ok=False 但服务在跑（验证发现问题但服务正常）
        print("\n" + "=" * 60)
        print("  ⚠️ 部署完成，但验证发现问题，请手动检查")
        print("  查看日志：journalctl -u mory-assistant -n 100 --no-pager")
        print("=" * 60)


if __name__ == "__main__":
    main()
