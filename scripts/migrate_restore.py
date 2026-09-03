#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""换服迁移恢复：新 VPS 一键重建（代码 git clone + 导出包数据还原 + 服务拉起 + 验证）。

前置：先跑 scripts/migrate_export.py 拿到 backups/server_migrate_<戳>/（含 VERIFY_REPORT.json 全绿）。

用法：
    # 1. 预检新服务器（只读，不写任何东西）
    set NEW_VPS_HOST=<新IP> & set NEW_VPS_SSH_PASS=<密码或密钥>
    python scripts/migrate_restore.py --export-dir backups/server_migrate_<戳> --check-only

    # 2. 干跑（打印计划，不连接）
    python scripts/migrate_restore.py --export-dir backups/server_migrate_<戳> --dry-run

    # 3. 真正恢复（新服务器必须是全新系统/空目录；已存在 mory.db 会直接拒绝）
    python scripts/migrate_restore.py --export-dir backups/server_migrate_<戳>

注意：
- 新服务器恢复是“写空目标”，与 deploy_vps.py“禁止上传 mory.db/覆盖 config.json”
  不冲突：后者保护的是现生产服，本脚本拒绝向已存在 mory.db 的目标写入。
- 认证：环境变量 NEW_VPS_SSH_PASS 或 NEW_VPS_SSH_KEY（私钥路径），或命令行参数。
- 系统要求：Ubuntu 24.04 + python3.12 + git + sudo 免密（与现生产服一致）。
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_REPO = "https://github.com/Alan-zzh/mory-telegram-assistant.git"


def _parse_args():
    ap = argparse.ArgumentParser(description="换服迁移恢复（新 VPS 一键重建）")
    ap.add_argument("--export-dir", required=True, help="migrate_export.py 产物目录")
    ap.add_argument("--new-host", default=os.environ.get("NEW_VPS_HOST", ""))
    ap.add_argument("--new-port", type=int,
                    default=int(os.environ.get("NEW_VPS_PORT", "22") or 22))
    ap.add_argument("--new-user", default=os.environ.get("NEW_VPS_USER", "ubuntu"))
    ap.add_argument("--new-path", default=os.environ.get("NEW_VPS_PATH",
                                                         "/home/ubuntu/mory_assistant"))
    ap.add_argument("--ssh-pass", default=os.environ.get("NEW_VPS_SSH_PASS", ""))
    ap.add_argument("--ssh-key", default=os.environ.get("NEW_VPS_SSH_KEY", ""))
    ap.add_argument("--repo", default=DEFAULT_REPO, help="代码仓库地址")
    ap.add_argument("--commit", default="", help="检出 commit（默认=本地当前 HEAD）")
    ap.add_argument("--check-only", action="store_true", help="只预检，不写")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不连接")
    return ap.parse_args()


def _exec(client, cmd, timeout=120):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    stdin.close()
    stdout.close()
    stderr.close()
    return rc, out, err


def _connect(args):
    sys.path.insert(0, str(ROOT))
    import paramiko
    from core.vps_config import (get_ssh_policy,
                                 secure_paramiko_connect_kwargs)
    key_files = [args.ssh_key] if args.ssh_key and Path(args.ssh_key).is_file() else []
    if not args.ssh_pass and not key_files:
        for cand in (Path.home() / ".ssh" / "id_ed25519_deploy",
                     Path.home() / ".ssh" / "id_ed25519",
                     Path.home() / ".ssh" / "id_rsa"):
            if cand.is_file():
                key_files.append(str(cand))
    if not args.new_host:
        raise SystemExit("❌ 缺少新服务器地址：--new-host 或 NEW_VPS_HOST")
    if not args.ssh_pass and not key_files:
        raise SystemExit("❌ 缺少新服务器认证：NEW_VPS_SSH_PASS 或 NEW_VPS_SSH_KEY")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(get_ssh_policy())  # type: ignore[arg-type]
    client.connect(args.new_host, port=args.new_port, username=args.new_user,
                   password=args.ssh_pass or None,
                   key_filename=key_files or None,  # type: ignore[arg-type]
                   look_for_keys=False, allow_agent=False, timeout=20,
                   **secure_paramiko_connect_kwargs())
    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(10)
    return client


PREFLIGHT = [
    ("os", "lsb_release -ds && python3 --version && git --version"),
    ("sudo", "sudo -n true && echo SUDO_NOPASS_OK"),
    ("disk", "df -h / | tail -1"),
    ("fresh", "test ! -e {path}/mory.db && echo FRESH_OK || echo HAS_DB_REFUSE"),
    ("port", "(ss -tlnp 2>/dev/null | grep -E ':6616' || echo PORT_6616_FREE)"),
]


