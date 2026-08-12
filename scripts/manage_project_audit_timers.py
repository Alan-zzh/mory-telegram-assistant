#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plan, install, verify, or uninstall project-local systemd timers.

The default action is a read-only plan.  Host mutation requires both an
explicit install/uninstall action and ``--apply``.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / "config" / "systemd"
SYSTEMD_DIR = Path("/etc/systemd/system")
SERVICE_NAME = "mory-project-audit@.service"
TIMER_NAMES = (
    "mory-project-audit-production-truth.timer",
    "mory-project-audit-drift.timer",
    "mory-project-audit-monthly.timer",
)
UNIT_NAMES = (SERVICE_NAME, *TIMER_NAMES)


def render_units(project_root: Path = PROJECT_ROOT, python_path: Path | None = None, audit_user: str | None = None) -> dict[str, str]:
    root = project_root.resolve()
    python_path = (python_path or Path(sys.executable)).resolve()
    audit_user = audit_user or getpass.getuser()
    replacements = {
        "@PROJECT_ROOT@": str(root),
        "@PYTHON@": str(python_path),
        "@AUDIT_USER@": audit_user,
    }
    rendered: dict[str, str] = {}
    for name in UNIT_NAMES:
        text = (SOURCE_DIR / name).read_text(encoding="utf-8")
        for marker, value in replacements.items():
            text = text.replace(marker, value)
        if "@PROJECT_ROOT@" in text or "@PYTHON@" in text or "@AUDIT_USER@" in text:
            raise ValueError(f"unresolved marker in {name}")
        rendered[name] = text
    return rendered


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def build_plan(action: str, target_dir: Path = SYSTEMD_DIR) -> dict[str, object]:
    operations: list[str]
    if action == "install":
        operations = [
            *(f"render {name} -> {(target_dir / name).as_posix()}" for name in UNIT_NAMES),
            "systemctl daemon-reload",
            *(f"systemctl enable --now {name}" for name in TIMER_NAMES),
        ]
    elif action == "uninstall":
        operations = [
            *(f"systemctl disable --now {name}" for name in TIMER_NAMES),
            *(f"remove {(target_dir / name).as_posix()}" for name in UNIT_NAMES),
            "systemctl daemon-reload",
        ]
    else:
        operations = [f"verify {(target_dir / name).as_posix()}" for name in UNIT_NAMES]
    return {
        "schema_version": "mory.project-audit-timer-plan/v1",
        "action": action,
        "apply": False,
        "target": target_dir.as_posix(),
        "operations": operations,
        "external_boundary": "systemd host is unchanged unless --apply is explicitly supplied",
    }


def _require_apply_environment() -> None:
    if os.name == "nt" or not Path("/run/systemd/system").exists():
        raise RuntimeError("systemd host required")
    if os.geteuid() != 0:
        raise RuntimeError("root is required to change /etc/systemd/system")
    resolved = SYSTEMD_DIR.resolve()
    if resolved != Path("/etc/systemd/system"):
        raise RuntimeError("unexpected systemd target")


def _resolve_audit_user(audit_user: str) -> tuple[int, int]:
    import pwd

    entry = pwd.getpwnam(audit_user)
    return entry.pw_uid, entry.pw_gid


def _prepare_report_dir(report_dir: Path, audit_user: str) -> None:
    uid, gid = _resolve_audit_user(audit_user)
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists() and env_path.stat().st_uid != uid:
        raise RuntimeError("audit user must own the project .env; use a dedicated checkout/credential set")
    report_dir.mkdir(parents=True, exist_ok=True)
    os.chown(report_dir, uid, gid)
    os.chmod(report_dir, 0o700)


def install_units(rendered: dict[str, str], audit_user: str) -> dict[str, object]:
    _require_apply_environment()
    report_dir = PROJECT_ROOT / "runtime" / "audit-reports" / "project-automation"
    _prepare_report_dir(report_dir, audit_user)
    for name, content in rendered.items():
        target = SYSTEMD_DIR / name
        target.write_text(content, encoding="utf-8", newline="\n")
        os.chmod(target, 0o644)
    daemon = _systemctl("daemon-reload")
    results = [{"command": "daemon-reload", "exit_code": daemon.returncode, "stderr": daemon.stderr.strip()}]
    for name in TIMER_NAMES:
        result = _systemctl("enable", "--now", name)
        results.append({"command": f"enable --now {name}", "exit_code": result.returncode, "stderr": result.stderr.strip()})
    ok = all(item["exit_code"] == 0 for item in results)
    return {"status": "pass" if ok else "failed", "results": results}


def uninstall_units() -> dict[str, object]:
    _require_apply_environment()
    results = []
    for name in TIMER_NAMES:
        result = _systemctl("disable", "--now", name)
        results.append({"command": f"disable --now {name}", "exit_code": result.returncode, "stderr": result.stderr.strip()})
    for name in UNIT_NAMES:
        target = (SYSTEMD_DIR / name).resolve()
        if target.parent != SYSTEMD_DIR:
            raise RuntimeError(f"unsafe unit target: {target}")
        if target.exists():
            target.unlink()
    daemon = _systemctl("daemon-reload")
    results.append({"command": "daemon-reload", "exit_code": daemon.returncode, "stderr": daemon.stderr.strip()})
    ok = all(item["exit_code"] == 0 for item in results)
    return {"status": "pass" if ok else "failed", "results": results}


def verify_units(rendered: dict[str, str], target_dir: Path = SYSTEMD_DIR) -> dict[str, object]:
    checks = []
    for name, expected in rendered.items():
        target = target_dir / name
        present = target.is_file()
        matches = present and target.read_text(encoding="utf-8") == expected
        checks.append({"unit": name, "present": present, "matches": matches})
    installed = all(item["matches"] for item in checks)
    return {"status": "pass" if installed else "not_installed_or_drifted", "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Mory project-local audit timers")
    parser.add_argument("--action", choices=("plan", "install", "verify", "uninstall"), default="plan")
    parser.add_argument("--apply", action="store_true", help="required for install/uninstall host mutation")
    parser.add_argument("--audit-user", default=getpass.getuser())
    args = parser.parse_args(argv)

    planned_action = "install" if args.action == "plan" else args.action
    if args.action in {"install", "uninstall"} and not args.apply:
        payload = build_plan(args.action)
        payload["status"] = "planned_not_applied"
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    try:
        rendered = render_units(audit_user=args.audit_user)
        if args.action == "plan":
            payload = build_plan(planned_action)
            payload["status"] = "planned_not_applied"
            exit_code = 0
        elif args.action == "install":
            payload = install_units(rendered, args.audit_user)
            exit_code = 0 if payload["status"] == "pass" else 3
        elif args.action == "uninstall":
            payload = uninstall_units()
            exit_code = 0 if payload["status"] == "pass" else 3
        else:
            payload = verify_units(rendered)
            exit_code = 0 if payload["status"] == "pass" else 2
    except (OSError, RuntimeError, ValueError) as exc:
        payload = {"status": "evidence_gap", "error": type(exc).__name__, "message": str(exc)}
        exit_code = 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
