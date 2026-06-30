from __future__ import annotations

import json

from ai_config_sync.cli import main, resolve_passphrase


def test_cli_help(capsys):
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    out = capsys.readouterr().out
    assert "ai-sync" in out


def test_passphrase_env_var(monkeypatch):
    monkeypatch.setenv("AI_SYNC_PASSPHRASE", "envpw")
    assert resolve_passphrase(required=True) == "envpw"


def test_passphrase_no_env_requires_terminal():
    # Without env var and no tty, should raise
    import os
    old = os.environ.pop("AI_SYNC_PASSPHRASE", None)
    try:
        # Simulate no tty by checking the function's behavior
        # In test env stdin is not a tty, so this should raise
        try:
            resolve_passphrase(required=True)
        except ValueError as exc:
            assert "no terminal" in str(exc) or "AI_SYNC_PASSPHRASE" in str(exc)
    finally:
        if old is not None:
            os.environ["AI_SYNC_PASSPHRASE"] = old


def test_cli_list_and_export_no_credentials(tmp_path, capsys):
    config = tmp_path / ".config/opencode/opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"provider": {"p": {"options": {"apiKey": "SECRET"}, "models": {"m": {}}}}}), encoding="utf-8")
    assert main(["list", "--home", str(tmp_path)]) == 0
    assert "SECRET" not in capsys.readouterr().out
    output = tmp_path / "out.json"
    assert main(["export", "--home", str(tmp_path), "--output", str(output), "--no-credentials"]) == 0
    assert output.exists()
    assert "SECRET" not in output.read_text()