def _preflight(client, args) -> bool:
    print("[预检] 新服务器只读检查 ...")
    ok = True
    for name, cmd in PREFLIGHT:
        rc, out, err = _exec(client, cmd.format(path=shlex.quote(args.new_path)))
        print(f"  --- {name}: rc={rc}\n  {out[:400]}")
        if name == "fresh" and "FRESH_OK" not in out:
            print("  ⛔ 目标已存在 mory.db：拒绝写入，防止覆盖已有生产数据。换空目录/新系统再跑。")
            ok = False
        elif name == "sudo" and "SUDO_NOPASS_OK" not in out:
            print("  ⛔ 需要 sudo 免密（装 systemd unit 用）。")
            ok = False
        elif rc != 0 and name in ("os", "disk"):
            ok = False
    return ok


def _restore(client, sftp, args, manifest, commit) -> bool:
    p = shlex.quote(args.new_path)
    print("[1/7] git clone 代码并锁定版本 ...")
    rc, out, err = _exec(
        client,
        f"git clone {shlex.quote(args.repo)} {p} && cd {p} && "
        f"git checkout {shlex.quote(commit)} && git rev-parse --short HEAD",
        300)
    if rc != 0:
        print(f"❌ clone/checkout 失败：{(err or out)[-800:]}")
        return False
    print(f"  ✅ {out.splitlines()[-1]}")

    print("[2/7] 还原数据文件（0600） ...")
    live = Path(args.export_dir) / "live"
    payloads = [
        (live / "mory.db", f"{args.new_path}/mory.db"),
        (live / "meta" / "config.json", f"{args.new_path}/config.json"),
        (live / "meta" / ".env", f"{args.new_path}/.env"),
        (live / "meta" / "fault_dedup_state.json",
         f"{args.new_path}/fault_dedup_state.json"),
    ]
    if (live / "router_usage.db").exists():
        payloads.append((live / "router_usage.db",
                         f"{args.new_path}/data/router_usage.db"))
    for local, remote in payloads:
        if not local.is_file():
            print(f"  ⚠️ 导出包缺 {local.name}，跳过")
            continue
        try:
            sftp.put(str(local), remote)
            sftp.chmod(remote, 0o600)
            print(f"  ✅ {local.name} → {remote} (0600)")
        except Exception as e:
            print(f"❌ 上传 {local.name} 失败：{e}")
            return False
    for sub in ("assets/fonts", "assets/broadcast", "assets/preset_media", "assets/start_welcome"):
        src_dir = live / sub
        if not src_dir.is_dir():
            continue
        _exec(client, f"install -d -m 0755 {p}/{shlex.quote(sub)}", 30)
        for f in sorted(src_dir.iterdir()):
            if f.is_file():
                sftp.put(str(f), f"{args.new_path}/{sub}/{f.name}")
        print(f"  ✅ {sub}/（{len(list(src_dir.iterdir()))} files）")

    print("[3/7] 安装依赖（requirements.lock） ...")
    rc, out, err = _exec(
        client,
        f"cd {p} && (python3 -m pip install --user -r requirements.lock "
        f"--break-system-packages || python3 -m pip install --user "
        f"-r requirements.lock) 2>&1 | tail -3",
        900)
    if rc != 0:
        print(f"❌ 依赖安装失败：{(err or out)[-800:]}")
        return False
    print("  ✅ 依赖已按 lock 安装")

    print("[4/7] 数据库迁移到 head ...")
    mig = ("import os,subprocess,sys;env=os.environ.copy();"
           "env.pop('DATABASE_URL',None);"
           f"env['MORY_DB_PATH']={args.new_path + '/mory.db'!r};"
           "subprocess.run([sys.executable,'-m','alembic','upgrade','head'],"
           "check=True,env=env)")
    rc, out, err = _exec(client, f"cd {p} && python3 -c {shlex.quote(mig)}", 300)
    if rc != 0:
        print(f"❌ 迁移失败：{(err or out)[-800:]}")
        return False
    print("  ✅ alembic head")

    print("[5/7] 安装 systemd units + enable ...")
    for svc in ("mory-assistant.service", "mory-dashboard.service"):
        rc, out, err = _exec(
            client,
            f"cd {p} && sudo install -o root -g root -m 0644 config/{svc} "
            f"/etc/systemd/system/{svc} && echo {svc}_OK",
            60)
        if rc != 0 or f"{svc}_OK" not in out:
            print(f"❌ {svc} 安装失败：{(err or out)[-400:]}")
            return False
    rc, _, err = _exec(client, "sudo systemctl daemon-reload && "
                               "sudo systemctl enable mory-assistant mory-dashboard",
                       60)
    if rc != 0:
        print(f"❌ enable 失败：{err[-400:]}")
        return False
    rc, out, _ = _exec(
        client,
        f"chmod 0600 {p}/.env {p}/config.json {p}/mory.db && "
        f"sudo install -d -o root -g root -m 0755 /usr/local/lib/mory-assistant && "
        f"sudo install -o root -g root -m 0755 {p}/scripts/vps_watchdog.py "
        f"/usr/local/lib/mory-assistant/vps_watchdog.py && echo HARDEN_OK",
        60)
    if rc != 0 or "HARDEN_OK" not in out:
        print(f"❌ 权限加固失败：{(out or '')[-400:]}")
        return False
    print("  ✅ units root:root 0644，凭据 0600，watchdog 就位")

    print("[6/7] 重启双服务并轮询 ...")
    rc, _, err = _exec(client, "sudo systemctl restart mory-assistant mory-dashboard",
                       60)
    if rc != 0:
        print(f"❌ restart 失败：{err[-400:]}")
        return False
    ok = False
    for i in range(20):
        time.sleep(3)
        _, code, _ = _exec(client, "curl -s -o /dev/null -w '%{http_code}' "
                                   "http://localhost:6616/api/health", 15)
        _, active, _ = _exec(client, "systemctl is-active mory-assistant "
                                      "mory-dashboard", 15)
        if code == "200" and active.count("active") >= 2:
            print(f"  ✅ health=200 且双服务 active（第 {i + 1} 次轮询）")
            ok = True
            break
    if not ok:
        print("  ⛔ health 未达 200 或服务未 active，停止并报失败")
        return False

    print("[7/7] 恢复后读回验证 ...")
    rc, ver, _ = _exec(client, f"cd {p} && python3 -c "
                               "'from version import VERSION; print(VERSION)'", 30)
    rc2, integ, _ = _exec(client, f"cd {p} && sqlite3 mory.db "
                                  "'PRAGMA integrity_check;'", 60)
    print(f"  version={ver.strip()}（期望 {manifest['version']}）")
    print(f"  integrity={integ.strip()}")
    return ver.strip() == manifest["version"] and integ.strip() == "ok"


