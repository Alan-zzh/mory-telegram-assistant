import logging
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  deploy_vps.py  ·  一键部署脚本（systemd管理）                           ║
║                                                                            ║
║  功能：上传代码（全程不停服，文件就位后单步切换）→ 安全合并配置 → 重启服务 → 验证部署     ║
║  使用：python deploy_vps.py                                               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import io
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path, PurePosixPath

def _configure_stdio():
    """仅在命令行执行部署时切换 UTF-8，避免被测试导入时破坏捕获流。"""
    if os.name != "nt":
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            setattr(
                sys,
                name,
                io.TextIOWrapper(
                    buffer,
                    encoding="utf-8",
                    errors="replace",
                    write_through=True,
                ),
            )

import paramiko

# 项目根目录
ROOT = Path(__file__).resolve().parent


def _locked_dashboard_versions() -> dict:
    """从唯一依赖锁读取 Dashboard 运行时精确版本。"""
    lock_text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    versions = {}
    for package in ("gunicorn", "gevent"):
        match = re.search(rf"(?m)^{package}==([^\s\\]+)", lock_text)
        if not match:
            raise RuntimeError(f"requirements.lock 缺少 {package} 精确版本")
        versions[package] = match.group(1)
    return versions


def _dashboard_runtime_probe_command() -> str:
    """生成生产运行解释器的依赖锁断言命令。"""
    expected = _locked_dashboard_versions()
    code = (
        "from importlib.metadata import version; "
        f"expected={expected!r}; "
        "actual={name:version(name) for name in expected}; "
        "assert actual == expected, f'LOCK_MISMATCH expected={expected} actual={actual}'; "
        "print('DASHBOARD_RUNTIME_LOCK_OK', actual)"
    )
    return f"cd {shlex.quote(VPS_PATH)} && python3 -c {shlex.quote(code)}"

# 导入部署工具
sys.path.insert(0, str(ROOT))
from core.deploy_utils import safe_upload_config, upload_files, verify_deployment, sync_runtime_fields_from_vps, sync_env_api_key, ensure_remote_dir
from core.vps_config import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASS, VPS_KEY_FILES, VPS_PATH, ssh_connect
from scripts.check_deploy_ready import check_git_clean, check_head_contains_main


def _deploy_source_gate() -> tuple[bool, str]:
    """阻断脏工作树或不含当前主线的全目录部署。"""
    for check in (check_git_clean, check_head_contains_main):
        ok, detail = check()
        if not ok:
            return False, detail
    return True, "工作树干净且部署源包含当前 main"


def _open_deploy_connection():
    """建立带 keepalive 的部署连接，返回 (SSHClient, SFTPClient)。"""
    client = paramiko.SSHClient()
    ssh_connect(client, timeout=15)
    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(10)
    sftp = client.open_sftp()
    channel = sftp.get_channel()
    if channel is not None:
        channel.settimeout(60)
    return client, sftp


def _upload_files_resilient(client, sftp, files, *, chunk_size=40, max_attempts=3):
    """分批上传；连接断开时重连并重传当前批次，避免留下半部署假成功。"""
    uploaded = []
    total = len(files)
    for offset in range(0, total, chunk_size):
        chunk = files[offset:offset + chunk_size]
        for attempt in range(1, max_attempts + 1):
            try:
                batch = upload_files(
                    sftp,
                    str(ROOT),
                    VPS_PATH,
                    chunk,
                    progress_cb=lambda done, _batch_total: print(
                        f"  ⏳ 上传进度: {min(offset + done, total)}/{total}", end="\r"
                    ),
                )
                uploaded.extend(batch)
                break
            except Exception as e:
                try:
                    sftp.close()
                except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
                    logging.getLogger('deploy_vps').debug(f'非致命忽略: {_e}')
                try:
                    client.close()
                except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
                    logging.getLogger('deploy_vps').debug(f'非致命忽略: {_e}')
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"上传批次 {offset + 1}-{offset + len(chunk)} 连续失败 {max_attempts} 次"
                    ) from e
                print(
                    f"\n  ⚠️ 上传连接中断，重连后重传当前批次 "
                    f"({attempt}/{max_attempts}): {type(e).__name__}"
                )
                time.sleep(attempt * 2)
                client, sftp = _open_deploy_connection()
    return client, sftp, uploaded


