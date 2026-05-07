#!/usr/bin/env python3
"""
One-click restore helper for a freshly reinstalled Linux server.

It creates a local tar.gz archive, uploads it with scp, extracts it on the
server, runs configured startup commands, and optionally checks HTTP URLs.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], dry_run: bool = False, cwd: Path | None = None) -> None:
    printable = " ".join(cmd)
    print(f"$ {printable}")
    if dry_run:
        return
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def should_exclude(path: Path, patterns: list[str]) -> bool:
    parts = set(path.parts)
    name = path.name
    return any(pattern == name or pattern in parts for pattern in patterns)


def make_archive(config: dict, archive_path: Path) -> None:
    upload_items = config["paths"].get("local_upload_items", ["."])
    excludes = config["paths"].get("exclude", [])

    with tarfile.open(archive_path, "w:gz") as tar:
        for item in upload_items:
            source = (ROOT / item).resolve()
            if not source.exists():
                raise FileNotFoundError(f"Local upload item does not exist: {source}")
            if source.is_file():
                if not should_exclude(source.relative_to(ROOT), excludes):
                    tar.add(source, arcname=source.relative_to(ROOT))
                continue

            for current in source.rglob("*"):
                rel = current.relative_to(ROOT)
                if should_exclude(rel, excludes):
                    continue
                tar.add(current, arcname=rel)


def ssh_base(config: dict) -> list[str]:
    server = config["server"]
    base = ["ssh", "-p", str(server.get("port", 22))]
    ssh_key = server.get("ssh_key")
    if ssh_key:
        base.extend(["-i", ssh_key])
    base.append(f"{server['user']}@{server['host']}")
    return base


def scp_base(config: dict) -> list[str]:
    server = config["server"]
    base = ["scp", "-P", str(server.get("port", 22))]
    ssh_key = server.get("ssh_key")
    if ssh_key:
        base.extend(["-i", ssh_key])
    return base


def run_remote(config: dict, command: str, dry_run: bool) -> None:
    run(ssh_base(config) + [command], dry_run=dry_run)


def run_command_group(config: dict, name: str, dry_run: bool) -> None:
    commands = config.get("commands", {}).get(name, [])
    if commands:
        print(f"\n== {name} ==")
    for command in commands:
        run_remote(config, command, dry_run)


def upload_archive(config: dict, archive_path: Path, dry_run: bool) -> str:
    server = config["server"]
    remote_app_dir = config["paths"]["remote_app_dir"].rstrip("/")
    remote_archive = f"{remote_app_dir}/recovery_upload.tar.gz"
    target = f"{server['user']}@{server['host']}:{remote_archive}"
    run(scp_base(config) + [str(archive_path), target], dry_run=dry_run)
    return remote_archive


def check_health(urls: list[str], dry_run: bool) -> None:
    if not urls:
        return
    print("\n== health_checks ==")
    for url in urls:
        print(f"GET {url}")
        if dry_run:
            continue
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                print(f"{url} -> HTTP {resp.status}")
        except Exception as exc:
            raise RuntimeError(f"Health check failed for {url}: {exc}") from exc


def require_tools(dry_run: bool) -> None:
    missing = [tool for tool in ("ssh", "scp") if shutil.which(tool) is None]
    if missing and not dry_run:
        raise RuntimeError(f"Missing required local tools: {', '.join(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore app data to a clean server.")
    parser.add_argument("--config", default="restore_config.json", help="Path to restore config JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without running them.")
    args = parser.parse_args()

    config_path = (ROOT / args.config).resolve()
    if not config_path.exists():
        print(f"Config not found: {config_path}", file=sys.stderr)
        print("Copy restore_config.example.json to restore_config.json first.", file=sys.stderr)
        return 2

    config = load_config(config_path)
    require_tools(args.dry_run)

    remote_app_dir = config["paths"]["remote_app_dir"].rstrip("/")
    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / "recovery_upload.tar.gz"
        print("== package ==")
        print(f"Creating archive: {archive_path}")
        if not args.dry_run:
            make_archive(config, archive_path)

        run_command_group(config, "before_upload", args.dry_run)
        remote_archive = upload_archive(config, archive_path, args.dry_run)

        print("\n== extract ==")
        run_remote(
            config,
            f"mkdir -p {remote_app_dir} && tar -xzf {remote_archive} -C {remote_app_dir}",
            args.dry_run,
        )

        run_command_group(config, "after_upload", args.dry_run)
        run_command_group(config, "restart", args.dry_run)
        run_command_group(config, "verify", args.dry_run)
        check_health(config.get("health_checks", []), args.dry_run)

    print("\nRestore flow finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
