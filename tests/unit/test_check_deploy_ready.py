"""check_deploy_ready.py 冒烟测试（v5.38.25 新增：一键部署就绪检查）。"""
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent.parent

spec = importlib.util.spec_from_file_location("check_deploy_ready", ROOT / "scripts" / "check_deploy_ready.py")
cdr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cdr)


def test_version_alignment_ok_on_current_docs():
    ok, detail = cdr.check_version_alignment()
    assert ok, f"version.py 与 VERSION.md 不一致: {detail}"
    assert re.match(r"^版本一致 v\d+\.\d+\.\d+$", detail)


def test_required_functions_exist():
    for fn in ("check_git_clean", "check_head_contains_main", "check_version_alignment", "_run_script", "main"):
        assert callable(getattr(cdr, fn)), f"缺少函数 {fn}"


def test_run_script_returns_tuple():
    rc, summary = cdr._run_script("verify_db_methods.py")
    assert isinstance(rc, int)
    assert isinstance(summary, str)


def test_current_branch_contains_main():
    ok, detail = cdr.check_head_contains_main()
    assert ok, detail


def test_stale_branch_is_blocked(monkeypatch):
    def fake_run(command, **_kwargs):
        if command[:3] == ["git", "rev-parse", "--verify"]:
            value = "mainsha" if command[-1] == "refs/heads/main" else "headsha"
            return SimpleNamespace(returncode=0, stdout=value + "\n", stderr="")
        if command[:3] == ["git", "merge-base", "--is-ancestor"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(cdr.subprocess, "run", fake_run)

    ok, detail = cdr.check_head_contains_main()

    assert not ok
    assert "全目录部署会回退主线文件" in detail
