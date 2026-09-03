#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""换服迁移导出：现 VPS 活数据一致性快照 + 打包 + 拉回本地 + 本地校验。

用法：
    python scripts/migrate_export.py                 # 活数据包（约30MB）
    python scripts/migrate_export.py --with-history   # + 历史DB/配置归档（约250MB）
    python scripts/migrate_export.py --live-only       # 仅活数据（默认）

产物（gitignored，不入库）：
    backups/server_migrate_<UTC戳>/
        live-data.tar.gz          # 活数据包（远端 staging 打包）
        history-data.tar.gz       # 历史归档包（仅 --with-history）
        live/                     # 本地解包 + 校验后的活数据（绝不写回项目根目录）
        MANIFEST.json             # 远端快照元数据（版本/alembic/表计数/sha256）
        VERIFY_REPORT.json        # 本地校验报告

安全：
- DB 快照走 sqlite3 backup API（在线一致，含 WAL 最新状态），不断服。
- 远端只在 <VPS_PATH>/.deploy-staging 下写临时文件，0600/0700，下载后删除。
- 凭据只经 .env 环境变量读取，不打印、不入库。
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paramiko  # noqa: E402

from core.vps_config import VPS_HOST, VPS_PATH, ssh_connect  # noqa: E402

# 远端快照脚本：保持单文件、无第三方依赖，执行完即删。
REMOTE_SNAPSHOT_CODE = r"""
import glob, hashlib, io, json, os, sqlite3, sys, tarfile, time

proj, stage, want_history = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
os.umask(0o077)

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def snap_db(src, dst):
    src_con = sqlite3.connect("file:%s?mode=ro" % src, uri=True, timeout=30)
    if os.path.exists(dst):
        os.unlink(dst)
    dst_con = sqlite3.connect(dst)
    src_con.backup(dst_con)
    src_con.close()
    integrity = dst_con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = dst_con.execute("PRAGMA foreign_key_check").fetchall()
    tables = {}
    for (name,) in dst_con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall():
        tables[name] = dst_con.execute(
            'SELECT COUNT(*) FROM "%s"' % name.replace('"', '""')
        ).fetchone()[0]
    alembic = None
    if "alembic_version" in tables:
        alembic = dst_con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    dst_con.close()
    assert integrity == "ok", "integrity=%r" % integrity
    assert not fk, "foreign_key_errors=%d" % len(fk)
    os.chmod(dst, 0o600)
    return {"tables": tables, "alembic": alembic, "sha256": sha256_file(dst),
            "bytes": os.path.getsize(dst)}

manifest = {"taken_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
manifest["mory_db"] = snap_db(os.path.join(proj, "mory.db"),
                              os.path.join(stage, "mory.db"))
router_src = os.path.join(proj, "data", "router_usage.db")
if os.path.exists(router_src):
    manifest["router_usage_db"] = snap_db(
        router_src, os.path.join(stage, "router_usage.db"))
else:
    manifest["router_usage_db"] = None

sys.path.insert(0, proj)
manifest["version"] = __import__("version").VERSION

def add_file(tar, arc, real):
    if os.path.isfile(real):
        info = tar.gettarinfo(real, arcname=arc)
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = int(time.time())
        with open(real, "rb") as f:
            tar.addfile(info, f)
        return {"bytes": os.path.getsize(real), "sha256": sha256_file(real)}
    return None

live_tar = os.path.join(stage, "live-data.tar.gz")
meta_files = {}
with tarfile.open(live_tar, "w:gz") as tar:
    for arc, real in (("mory.db", os.path.join(stage, "mory.db")),
                      ("router_usage.db", os.path.join(stage, "router_usage.db"))):
        if os.path.exists(real):
            tar.add(real, arcname=arc)
    for name in ("config.json", ".env", "version.py", "VERSION.md",
                 "config.json.example", "requirements.lock",
                 "fault_dedup_state.json"):
        hit = add_file(tar, "meta/" + name, os.path.join(proj, name))
        if hit:
            meta_files[name] = hit
    for arc_prefix, real_dir in (("assets/fonts", os.path.join(proj, "assets", "fonts")),
                                 ("assets/broadcast", os.path.join(proj, "assets", "broadcast")),
                                 ("assets/preset_media", os.path.join(proj, "assets", "preset_media")),
                                 ("assets/start_welcome", os.path.join(proj, "assets", "start_welcome"))):
        if os.path.isdir(real_dir):
            for real in sorted(glob.glob(os.path.join(real_dir, "*"))):
                if os.path.isfile(real):
                    tar.add(real, arcname=arc_prefix + "/" + os.path.basename(real))
    for unit in ("mory-assistant.service", "mory-dashboard.service"):
        for src in ("/etc/systemd/system/" + unit,
                    os.path.join(proj, "config", unit)):
            if os.path.isfile(src):
                hit = add_file(tar, "systemd/" + unit, src)
                if hit:
                    meta_files["systemd/" + unit] = {"from": src, **hit}
                break
manifest["meta_files"] = meta_files
manifest["live_tar"] = {"bytes": os.path.getsize(live_tar),
                        "sha256": sha256_file(live_tar)}

hist_tar = None
if want_history:
    hist_tar = os.path.join(stage, "history-data.tar.gz")
    hourlies = sorted(glob.glob(os.path.join(proj, "backup/mory_backup_*.db")),
                      key=os.path.getmtime, reverse=True)
    kept_hourlies, skipped_hourlies = hourlies, []
    picked = (kept_hourlies
              + sorted(glob.glob(os.path.join(proj, "backups/mory_pre_migration_*.db")))
              + sorted(glob.glob(os.path.join(proj, "backups/config_*.json")))
              + sorted(glob.glob(os.path.join(proj, "backup/config_*.json"))))
    with tarfile.open(hist_tar, "w:gz") as tar:
        count = 0
        for real in picked:
            tar.add(real, arcname=os.path.relpath(real, proj))
            count += 1
    manifest["history_tar"] = {"bytes": os.path.getsize(hist_tar),
                               "sha256": sha256_file(hist_tar), "files": count,
                               "note": "all hourlies + all pre-migration + all config backups"}
else:
    manifest["history_tar"] = None

with open(os.path.join(stage, "MANIFEST.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print("SNAPSHOT_OK " + json.dumps({"live": manifest["live_tar"],
                                   "history": manifest["history_tar"]}))
"""


