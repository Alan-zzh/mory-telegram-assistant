from scripts import check_exception_hygiene


def test_scanner_rejects_commented_pass_after_broad_exception(monkeypatch, tmp_path):
    target = tmp_path / "bad.py"
    target.write_text(
        "try:\n    work()\nexcept Exception:\n    pass  # this used to evade the gate\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_exception_hygiene, "_iter_targets", lambda: iter([target]))
    monkeypatch.setattr(check_exception_hygiene, "ROOT", tmp_path)

    violations, _ = check_exception_hygiene.scan()

    assert len(violations) == 1
    assert "宽捕获静默 pass" in violations[0]


def test_scanner_allows_commented_pass_only_with_explicit_hygiene_reason(monkeypatch, tmp_path):
    target = tmp_path / "allowed.py"
    target.write_text(
        "try:\n    work()\nexcept Exception:  # hygiene-allow: stderr is unavailable\n"
        "    pass  # deliberate fallback\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_exception_hygiene, "_iter_targets", lambda: iter([target]))
    monkeypatch.setattr(check_exception_hygiene, "ROOT", tmp_path)

    violations, _ = check_exception_hygiene.scan()

    assert violations == []


def test_scanner_treats_named_api_exception_as_narrow(monkeypatch, tmp_path):
    target = tmp_path / "narrow.py"
    target.write_text(
        "try:\n    work()\nexcept ApiTelegramException:\n    pass  # expected missing message\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_exception_hygiene, "_iter_targets", lambda: iter([target]))
    monkeypatch.setattr(check_exception_hygiene, "ROOT", tmp_path)

    violations, narrow_allowed = check_exception_hygiene.scan()

    assert violations == []
    assert narrow_allowed == 1