def _deployment_exit_code(success: bool) -> int:
    """部署未完成或验证失败必须给自动化返回非零。"""
    return 0 if success else 1


def _service_staging_path(service_name: str) -> str:
    """返回项目私有目录下的 unit 暂存路径，避免 world-writable /tmp TOCTOU。"""
    safe_name = Path(service_name).name
    if safe_name != service_name or not safe_name.endswith(".service"):
        raise ValueError(f"非法 service 文件名: {service_name!r}")
    return f"{VPS_PATH}/.deploy-staging/{safe_name}"


def _service_install_command(service_name: str) -> str:
    """生成固定所有者/权限的 systemd unit 安装命令。"""
    safe_name = Path(service_name).name
    if safe_name != service_name or not safe_name.endswith(".service"):
        raise ValueError(f"非法 service 文件名: {service_name!r}")
    staging_path = _service_staging_path(safe_name)
    return (
        f"sudo install -o root -g root -m 0644 {staging_path} "
        f"/etc/systemd/system/{safe_name} && rm -f {staging_path}"
    )


def _runtime_permission_hardening_command() -> str:
    """收紧凭据权限，并让 root cron 只执行 root 拥有的 watchdog 副本。"""
    secure_watchdog = "/usr/local/lib/mory-assistant/vps_watchdog.py"
    source_watchdog = f"{VPS_PATH}/scripts/vps_watchdog.py"
    canonical_cron = (
        f"*/2 * * * * cd {VPS_PATH} && /usr/bin/python3 -X utf8 {secure_watchdog}"
    )
    return " && ".join([
        "set -eu",
        f"chmod 0600 {VPS_PATH}/.env {VPS_PATH}/config.json",
        f"test ! -f {VPS_PATH}/mory.db || chmod 0600 {VPS_PATH}/mory.db",
        "sudo install -d -o root -g root -m 0755 /usr/local/lib/mory-assistant",
        f"sudo install -o root -g root -m 0755 {source_watchdog} {secure_watchdog}",
        "cron_text=\"$(sudo crontab -l 2>/dev/null || true)\"",
        # 兼容旧绝对/相对路径：先清掉所有旧 watchdog 行，再只写一个规范条目。
        f"install -d -m 0700 {VPS_PATH}/.deploy-staging",
        f"cron_stage={VPS_PATH}/.deploy-staging/root-cron.$$$$",
        "umask 077",
        "printf '%s\\n' \"$cron_text\" | sed '/vps_watchdog\\.py/d' > \"$cron_stage\"",
        f"printf '%s\\n' '{canonical_cron}' >> \"$cron_stage\"",
        "sudo crontab \"$cron_stage\"",
        "rm -f \"$cron_stage\"",
        f"test \"$(sudo crontab -l | grep -Fxc '{canonical_cron}')\" = '1'",
        f"sudo test \"$(stat -c '%U:%G %a' {secure_watchdog})\" = 'root:root 755'",
    ])


def _code_backup_command() -> str:
    """生成不含凭据、配置和运行态数据的受限代码快照命令。"""
    return (
        f"cd {VPS_PATH} && umask 077 && mkdir -p backups && chmod 0700 backups && "
        "tar --exclude='./mory.db' --exclude='./.venv' --exclude='./.env' --exclude='./.env.*' "
        "--exclude='./config.json' --exclude='./logs' --exclude='./runtime' "
        "--exclude='./backups' --exclude='./backup' --exclude='*__pycache__*' "
        "--exclude='*.pyc' -czf backups/code_deploy_$(date +%s).tar.gz . 2>/dev/null && "
        "chmod 0600 backups/code_deploy_*.tar.gz && "
        "ls -dt backups/code_deploy_*.tar.gz 2>/dev/null | tail -n +3 | xargs -r rm -f && "
        "echo BACKUP_OK"
    )


def _enable_services_command() -> str:
    """同时启用两个 systemd 服务，避免主机重启后仅 Dashboard 自动恢复。"""
    return "sudo systemctl daemon-reload && sudo systemctl enable mory-assistant mory-dashboard"


