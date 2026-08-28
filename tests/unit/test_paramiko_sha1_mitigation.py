# -*- coding: utf-8 -*-
"""Paramiko 未发布修复版期间，所有直接 SSH 连接必须禁用 RSA+SHA-1。"""

import ast
from pathlib import Path

from core.vps_config import secure_paramiko_connect_kwargs


ROOT = Path(__file__).resolve().parents[2]


def test_secure_paramiko_options_disable_sha1_without_disabling_rsa_sha2():
    disabled = secure_paramiko_connect_kwargs()["disabled_algorithms"]
    assert disabled["keys"] == ["ssh-rsa"]
    assert disabled["pubkeys"] == ["ssh-rsa"]
    assert "rsa-sha2-256" not in disabled["keys"]
    assert "rsa-sha2-512" not in disabled["keys"]


def test_direct_paramiko_connect_calls_use_central_mitigation():
    missing = []
    for directory in ("core", "dashboard", "scripts", "runtime"):
        for path in (ROOT / directory).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "paramiko" not in source or ".connect(" not in source:
                continue
            tree = ast.parse(source, filename=str(path))
            ssh_client_names = {
                target.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == "paramiko"
                and node.value.func.attr == "SSHClient"
                for target in node.targets
                if isinstance(target, ast.Name)
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr != "connect":
                    continue
                if not isinstance(node.func.value, ast.Name) or node.func.value.id not in ssh_client_names:
                    continue
                has_mitigation = any(
                    keyword.arg is None
                    and isinstance(keyword.value, ast.Call)
                    and getattr(keyword.value.func, "id", "") == "secure_paramiko_connect_kwargs"
                    for keyword in node.keywords
                )
                if not has_mitigation:
                    missing.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert missing == []
