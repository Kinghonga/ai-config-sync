from __future__ import annotations

import json
from pathlib import Path

from ai_config_sync.export_package import SCHEMA, build_export_package, load_export_package, write_export_package
from ai_config_sync.import_package import import_package


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_export_schema_and_no_credentials_marks_omitted(tmp_path):
    write_json(
        tmp_path / ".config/opencode/opencode.json",
        {"provider": {"sense-nova": {"npm": "@ai-sdk/openai-compatible", "options": {"apiKey": "SECRET"}, "models": {"deepseek-v4-flash": {}}}}},
    )
    package = build_export_package(home=tmp_path, include_credentials=False)
    assert package["schema"] == SCHEMA
    assert package["version"] == 1
    assert package["exported_at"].endswith("Z")
    assert package["encrypted_credentials"] is None
    provider = package["clients"][0]["providers"][0]
    assert provider["credentials_omitted"] is True
    assert "SECRET" not in json.dumps(package)


def test_export_import_roundtrip_with_credentials(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    write_json(source / ".config/opencode/opencode.json", {"provider": {"sense-nova": {"npm": "@ai-sdk/openai-compatible", "options": {"baseURL": "https://api", "apiKey": "SECRET"}, "models": {"m1": {"name": "M1"}}}}})
    package = build_export_package(home=source, include_credentials=True, passphrase="pw")
    output = tmp_path / "package.json"
    write_export_package(package, output)
    clients, creds, _ = load_export_package(output, "pw")
    assert clients[0].client == "opencode"
    assert creds.secrets["opencode:sense-nova"]["options"]["apiKey"] == "SECRET"
    report = import_package(input_path=output, home=dest, passphrase="pw")
    imported = json.loads((dest / ".config/opencode/opencode.json").read_text())
    assert imported["provider"]["sense-nova"]["options"]["apiKey"] == "SECRET"
    assert report.changed_files


def test_import_dry_run_does_not_write(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    write_json(source / ".claude/settings.json", {"env": {"ANTHROPIC_MODEL": "claude", "ANTHROPIC_API_KEY": "SECRET"}})
    output = tmp_path / "package.json"
    write_export_package(build_export_package(home=source, include_credentials=False), output)
    report = import_package(input_path=output, home=dest, dry_run=True)
    assert report.changed_files
    assert not (dest / ".claude/settings.json").exists()