def _database_migration_command() -> str:
    """把本仓库唯一生产数据库精确绑定后升级到 Alembic head。"""
    project_dir = shlex.quote(VPS_PATH)
    database_path = str(PurePosixPath(VPS_PATH) / "mory.db")
    code = "\n".join(
        [
            "import os, subprocess, sys",
            "env = os.environ.copy()",
            "env.pop('DATABASE_URL', None)",
            f"env['MORY_DB_PATH'] = {database_path!r}",
            "subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], check=True, env=env)",
            "subprocess.run([sys.executable, '-m', 'alembic', 'current'], check=True, env=env)",
            "print('MIGRATION_OK')",
        ]
    )
    return f"cd {project_dir} && python3 -c {shlex.quote(code)}"


def _database_backup_command() -> str:
    """迁移前创建经过完整性校验的在线 SQLite 快照。"""
    project_dir = shlex.quote(VPS_PATH)
    code = "\n".join(
        [
            "import glob, hashlib, os, secrets, sqlite3, time",
            "stamp = int(time.time())",
            "token = secrets.token_hex(8)",
            "stage = f'backups/.mory_pre_migration_{stamp}_{token}.tmp'",
            "target = f'backups/mory_pre_migration_{stamp}_{token}.db'",
            "source = sqlite3.connect('file:mory.db?mode=ro', uri=True)",
            "snapshot = sqlite3.connect(stage)",
            "source.backup(snapshot)",
            "integrity = snapshot.execute('PRAGMA integrity_check').fetchone()[0]",
            "foreign_keys = snapshot.execute('PRAGMA foreign_key_check').fetchall()",
            "snapshot.close()",
            "source.close()",
            "assert integrity == 'ok', integrity",
            "assert not foreign_keys, f'foreign_key_errors={len(foreign_keys)}'",
            "os.chmod(stage, 0o600)",
            "os.replace(stage, target)",
            "handle = open(target, 'rb')",
            "digest = hashlib.file_digest(handle, 'sha256').hexdigest()",
            "handle.close()",
            "old = sorted(glob.glob('backups/mory_pre_migration_*.db'), key=os.path.getmtime, reverse=True)[3:]",
            "[os.unlink(path) for path in old]",
            "print('DB_BACKUP_OK', os.path.basename(target), digest)",
        ]
    )
    return (
        f"cd {project_dir} && umask 077 && mkdir -p backups && chmod 0700 backups && "
        f"test -f mory.db && python3 -c {shlex.quote(code)}"
    )

# 绝不上传的文件名（含凭据/运行态/旧备份）。_collect_upload_files 只扫描 .py 文件，
# 故 .bat/.sh 等非 Python 脚本根本不会被收集，无需在此列举。
# v5.16.5 曾在此防御已删除的 deploy.bat/start.sh/start_dashboard.bat/docker_deploy.sh，
# 但这些条目属无效死代码（本地已删且扫描器不会命中），已于本次清理移除。
EXCLUDE_NAMES = {
    # 运行态配置（含 Token/密钥，线上以 safe_upload_config 安全合并，不直接覆盖）
    "config.json",
    # 凭据文件（含 VPS 密码/API Key，绝不上传）
    ".env", ".env.bak",
    # 数据库与缓存（运行态数据，上传会覆盖线上）
    "mory.db", "__pycache__", ".pyc",
    # 部署脚本自身（避免递归上传）
    "deploy_vps.py",
    # 同步冲突临时文件（Syncthing 等产生的 .sync-conflict- 副本）
    ".sync-conflict-",
    # SSH 已知主机（含 VPS 指纹，本地凭据）
    "_ssh_known_hosts",
    # 运行日志（运行态产物，不应上传）
    "dashboard.log", "fault_alerts.log",
    # 过程流水文件（不应传 VPS：执行日志/审计报告/隔离目录名）
    "EXECUTION_LOG.md", "EXECUTION_REPORT.md",
}

# 【死代码清理列表】本地已删除的文件，部署时自动从服务器删除，保持服务器干净
# 新增死代码直接加进来，部署时自动清理
DEAD_REMOTE_FILES = [
    "core/cache_manager.py",
    "core/migrate.py",
    "core/monitoring.py",
    "core/rate_limiter.py",
    "core/router_statistics.py",
    "core/router_database.py",
    "core/trendradar_news.py",
    "modules/predictive_patrol.py",
    "modules/stats_report.py",
    # v5.40.0 死链路清理：JSON 加载后唯一 getter 全仓零调用，内容消费走内置常量池
    "data/tarot_cards.json",
    "data/fortune_texts.json",
    # 旧健康/自动回滚入口会把 health 200 当整体健康并自动改生产，已由只读巡检控制面取代。
    "scripts/health_check.py",
    "scripts/auto_rollback.py",
    "scripts/rollback_config.json",
    "docs/review-report-20260621.md",
    # 内部文档（曾误上传至 VPS，现已从 ROOT_FILES 移除；部署时清理远端旧版本，
    # 避免暴露安全策略/踩坑病历/模块清单）
    "AGENTS.md",
    "AI_DEBUG_HISTORY.md",
    "project_snapshot.md",
]

