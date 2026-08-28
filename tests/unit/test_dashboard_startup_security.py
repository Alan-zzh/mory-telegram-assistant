"""Dashboard 安全启动器回归测试。"""

import start_dashboard


def test_startup_requires_hash_and_never_generates_plaintext_password(monkeypatch):
    monkeypatch.setattr(start_dashboard, "load_env_file", lambda: None)
    monkeypatch.setenv("DASHBOARD_SECRET", "test-dashboard-secret-1234567890")
    monkeypatch.delenv("DASHBOARD_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)

    assert start_dashboard.main() == 2
    assert "DASHBOARD_PASSWORD" not in start_dashboard.os.environ
