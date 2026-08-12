#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mory project-local, read-only audit control plane.

The scheduler only invokes this script.  This script never deploys, restarts,
changes production configuration, sends messages, or installs capabilities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "project-audit.example.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "runtime" / "audit-reports" / "project-automation"

STATUS_PASS = "pass"
STATUS_GAP = "evidence_gap"
STATUS_FAILED = "failed"
EXIT_CODES = {STATUS_PASS: 0, STATUS_GAP: 2, STATUS_FAILED: 3}
STATUS_RANK = {STATUS_PASS: 0, STATUS_GAP: 1, STATUS_FAILED: 2}

_SECRET_RE = re.compile(
    r"(?i)(token|password|passwd|secret|api[_-]?key|cookie|authorization)\s*[:=]\s*\S+"
)
_TOKEN_PATTERNS = (
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]{10,})?\b"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact(value: Any, limit: int = 1200) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(key): _redact(item, limit) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, limit) for item in value]
    text = _SECRET_RE.sub(lambda match: f"{match.group(1)}=<REDACTED>", str(value))
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub("<REDACTED>", text)
    return text if len(text) <= limit else text[:limit] + "...<TRUNCATED>"


def _check(
    check_id: str,
    status: str,
    summary: str,
    *,
    evidence: Any = None,
    coverage: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": check_id,
        "status": status,
        "summary": summary,
    }
    if coverage:
        result["coverage"] = coverage
    if evidence not in (None, "", [], {}):
        result["evidence"] = _redact(evidence)
    return result


