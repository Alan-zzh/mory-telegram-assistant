"""check_deploy_ready.py 冒烟测试（v5.38.25 新增：一键部署就绪检查）。"""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

spec = importlib.util.spec_from_file_location("check_deploy_ready", ROOT / "scripts" / "check_deploy_ready.py")
cdr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cdr)


def test_version_alignment_ok_on_current_docs():
    ok, detail = cdr.check_version_alignment()
    assert ok, f"version.py 与 VERSION.md 不一致: {detail}"
    assert re.match(r"^版本一致 v\d+\.\d+\.\d+$", detail)


def test_required_functions_exist():
    for fn in ("check_git_clean", "check_version_alignment", "_run_script", "main"):
        assert callable(getattr(cdr, fn)), f"缺少函数 {fn}"


def test_run_script_returns_tuple():
    rc, summary = cdr._run_script("verify_db_methods.py")
    assert isinstance(rc, int)
    assert isinstance(summary, str)