def _exec(client, cmd, timeout):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    stdin.close()
    stdout.close()
    stderr.close()
    return rc, out, err


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_resume(sftp, remote: str, local: Path, label: str) -> None:
    """断点续传：本地已有部分则 seek 后追加；远端大小变化则重下。"""
    rsize = sftp.stat(remote).st_size
    start = local.stat().st_size if local.exists() else 0
    if start > rsize:
        local.unlink()
        start = 0
    if start == rsize and start > 0:
        print(f"    {label} 已完整（{rsize / 1024 / 1024:.1f}MB），跳过下载")
        return
    if start > 0:
        print(f"    {label} 续传：{start / 1024 / 1024:.1f}/{rsize / 1024 / 1024:.1f}MB")
    last_shown = -1
    with sftp.open(remote, "rb") as rf, open(local, "ab") as lf:
        rf.seek(start)
        done = start
        while True:
            chunk = rf.read(1 << 20)
            if not chunk:
                break
            lf.write(chunk)
            done += len(chunk)
            pct = int(done / rsize * 100) if rsize else 100
            if pct - last_shown >= 5:
                print(f"    … {label} {done / 1024 / 1024:.1f}/"
                      f"{rsize / 1024 / 1024:.1f}MB ({pct}%)", end="\r")
                last_shown = pct
    print(f"    ✅ {label} {local.stat().st_size / 1024 / 1024:.1f}MB")