# 需要动态扫描的目录（递归收集所有 .py 文件）
SCAN_DIRS = [
    "core",
    "modules",
    "dashboard",
    "scripts",
    "tasks",
    "migrations",
    "i18n",
    "assets",
]  # 运行代码、自动任务、Alembic 迁移与 i18n 语言包必须随同一次版本部署；assets 含 PIL 图片卡中文字体（LXGWWenKai），VPS 缺失会导致汉字变豆腐块

# 各扫描目录的扩展名映射（未列出的目录默认扫描 .py）
# i18n 目录只含 .json 语言包；assets 含字体/图片等二进制资源，需显式声明扩展名。
# dashboard 含前端模板（v5.38.69 起前端拆分为真实 .html 文件），缺失会导致页面白屏。
SCAN_DIR_EXTS = {
    "i18n": [".json"],
    "assets": [".ttf", ".ttc", ".otf", ".woff", ".woff2", ".png", ".jpg", ".jpeg", ".gif"],
    "dashboard": [".py", ".html"],
}

# 单文件体积上限（字节）。超过则跳过并警告，避免误上传缓存图片/旧数据库/视频。
# 字体文件通常几 MB 量级，给 20MB 足够；数据库/视频不可能混进 SCAN_DIRS，但作为兜底。
MAX_UPLOAD_FILE_SIZE = 20 * 1024 * 1024  # 20 MB

# 无论是否在 SCAN_DIRS 中，命中这些路径片段都直接跳过（兜底）。
SKIP_PATH_FRAGMENTS = (
    "runtime/cache", "runtime/logs", "runtime/audit-reports",
    "runtime/demo", "__pycache__", ".git/",
    "_quarantine_", "EXECUTION_", "_tmp_",
)

# 根目录下需要上传的文件
ROOT_FILES = [
    "main.py",
    "version.py",
    "windows_helper.py",
    "start_dashboard.py",
    "README.md",
    "CHANGELOG.md",
    "VERSION.md",
    "alembic.ini",
    "config.json.example",
    # 内部文档（AGENTS.md/AI_DEBUG_HISTORY.md/project_snapshot.md）不上传 VPS，
    # 避免暴露安全策略、踩坑病历和模块清单。如需查阅请在本地仓库查看。
    # VERSION.md 是版本说明（非内部规则），保留上传供 VPS 端查版本。
]

# 项目内只读巡检的可部署静态资产；精确白名单，禁止把真实 config/.env 一并上传。
PROJECT_AUDIT_FILES = [
    "config/project-audit.example.json",
    "config/systemd/mory-project-audit@.service",
    "config/systemd/mory-project-audit-production-truth.timer",
    "config/systemd/mory-project-audit-drift.timer",
    "config/systemd/mory-project-audit-monthly.timer",
]

# 需要上传到 /etc/systemd/system/ 的服务文件
# [v5.31.2 整改] 只保留双核心服务；mory-media-* 是引用不存在的 `main.py --media`
# 参数的坏桩（启动必崩），已从仓库删除，不再部署。
SERVICE_FILES = [
    "config/mory-dashboard.service",
    "config/mory-assistant.service",
]