def main() -> int:
    args = _parse_args()
    export_dir = Path(args.export_dir)
    manifest_p = export_dir / "MANIFEST.json"
    verify_p = export_dir / "VERIFY_REPORT.json"
    if not manifest_p.is_file():
        print(f"❌ 导出目录无效（缺 MANIFEST.json）：{export_dir}")
        return 2
    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    if verify_p.is_file():
        report = json.loads(verify_p.read_text(encoding="utf-8"))
        bad = [k for k, v in report.get("checks", {}).items() if not v.get("ok")]
        if bad:
            print(f"⛔ 导出包校验有失败项 {bad}，拒绝用作恢复源")
            return 1
    else:
        print("⚠️ 导出包无 VERIFY_REPORT.json（仅活数据包也应有），继续需自行承担")
    commit = args.commit or subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
        cwd=str(ROOT)).stdout.strip()
    print(f"恢复源：version={manifest['version']} commit={commit[:12]} "
          f"alembic={manifest['mory_db'].get('alembic')}")

    if args.dry_run:
        print("[dry-run] 计划：预检→clone+checkout "
              f"{commit[:12]}→还原mory.db/config.json/.env/router/fonts"
              "→pip lock→alembic head→units 0644→enable→加固→restart→health+版本+完整性读回")
        print(f"[dry-run] 目标：{args.new_user}@{args.new_host or '<未填>'}:"
              f"{args.new_port}{args.new_path}")
        return 0

    client = _connect(args)
    try:
        sftp = client.open_sftp()
        if not _preflight(client, args):
            return 1
        if args.check_only:
            print("✅ 预检通过（未做任何写入）")
            return 0
        ok = _restore(client, sftp, args, manifest, commit)
        print("✅ 一键恢复完成" if ok else "⛔ 恢复失败：新服务未通过验证，老服务器未动，可重跑")
        return 0 if ok else 1
    finally:
        try:
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