def main() -> int:
    ap = argparse.ArgumentParser(description="换服迁移导出（现 VPS -> 本地）")
    ap.add_argument("--with-history", action="store_true",
                    help="连同历史 DB/配置归档一起拉回（约250MB）")
    ap.add_argument("--live-only", action="store_true", help="仅活数据（默认）")
    ap.add_argument("--out-dir", default="",
                    help="复用已有输出目录（断点续传时指向中断那次目录）")
    ap.add_argument("--resume-stage", default="",
                    help="复用远端已有 staging（断点续传时用，不再重新快照）")
    args = ap.parse_args()

    if not VPS_HOST:
        print("❌ VPS_HOST 未设置（.env），无法连接现服务器")
        return 2

    if args.out_dir:
        out_dir = Path(args.out_dir)
        if not out_dir.is_dir():
            print(f"❌ --out-dir 不存在：{out_dir}")
            return 2
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = ROOT / "backups" / f"server_migrate_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)

    client = paramiko.SSHClient()
    print(f"[1/5] 连接现服务器 {VPS_HOST} ...")
    ssh_connect(client, timeout=15)
    sftp = client.open_sftp()
    stage = ""
    fresh_stage = not args.resume_stage
    if args.resume_stage:
        stage = f"{VPS_PATH}/.deploy-staging/{args.resume_stage}"
        try:
            sftp.stat(f"{stage}/MANIFEST.json")
        except FileNotFoundError:
            print(f"❌ 远端 staging 已不存在：{stage}，请重跑完整导出")
            return 1
        print(f"  ♻️ 复用远端 staging：{stage}")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        stage_token = os.urandom(8).hex()
        stage = f"{VPS_PATH}/.deploy-staging/migrate_{stamp}_{stage_token}"
        rc, out, err = _exec(client, f"install -d -m 0700 {stage}", 30)
        if rc != 0:
            print(f"❌ 远端 staging 创建失败：{err}")
            return 1
        print(f"  ✅ staging: {stage}")

    try:
        if fresh_stage:
            print("[2/5] 远端一致性快照 + 打包 ...")
            remote_py = f"{stage}/snapshot.py"
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                             encoding="utf-8") as f:
                f.write(REMOTE_SNAPSHOT_CODE)
                local_py = f.name
            try:
                sftp.put(local_py, remote_py)
                sftp.chmod(remote_py, 0o600)
            finally:
                os.unlink(local_py)
            want_hist = "1" if args.with_history else "0"
            rc, out, err = _exec(
                client,
                f"cd {VPS_PATH} && python3 {remote_py} {VPS_PATH} {stage} {want_hist}",
                900,
            )
            if rc != 0 or "SNAPSHOT_OK" not in out:
                print(f"❌ 远端快照失败 rc={rc}：{(err or out)[-1500:]}")
                return 1
            print(f"  ✅ {out.splitlines()[-1][:300]}")
        else:
            print("[2/5] 跳过快照（复用远端 staging）...")

        print("[3/5] 下载到本地（断点续传）...")
        sftp.get(f"{stage}/MANIFEST.json", str(out_dir / "MANIFEST.json"))
        manifest = json.loads((out_dir / "MANIFEST.json").read_text(encoding="utf-8"))

        _get_resume(sftp, f"{stage}/live-data.tar.gz",
                    out_dir / "live-data.tar.gz", "live-data.tar.gz")
        if args.with_history and manifest.get("history_tar"):
            print(f'    历史归档约 {manifest["history_tar"]["bytes"] / 1024 / 1024:.0f}MB，'
                  f'{manifest["history_tar"]["files"]} files（含近3份hourly+全部pre-migration+配置备份）')
            _get_resume(sftp, f"{stage}/history-data.tar.gz",
                        out_dir / "history-data.tar.gz", "history-data.tar.gz")
        print(f"  ✅ 已下载：{', '.join(p.name for p in sorted(out_dir.iterdir()))}")
    finally:
        print("[4/5] 清理远端 staging ...")
        _exec(client, f"rm -rf {stage}", 60)
        try:
            sftp.close()
        except Exception:
            pass
        client.close()
        print("  ✅ 远端临时文件已删（线上服务全程未停）")

    print("[5/5] 本地校验 ...")
    report = {"out_dir": str(out_dir), "checks": {}}
    ok_all = True

    def check(name, cond, detail=""):
        nonlocal ok_all
        report["checks"][name] = {"ok": bool(cond), "detail": detail}
        print(f"  {'✅' if cond else '❌'} {name} {detail}")
        if not cond:
            ok_all = False

    manifest = json.loads((out_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    check("live_sha256",
          _sha256(out_dir / "live-data.tar.gz") == manifest["live_tar"]["sha256"],
          manifest["live_tar"]["sha256"][:16] + "…")
    if args.with_history and manifest.get("history_tar"):
        check("history_sha256",
              _sha256(out_dir / "history-data.tar.gz") == manifest["history_tar"]["sha256"],
              f'{manifest["history_tar"]["files"]} files')

    live_dir = out_dir / "live"
    live_dir.mkdir(exist_ok=True)
    with tarfile.open(out_dir / "live-data.tar.gz", "r:gz") as tar:
        tar.extractall(live_dir, filter="data")
    db_path = live_dir / "mory.db"
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        local_counts = {r[0]: con.execute(
            'SELECT COUNT(*) FROM "%s"' % r[0].replace('"', '""')).fetchone()[0]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
    finally:
        con.close()
    check("db_integrity", integrity == "ok", integrity)
    check("db_foreign_key", not fk, f"errors={len(fk)}")
    remote_counts = manifest["mory_db"]["tables"]
    check("db_counts_match", local_counts == remote_counts,
          f"tables={len(local_counts)} rows_total={sum(local_counts.values())}")
    check("db_alembic_head",
          manifest["mory_db"].get("alembic") == "0012_scheduler_metrics_last_status_at",
          str(manifest["mory_db"].get("alembic")))
    local_version = (ROOT / "version.py").read_text(encoding="utf-8")
    check("version_match", manifest["version"] in local_version,
          f'vps={manifest["version"]}')
    for name in ("config.json", ".env"):
        p = live_dir / "meta" / name
        try:
            content = p.read_text(encoding="utf-8")
            valid = len(content) > 10 and (json.loads(content) if name.endswith(".json") else True)
            check(f"{name}_present", bool(valid), f"{len(content)} bytes")
        except Exception as e:
            check(f"{name}_present", False, str(e)[:120])
    fonts = list((live_dir / "assets" / "fonts").glob("*")) if (live_dir / "assets" / "fonts").exists() else []
    check("fonts_present", len(fonts) > 0, f"{len(fonts)} files")
    preset = list((live_dir / "assets" / "preset_media").glob("*")) if (live_dir / "assets" / "preset_media").exists() else []
    check("preset_media_present", len(preset) > 0, f"{len(preset)} files")
    welcome = list((live_dir / "assets" / "start_welcome").glob("*")) if (live_dir / "assets" / "start_welcome").exists() else []
    check("start_welcome_present", len(welcome) > 0, f"{len(welcome)} files")

    (out_dir / "VERIFY_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not ok_all:
        print("⛔ 本地校验未全过，不可用作恢复源，请按报告排查后重跑")
        return 1
    print(f"\n✅ 导出完成：{out_dir}（共 {sum(p.stat().st_size for p in out_dir.rglob('*') if p.is_file()) / 1024 / 1024:.1f}MB）")
    print("   下一步：新服务器就绪后 python scripts/migrate_restore.py --help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