def _collect_upload_files():
    """动态收集所有需要上传的代码/资源文件。

    三层过滤：
    1. EXCLUDE_NAMES：明确的文件名/目录黑名单
    2. SKIP_PATH_FRAGMENTS：路径片段（如 runtime/cache）
    3. MAX_UPLOAD_FILE_SIZE：单文件体积上限（20MB，避免误传缓存/数据库）
    """
    files = []
    skipped_large = []
    skipped_path = []
    # 根目录文件
    for f in ROOT_FILES:
        fp = ROOT / f
        if fp.exists():
            files.append(f)
    for f in PROJECT_AUDIT_FILES:
        fp = ROOT / f
        if fp.is_file():
            files.append(f)
    # 递归扫描子目录（按目录决定扩展名，默认 .py；i18n 等目录走 SCAN_DIR_EXTS）
    for dir_name in SCAN_DIRS:
        dir_path = ROOT / dir_name
        if not dir_path.exists():
            continue
        exts = SCAN_DIR_EXTS.get(dir_name, [".py"])
        for ext in exts:
            for py_file in sorted(dir_path.rglob(f"*{ext}")):
                rel = py_file.relative_to(ROOT).as_posix()
                # 1. 排除文件/目录名
                if any(exc in rel for exc in EXCLUDE_NAMES):
                    continue
                # 2. 路径片段黑名单（兜底，避免 runtime/cache 混进 SCAN_DIRS）
                if any(frag in rel for frag in SKIP_PATH_FRAGMENTS):
                    skipped_path.append(rel)
                    continue
                # 3. 体积上限（字体/图像应远小于 20MB；命中大概率是缓存 PNG 或意外文件）
                try:
                    size = py_file.stat().st_size
                    if size > MAX_UPLOAD_FILE_SIZE:
                        skipped_large.append((rel, size // 1024 // 1024))
                        continue
                except OSError:
                    pass
                files.append(rel)
    if skipped_large:
        print(f"  ⚠️ [收集] 跳过 {len(skipped_large)} 个超大文件（>{MAX_UPLOAD_FILE_SIZE//1024//1024}MB）:")
        for rel, mb in skipped_large[:5]:
            print(f"     - {rel} ({mb}MB)")
        if len(skipped_large) > 5:
            print(f"     ... 其余 {len(skipped_large)-5} 个省略")
    if skipped_path:
        print(f"  ℹ️ [收集] 按路径黑名单跳过 {len(skipped_path)} 个文件")
    return files


UPLOAD_FILES = _collect_upload_files()


# ──────────────────────────────────────────────────────
# 【v5.31.4 修复】部署健壮性：信号兜底 + 独立重连重启
# ──────────────────────────────────────────────────────
import signal

# 部署状态追踪：外部信号(如工具超时SIGTERM)触发时，如实标记所处阶段。
_DEPLOY_STATE = {
    "phase": "init",
}


def _signal_handler(signum, frame):
    """捕获 SIGTERM/SIGINT：不得通过重启同一未验证版本冒充恢复。"""
    phase = _DEPLOY_STATE["phase"]
    print(f"\n⚠️ 收到信号 {signum}（phase={phase}），部署中止。")
    print("  ⛔ 不自动重启未验证代码；保留快照供受控人工回滚。")
    sys.exit(1)


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


def main() -> bool:
    print("=" * 60)
    print("  Mory小助理 · 一键部署到VPS")
    print("=" * 60)

    source_ok, source_detail = _deploy_source_gate()
    if not source_ok:
        print(f"❌ 部署源门禁阻断：{source_detail}")
        return False
    print(f"  ✅ 部署源门禁：{source_detail}")

    # [v5.31.4 修复] 注册信号兜底：工具超时(SIGTERM)等外部中断时，先拉起服务再退出
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
        logging.getLogger('deploy_vps').debug(f'非致命忽略: {_e}')

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
    try:
        client, sftp = _open_deploy_connection()
    except Exception as e:
        print(f"❌ SSH连接失败：{e}")
        sys.exit(1)
    print("  ✅ 连接成功")

    # restart_attempted：仅当 [4/5] 的 systemctl restart 已真正发出才置 True。
    # deploy_ok 仅在 health=200 + 双服务 active 后置 True。
    restart_attempted = False
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

        # [v5.38.32 加固] 不再提前 stop 服务：全程保持双服务运行，
        # 待代码/配置全部就位后在 [4/5] 单步 systemctl restart 完成切换。
        # 旧版先 stop 再上传，若进程在停摆窗口被外部硬杀（finally 不可靠），
        # 双服务会长时间下线；现方案任意时刻被中断，服务都在跑上一版本（安全侧）。
        # 在 restart 之前中断时，已在运行的旧进程不受影响。

        # 4.5 部署前备份 VPS 当前代码。备份失败即停止，避免无恢复证据覆盖线上文件。
        # [v5.38.32 加固] 改为 tar 精准快照：排除凭据、config、mory.db/.venv/logs/runtime/backups/缓存，
        # 避免旧版 cp -r 整目录复制（含大型运行态）拖慢部署并放大被外部中断的风险窗口。
        # 备份落 backups/code_deploy_*.tar.gz，保留最近 2 份；回滚 = 解压覆盖。
        print("\n  备份 VPS 当前代码 ...")
        try:
            bak_stdin, bak_stdout, bak_stderr = client.exec_command(
                "mkdir -p " + VPS_PATH + "/backups", timeout=15)
            bak_stdout.channel.recv_exit_status()
        except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
            logging.getLogger('deploy_vps').debug(f'非致命忽略: {_e}')
        backup_cmd = _code_backup_command()
        try:
            stdin, stdout, stderr = client.exec_command(backup_cmd, timeout=180)
            rc = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace").strip()
            if rc == 0 and "BACKUP_OK" in out:
                print("  ✅ VPS 代码已备份（tar 快照，保留最近 2 个）")
            else:
                err = stderr.read().decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"VPS代码备份返回码 {rc}，拒绝继续部署：{(err or out)[:200]}")
        except Exception as e:
            raise RuntimeError(f"VPS代码备份失败，拒绝继续部署：{e}") from e

        # 5. 上传代码文件
        print("\n[3/5] 上传代码文件 ...")
        files_to_upload = []
        skipped_ul = []
        for rel_path in UPLOAD_FILES:
            local_full = ROOT / rel_path
            if not local_full.exists():
                continue
            # 上传前二次检查（兜底：防止 _collect_upload_files 后本地又新增大文件）
            try:
                sz = local_full.stat().st_size
                if sz > MAX_UPLOAD_FILE_SIZE:
                    skipped_ul.append((rel_path, sz // 1024 // 1024))
                    continue
            except OSError:
                pass
            if any(frag in rel_path for frag in SKIP_PATH_FRAGMENTS):
                continue
            remote_path = f"{VPS_PATH}/{rel_path}"
            files_to_upload.append((rel_path, remote_path))
        if skipped_ul:
            print(f"  ⚠️ [上传前] 二次过滤跳过 {len(skipped_ul)} 个超大文件:")
            for rp, mb in skipped_ul[:3]:
                print(f"     - {rp} ({mb}MB)")

        client, sftp, uploaded = _upload_files_resilient(client, sftp, files_to_upload)
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
        for extra in ["requirements.lock", "requirements.in"]:
            local_extra = ROOT / extra
            if local_extra.exists():
                try:
                    sftp.put(str(local_extra), f"{VPS_PATH}/{extra}")
                    print(f"  ✅ {extra}")
                except Exception as e:
                    print(f"  ⚠️ {extra} 上传失败：{e}")

        # 先验证关键导入与 Dashboard 运行时精确锁版本；漂移时按唯一 lock 同步。
        print("\n  安装/同步 Python 依赖 ...")
        dep_check = (
            f"cd {VPS_PATH} && python3 -c 'import telebot, flask, gevent, gunicorn, apscheduler, "
            "nudenet, onnxruntime, cv2; "
            'print(\"DEPS_IMPORT_OK\")' "' 2>/dev/null && "
            f"{_dashboard_runtime_probe_command()}"
        )
        try:
            stdin, stdout, stderr = client.exec_command(dep_check, timeout=15)
            dep_out = stdout.read().decode("utf-8", errors="replace").strip()
        except Exception as e:
            dep_out = ""
            print(f"  ⚠️ 依赖预检异常：{e}")
        if "DEPS_IMPORT_OK" in dep_out and "DASHBOARD_RUNTIME_LOCK_OK" in dep_out:
            print("  ✅ 依赖已满足且 Dashboard 运行时与锁定版本一致")
        else:
            print("  ⏳ 依赖缺失或版本漂移，按 requirements.lock 同步 ...")
            try:
                install_cmd = (
                    f"cd {VPS_PATH} && "
                    "(python3 -m pip install --user -r requirements.lock --break-system-packages "
                    "|| python3 -m pip install --user -r requirements.lock)"
                )
                stdin, stdout, stderr = client.exec_command(install_cmd, timeout=180)
                out = stdout.read().decode("utf-8", errors="replace").strip()
                err = stderr.read().decode("utf-8", errors="replace").strip()
                exit_code = stdout.channel.recv_exit_status()
                if exit_code == 0:
                    print("  ✅ requirements.lock 已安装")
                else:
                    tail = "\n".join((out + "\n" + err).splitlines()[-20:])
                    raise RuntimeError(f"requirements.lock 安装失败 rc={exit_code}:\n{tail}")
            except Exception as e:
                raise RuntimeError(f"依赖锁同步失败，拒绝重启到未知运行时：{e}") from e

        stdin, stdout, stderr = client.exec_command(
            _dashboard_runtime_probe_command(), timeout=20)
        runtime_out = stdout.read().decode("utf-8", errors="replace").strip()
        runtime_err = stderr.read().decode("utf-8", errors="replace").strip()
        if stdout.channel.recv_exit_status() != 0 or "DASHBOARD_RUNTIME_LOCK_OK" not in runtime_out:
            raise RuntimeError(f"Dashboard 运行时版本读回失败：{runtime_err or runtime_out}")

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
        stdin, stdout, stderr = client.exec_command(
            f"install -d -m 0700 {VPS_PATH}/.deploy-staging", timeout=10)
        if stdout.channel.recv_exit_status() != 0:
            err = stderr.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"创建私有部署暂存目录失败：{err}")
        for svc_rel in SERVICE_FILES:
            local_svc = ROOT / svc_rel
            if local_svc.exists():
                svc_name = Path(svc_rel).name
                try:
                    sftp.put(str(local_svc), _service_staging_path(svc_name))
                    stdin, stdout, stderr = client.exec_command(
                        _service_install_command(svc_name), timeout=10)
                    exit_code = stdout.channel.recv_exit_status()
                    if exit_code == 0:
                        print(f"  ✅ {svc_name} → /etc/systemd/system/")
                    else:
                        err = stderr.read().decode("utf-8", errors="replace").strip()
                        raise RuntimeError(f"{svc_name} 安装失败：{err}")
                except Exception as e:
                    raise RuntimeError(f"systemd unit 部署失败：{e}") from e

        # daemon-reload + enable 双服务
        stdin, stdout, stderr = client.exec_command(
            _enable_services_command(), timeout=15)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code == 0:
            print("  ✅ daemon-reload完成，mory-assistant/mory-dashboard均已enable")
        else:
            err = stderr.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"daemon-reload/enable返回码 {exit_code}：{err}")

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

        # root 执行面与凭据权限必须在重启前收紧；失败即阻断部署。
        print("  收紧凭据与 watchdog 权限 ...")
        stdin, stdout, stderr = client.exec_command(
            _runtime_permission_hardening_command(), timeout=20)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            err = stderr.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"运行态权限加固失败：{err or 'unknown error'}")
        print("  ✅ .env/config/db 已最小权限化，root cron 使用 root-owned watchdog")

        # SQLite migration 可能重建表或去重数据；必须先留下可校验的一致性快照。
        print("  备份生产数据库（在线一致性快照） ...")
        stdin, stdout, stderr = client.exec_command(
            _database_backup_command(), timeout=180)
        backup_out = stdout.read().decode("utf-8", errors="replace").strip()
        backup_err = stderr.read().decode("utf-8", errors="replace").strip()
        backup_rc = stdout.channel.recv_exit_status()
        if backup_rc != 0 or not backup_out.startswith("DB_BACKUP_OK "):
            raise RuntimeError(
                "生产数据库备份或完整性校验失败，拒绝执行迁移："
                f"{(backup_err or backup_out)[-1200:]}"
            )
        print(f"  ✅ {backup_out}")

        # schema 必须在新代码重启前升级；应用启动期不再允许按请求懒建表。
        print("  执行数据库迁移 ...")
        stdin, stdout, stderr = client.exec_command(
            _database_migration_command(), timeout=180)
        migration_out = stdout.read().decode("utf-8", errors="replace").strip()
        migration_err = stderr.read().decode("utf-8", errors="replace").strip()
        migration_rc = stdout.channel.recv_exit_status()
        if migration_rc != 0 or "(head)" not in migration_out:
            raise RuntimeError(
                "数据库迁移未到 Alembic head，拒绝重启新代码："
                f"{(migration_err or migration_out)[-1200:]}"
            )
        print("  ✅ 生产数据库已升级并读回 Alembic head")

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

        print("\n  ✅ gunicorn + gevent 已由 requirements.lock 精确锁定并读回")

        # 6. 重启双服务并进入运行态门禁
        print("\n[4/5] 启动Bot服务 ...")
        _DEPLOY_STATE["phase"] = "starting"
        stdin, stdout, stderr = client.exec_command("sudo systemctl restart mory-assistant mory-dashboard", timeout=60)
        restart_attempted = True
        exit_code = stdout.channel.recv_exit_status()
        if exit_code == 0:
            print("  ✅ Bot和Dashboard已重启")
        else:
            err = stderr.read().decode("utf-8", errors="replace").strip()
            print(f"  ❌ 启动失败：{err}（将继续执行失败关闭验证）")

        # [v5.31.4 修复] 健康检查轮询：start 是异步的，必须等真正起来再判成功
        # [v5.38.32 加固] 同时校验双服务 is-active（restart 返回 0 不代表进程存活），
        # 轮询上限 20 次（约 60s）覆盖 gunicorn 慢启动。
        print("  ⏳ 等待服务就绪并轮询 health ...")
        for attempt in range(1, 21):
            time.sleep(3)
            try:
                hc = client.exec_command("curl -s -o /dev/null -w '%{http_code}' http://localhost:6616/api/health", timeout=10)
                code = hc[1].read().decode("utf-8", "replace").strip()
            except Exception:
                code = ""
            active_out = ""
            try:
                ac = client.exec_command("systemctl is-active mory-assistant mory-dashboard", timeout=10)
                active_out = ac[1].read().decode("utf-8", errors="replace").strip()
            except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
                logging.getLogger('deploy_vps').debug(f'非致命忽略: {_e}')
            both_active = active_out.count("active") >= 2
            if code == "200" and both_active:
                print(f"  ✅ health=200 且双服务 active（第 {attempt+1} 次轮询）")
                deploy_ok = True
                break
            else:
                print(f"  ... 第 {attempt+1} 次 health={code or '无响应'} active=[{active_out.replace(chr(10), '/')}]")
        if not deploy_ok:
            print("  ⚠️ 启动后 health 未达 200 或服务未 active，发布门禁将失败关闭")

        # 7. 验证部署
        print("\n验证部署结果 ...")
        try:
            deploy_ok = verify_deployment(client, VPS_PATH)
        except Exception as e:
            deploy_ok = False
            print(f"  ❌ 验证脚本异常，发布门禁失败：{e}")

    except Exception as e:
        print(f"\n❌ 部署过程异常：{e}")
        print("  将保留快照并失败关闭，不自动重启未验证版本。")

    finally:
        # 验证失败必须失败关闭：不能通过重启同一未验证版本伪造“已恢复”。
        # 上一步受限快照会保留，供明确的人工回滚流程使用。
        if restart_attempted and not deploy_ok:
            print("\n⛔ [失败关闭] 新版本未通过运行态验证；拒绝重启同一未验证版本或报告成功。")
            print("   部署快照已保留，请按受控回滚流程恢复并重新取证。")
        # 关闭主 SSH（忽略任何错误，主连接可能在中断中已部分损坏）
        try:
            client.close()
        except Exception as _e:  # v5.41.0 卫生整改：留痕不吞错
            logging.getLogger('deploy_vps').debug(f'非致命忽略: {_e}')
    # ── 输出最终结果 ──
    if deploy_ok:
        print("\n" + "=" * 60)
        print("  ✅ 部署运行态门禁通过！")
        print("  ℹ️ 仍须按受影响入口完成真实业务探针，才能宣称业务闭环")
        print("=" * 60)
    else:
        # deploy_ok=False，不能把 liveness 或残留服务进程描述成发布完成。
        print("\n" + "=" * 60)
        print("  ⛔ 部署验证失败，当前版本不可视为已发布")
        print("  请按受控回滚流程恢复快照并重新取证")
        print("  查看日志：journalctl -u mory-assistant -n 100 --no-pager")
        print("=" * 60)
    return deploy_ok


def _handle_cli_args(args) -> bool:
    """处理命令行参数；返回 True 表示已经输出结果，不应继续部署。"""
    if not args:
        return False
    if args in (["-h"], ["--help"]):
        print("用法：python deploy_vps.py")
        print("说明：不带参数时执行生产部署；--help 仅显示本说明。")
        return True
    print(f"❌ 未知参数：{' '.join(args)}")
    print("使用 python deploy_vps.py --help 查看用法。")
    raise SystemExit(2)


if __name__ == "__main__":
    _configure_stdio()
    if not _handle_cli_args(sys.argv[1:]):
        raise SystemExit(_deployment_exit_code(main()))