def _aggregate(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return STATUS_GAP
    return max((item["status"] for item in checks), key=STATUS_RANK.__getitem__)


_MONITOR_EVIDENCE_KEYS = {
    "l1_resources": {"cpu_usage", "mem_avail_pct", "disk_usage_pct", "load1", "net_conn", "uptime", "_warn", "_crit", "_exc"},
    "l4_business_metrics": {"task_1h", "task_5min", "task_status_1h", "recent_tasks", "token_usage_1h", "token_usage_5min", "token_cost_1h_sum", "conversion_1h", "orphan_1h", "_warn", "_crit", "_exc"},
    "l5_scheduler": {"task_status_1h", "failed_1h", "running_1h", "aborted_1h", "stale_running_30m", "recent_persisted_failures", "scheduler_metrics_errors", "recent_scheduled_tasks", "watchdog_usec", "_warn", "_crit", "_exc"},
    "l6_watchdog": {"cron_tasks", "legacy_cron_residue", "watchdog_log_age_sec", "_warn", "_crit", "_exc"},
}


def _filter_monitor_evidence(layer: str, details: dict[str, Any]) -> dict[str, Any]:
    allowed = _MONITOR_EVIDENCE_KEYS[layer]
    return {key: value for key, value in details.items() if key in allowed}


def load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "mory.project-audit-config/v1":
        raise ValueError("unsupported project audit config schema")
    return payload


def _remote_exec(client: Any, command: str, timeout: int = 30) -> tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace").strip()
    error = stderr.read().decode("utf-8", errors="replace").strip()
    return stdout.channel.recv_exit_status(), output, error


def _remote_check_status(name: str, rc: int, output: str, error: str) -> tuple[str, str]:
    if rc == 2:
        return STATUS_GAP, f"{name} evidence unavailable"
    if rc != 0 or error:
        return STATUS_FAILED, f"{name} failed"
    expected = {
        "Bot状态": "active",
        "Dashboard状态": "active",
        "Health API": "200",
        "运行版本": None,
        "Bot日志": "STARTUP_LOG_CLEAN",
        "Dashboard日志": "STARTUP_LOG_CLEAN",
        "配置完整性": "ALL CONFIG OK",
        "凭据键": "ENV_KEYS_OK",
        "数据库完整性": "DB_INTEGRITY_OK",
        "调度事实": "SCHEDULER_TRUTH_OK",
        "调度注册": "SCHEDULER_REGISTRY_OK",
        "权限": "PERMISSIONS_OK",
    }
    marker = expected.get(name)
    if marker is not None and not output.startswith(marker):
        return STATUS_FAILED, f"{name} returned an unexpected receipt"
    if name == "运行版本":
        from version import VERSION

        if output != VERSION:
            return STATUS_FAILED, "production release identity differs from workspace version"
    return STATUS_PASS, f"{name} verified"


def _business_receipt_command(remote_root: str, probes: list[dict[str, Any]]) -> str:
    safe_root = str(PurePosixPath(remote_root))
    encoded = json.dumps(probes, ensure_ascii=True, separators=(",", ":"))
    return f"""cd {safe_root} && /usr/bin/python3 << 'PYEOF'
import json, sqlite3, time
probes = json.loads({json.dumps(encoded)})
conn = sqlite3.connect('file:mory.db?mode=ro', uri=True)
now = int(time.time())
failed = []
receipts = []
for probe in probes:
    task_key = str(probe['task_key'])
    max_age = int(probe.get('max_age_hours', 36)) * 3600
    row = conn.execute(
        "SELECT start_ts FROM task_execution_history WHERE task_key=? AND status='success' ORDER BY start_ts DESC LIMIT 1",
        (task_key,),
    ).fetchone()
    if not row or now - int(row[0]) > max_age:
        failed.append(task_key)
    else:
        receipts.append({{'task_key': task_key, 'age_seconds': now - int(row[0])}})
if failed:
    print('BUSINESS_RECEIPT_MISSING ' + ','.join(failed))
    raise SystemExit(1)
print('BUSINESS_RECEIPTS_OK ' + json.dumps(receipts, separators=(',', ':')))
PYEOF"""


def audit_production_truth(config: dict[str, Any], client_factory: Callable[[], Any] | None = None) -> list[dict[str, Any]]:
    """Collect production evidence without changing the host or Telegram."""
    checks: list[dict[str, Any]] = []
    if client_factory is None:
        from scripts.puzan_loop_monitor import make_ssh_client

        client_factory = make_ssh_client
    try:
        client = client_factory()
    except Exception as exc:
        return [_check("production.ssh", STATUS_GAP, "production SSH evidence unavailable", evidence=type(exc).__name__)]

    try:
        from core.deploy_utils import _deployment_verification_checks
        from core.vps_config import VPS_PATH
        from scripts import puzan_loop_monitor

        # Reuse the established monitor for resource, business, scheduler and
        # watchdog evidence.  Service/health/version/startup-window checks are
        # handled below by the shared deployment verification contract.
        for layer, collector in (
            ("l1_resources", puzan_loop_monitor.l1_vps_check),
            ("l4_business_metrics", puzan_loop_monitor.l4_biz_check),
            ("l5_scheduler", puzan_loop_monitor.l5_scheduler_check),
            ("l6_watchdog", puzan_loop_monitor.l6_watchdog_check),
        ):
            try:
                raw_status, details = collector(client)
                if raw_status == "OK":
                    status = STATUS_PASS
                elif raw_status in {"WARN", "CRITICAL"}:
                    status = STATUS_FAILED
                else:
                    status = STATUS_GAP
                checks.append(
                    _check(
                        f"production.{layer}",
                        status,
                        f"puzan monitor {layer} returned {raw_status}",
                        evidence=_filter_monitor_evidence(layer, details),
                        coverage="existing puzan_loop_monitor read-only collector",
                    )
                )
            except Exception as exc:
                checks.append(
                    _check(
                        f"production.{layer}",
                        STATUS_GAP,
                        f"puzan monitor {layer} evidence unavailable",
                        evidence=type(exc).__name__,
                    )
                )

        for name, command in _deployment_verification_checks(VPS_PATH):
            try:
                rc, output, error = _remote_exec(client, command)
                status, summary = _remote_check_status(name, rc, output, error)
                checks.append(
                    _check(
                        "production." + re.sub(r"\W+", "_", name).strip("_").lower(),
                        status,
                        summary,
                        evidence={"exit_code": rc, "stdout": output, "stderr": error},
                    )
                )
            except Exception as exc:
                checks.append(
                    _check(
                        "production." + re.sub(r"\W+", "_", name).strip("_").lower(),
                        STATUS_GAP,
                        f"{name} evidence collection failed",
                        evidence=type(exc).__name__,
                    )
                )

        probes = list(config.get("production_truth", {}).get("business_receipts", []))
        if not probes:
            checks.append(
                _check(
                    "production.business_receipts",
                    STATUS_GAP,
                    "no read-only business receipt probes are configured",
                    coverage="health and scheduler evidence cannot substitute for a business receipt",
                )
            )
        else:
            command = _business_receipt_command(VPS_PATH, probes)
            try:
                rc, output, error = _remote_exec(client, command)
                status = STATUS_PASS if rc == 0 and output.startswith("BUSINESS_RECEIPTS_OK") else STATUS_FAILED
                checks.append(
                    _check(
                        "production.business_receipts",
                        status,
                        "configured read-only business receipts verified" if status == STATUS_PASS else "required business receipt is missing or stale",
                        evidence={"exit_code": rc, "stdout": output, "stderr": error},
                        coverage="configured task success receipts only; no Telegram write action",
                    )
                )
            except Exception as exc:
                checks.append(
                    _check(
                        "production.business_receipts",
                        STATUS_GAP,
                        "business receipt evidence unavailable",
                        evidence=type(exc).__name__,
                    )
                )
    finally:
        try:
            client.close()
        except Exception:
            pass
    return checks


def _run_local_command(args: list[str], timeout: int = 120) -> tuple[int, str, str]:
    completed = subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return completed.returncode, completed.stdout.rstrip(), completed.stderr.rstrip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_drift(config: dict[str, Any], client_factory: Callable[[], Any] | None = None) -> list[dict[str, Any]]:
    """Compare repository governance/deploy truth with read-only production facts."""
    checks: list[dict[str, Any]] = []
    for check_id, command in (
        ("drift.docs", [sys.executable, "scripts/doc_consistency.py"]),
        ("drift.config_contract", [sys.executable, "scripts/check_config_sync.py"]),
    ):
        try:
            rc, output, error = _run_local_command(command)
            checks.append(
                _check(
                    check_id,
                    STATUS_PASS if rc == 0 else STATUS_FAILED,
                    "local contract is consistent" if rc == 0 else "local contract drift detected",
                    evidence={"command": command, "exit_code": rc, "stdout": output, "stderr": error},
                )
            )
        except Exception as exc:
            checks.append(_check(check_id, STATUS_GAP, "local drift check unavailable", evidence=type(exc).__name__))

    watched = list(config.get("drift", {}).get("watched_workspace_paths", []))
    if watched:
        rc, output, error = _run_local_command(["git", "status", "--porcelain", "--", *watched])
        checks.append(
            _check(
                "drift.workspace_state",
                STATUS_GAP if rc == 0 and output else (STATUS_PASS if rc == 0 else STATUS_GAP),
                "watched control files have uncommitted state" if output else "watched control files match Git workspace truth",
                evidence={"exit_code": rc, "paths": [line[3:] for line in output.splitlines()], "stderr": error},
                coverage="uncommitted state is not treated as deployed truth",
            )
        )

    if client_factory is None:
        from scripts.puzan_loop_monitor import make_ssh_client

        client_factory = make_ssh_client
    try:
        client = client_factory()
    except Exception as exc:
        checks.append(_check("drift.production", STATUS_GAP, "production drift evidence unavailable", evidence=type(exc).__name__))
        return checks

    try:
        from core.vps_config import VPS_PATH

        mappings = list(config.get("drift", {}).get("remote_hash_mappings", []))
        for mapping in mappings:
            local_rel = str(mapping["local"])
            remote_rel = str(mapping["remote"])
            local_path = PROJECT_ROOT / local_rel
            check_id = "drift.hash." + re.sub(r"\W+", "_", local_rel).strip("_").lower()
            if not local_path.is_file():
                checks.append(_check(check_id, STATUS_FAILED, "local drift source is missing", evidence=local_rel))
                continue
            remote_path = str(PurePosixPath(VPS_PATH) / remote_rel)
            rc, output, error = _remote_exec(client, f"sha256sum {remote_path} | awk '{{print $1}}'")
            local_hash = _sha256(local_path)
            if rc != 0 or not output:
                status, summary = STATUS_GAP, "remote file identity unavailable"
            elif output != local_hash:
                status, summary = STATUS_FAILED, "workspace and production file identities differ"
            else:
                status, summary = STATUS_PASS, "workspace and production file identities match"
            checks.append(
                _check(
                    check_id,
                    status,
                    summary,
                    evidence={"local": local_rel, "remote": remote_rel, "local_sha256": local_hash, "remote_sha256": output, "exit_code": rc, "stderr": error},
                )
            )

        local_keys = sorted(json.loads((PROJECT_ROOT / "config.json.example").read_text(encoding="utf-8")).keys())
        key_command = f"""cd {VPS_PATH} && /usr/bin/python3 - << 'PYEOF'
import json
print(json.dumps(sorted(json.load(open('config.json')).keys()), separators=(',', ':')))
PYEOF"""
        rc, output, error = _remote_exec(client, key_command)
        if rc != 0:
            checks.append(_check("drift.config_keys", STATUS_GAP, "production config key set unavailable", evidence={"exit_code": rc, "stderr": error}))
        else:
            try:
                remote_keys = json.loads(output)
                missing = sorted(set(local_keys) - set(remote_keys))
                extra = sorted(set(remote_keys) - set(local_keys))
                status = STATUS_FAILED if missing else STATUS_PASS
                checks.append(
                    _check(
                        "drift.config_keys",
                        status,
                        "production config key contract matches" if status == STATUS_PASS else "production config is missing declared keys",
                        evidence={"missing_keys": missing, "extra_keys": extra},
                        coverage="key names only; no credential or config values are read into the receipt",
                    )
                )
            except json.JSONDecodeError:
                checks.append(_check("drift.config_keys", STATUS_GAP, "production config key receipt is invalid"))
    finally:
        try:
            client.close()
        except Exception:
            pass
    return checks


_REPEAT_CATEGORIES = {
    "production_truth": ("生产", "vps", "deploy", "部署", "health", "watchdog"),
    "scheduler_truth": ("scheduler", "调度", "cron", "running", "任务"),
    "reply_regression": ("reply", "cta", "persona", "回复", "人设", "问候"),
    "moderation": ("ad", "spam", "广告", "误封", "禁言", "解封"),
    "record_governance": ("record", "handoff", "drift", "记录", "规则", "文档"),
}

_EXISTING_OWNERS = {
    "production_truth": "scripts/project_audit_control.py:production-truth + Puzan mory-assistant-maintenance",
    "scheduler_truth": "scripts/project_audit_control.py:production-truth + core/scheduler_monitor.py",
    "reply_regression": "Puzan mory-assistant-maintenance",
    "moderation": "Puzan mory-assistant-maintenance",
    "record_governance": "Puzan record-keeping + records-autopilot",
}


def _classify_candidate(category: str, count: int) -> tuple[str, str, str]:
    if category == "record_governance":
        return "skip", "existing record-keeping owner already covers this workflow", "reuse records-autopilot apply plus verify-only strict receipts"
    if category in {"production_truth", "scheduler_truth"}:
        return "Automation", "keep read-only collection/reporting; hand repair to an Agent", "structured receipt plus deterministic exit code"
    if category in {"reply_regression", "moderation"}:
        return "Agent", "requires contextual diagnosis and regression judgment", "failing fixture, normal counterexample, and affected-entry probe"
    if count >= 3:
        return "Skill", "stable local workflow is recurring", "same input contract produces a repeatable local verification receipt"
    return "skip", "insufficient recurrence for a new capability", "reassess after another dated occurrence"


def audit_monthly(config: dict[str, Any]) -> list[dict[str, Any]]:
    monthly = config.get("monthly", {})
    lookback_days = int(monthly.get("lookback_days", 90))
    minimum = int(monthly.get("minimum_occurrences", 2))
    rc, output, error = _run_local_command(
        ["git", "log", f"--since={lookback_days}.days", "--date=short", "--pretty=%ad|%H|%s"],
        timeout=30,
    )
    if rc != 0:
        return [_check("monthly.source", STATUS_GAP, "Git history is unavailable", evidence={"exit_code": rc, "stderr": error})]
    hits: dict[str, list[dict[str, str]]] = {key: [] for key in _REPEAT_CATEGORIES}
    for line in output.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        date, commit_id, subject = parts
        lowered = subject.lower()
        for category, keywords in _REPEAT_CATEGORIES.items():
            if any(keyword.lower() in lowered for keyword in keywords):
                hits[category].append({"date": date, "commit": commit_id[:12], "subject": subject[:180]})

    candidates = []
    for category, occurrences in hits.items():
        if len(occurrences) < minimum:
            continue
        capability, reason, acceptance = _classify_candidate(category, len(occurrences))
        candidates.append(
            {
                "category": category,
                "occurrences": len(occurrences),
                "dates": sorted({item["date"] for item in occurrences}),
                "classification": capability,
                "existing_owner": _EXISTING_OWNERS.get(category, "none"),
                "reason": reason,
                "estimated_saving": "hypothesis only: reduce repeated evidence collection and context reconstruction",
                "acceptance": acceptance,
                "evidence": occurrences[:10],
                "action": "candidate_only_no_install",
            }
        )
    return [
        _check(
            "monthly.repeated_work_candidates",
            STATUS_PASS,
            f"generated {len(candidates)} read-only candidates; installed nothing",
            evidence={"lookback_days": lookback_days, "minimum_occurrences": minimum, "candidates": candidates},
            coverage="Git commit dates and subjects only; estimates are not measured savings",
        )
    ]


def _write_receipt(receipt: dict[str, Any], output: Path | None) -> Path:
    if output is None:
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        output = DEFAULT_OUTPUT_DIR / f"{receipt['profile']}-{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        output.chmod(0o600)
    except OSError:
        pass
    latest = output.parent / f"latest-{receipt['profile']}.json"
    if latest != output:
        latest.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            latest.chmod(0o600)
        except OSError:
            pass
    return output


def run_profile(profile: str, config: dict[str, Any]) -> dict[str, Any]:
    started = _utc_now()
    if profile == "production-truth":
        checks = audit_production_truth(config)
    elif profile == "drift":
        checks = audit_drift(config)
    elif profile == "monthly":
        checks = audit_monthly(config)
    else:
        checks = []
        for child in ("production-truth", "drift", "monthly"):
            child_receipt = run_profile(child, config)
            checks.append(
                _check(
                    f"profile.{child}",
                    child_receipt["status"],
                    f"{child} profile completed",
                    evidence={"counts": child_receipt["counts"], "checks": child_receipt["checks"]},
                )
            )
    status = _aggregate(checks)
    counts = Counter(item["status"] for item in checks)
    return {
        "schema_version": "mory.project-audit-receipt/v1",
        "profile": profile,
        "started_at": started,
        "finished_at": _utc_now(),
        "read_only": True,
        "status": status,
        "exit_code": EXIT_CODES[status],
        "counts": {key: counts.get(key, 0) for key in (STATUS_PASS, STATUS_GAP, STATUS_FAILED)},
        "checks": checks,
        "boundaries": {
            "production_mutation": "not_authorized_and_not_implemented",
            "deployment": "not_authorized_and_not_implemented",
            "external_messages": "not_authorized_and_not_implemented",
            "capability_installation": "monthly_profile_is_candidate_only",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mory project-local read-only audit control plane")
    parser.add_argument("--profile", choices=("production-truth", "drift", "monthly", "all"), required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-write", action="store_true", help="print receipt only; do not persist it")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        receipt = run_profile(args.profile, config)
        output = None if args.no_write else _write_receipt(receipt, args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        receipt = {
            "schema_version": "mory.project-audit-receipt/v1",
            "profile": args.profile,
            "read_only": True,
            "status": STATUS_GAP,
            "exit_code": EXIT_CODES[STATUS_GAP],
            "checks": [_check("control.config", STATUS_GAP, "control-plane configuration unavailable", evidence=type(exc).__name__)],
        }
        output = None
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    if output:
        print(f"RECEIPT_PATH={output}", file=sys.stderr)
    return int(receipt["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
