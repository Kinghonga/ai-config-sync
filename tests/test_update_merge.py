from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_config_sync.adapters.claude_code import ClaudeCodeAdapter
from ai_config_sync.adapters.opencode import OpenCodeAdapter
from ai_config_sync.cli import build_parser
from ai_config_sync.models import ClientConfig, CredentialBundle, ModelConfig, ProviderConfig


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# OpenCode --update tests
# ---------------------------------------------------------------------------


def test_opencode_update_only_diffs_model_display_name(tmp_path):
    """(a) --update only updates the differing model field (display_name); base_url and other model stay unchanged."""
    config = tmp_path / ".config/opencode/opencode.json"
    write_json(
        config,
        {
            "provider": {
                "existing": {
                    "options": {"baseURL": "https://old", "apiKey": "OLD"},
                    "models": {
                        "m1": {"name": "Old Name", "limit": {"context": 1000, "output": 2000}},
                        "m2": {"name": "Keep"},
                    },
                }
            }
        },
    )
    incoming = ClientConfig(
        "opencode",
        "~/.config/opencode/opencode.json",
        [
            ProviderConfig(
                "existing",
                base_url="https://old",
                credential_ref="opencode:existing",
                raw={"options": {"baseURL": "https://old"}, "models": {}},
                models=[
                    ModelConfig("m1", "New Name", context_limit=1000, output_limit=2000, raw={"name": "New Name", "limit": {"context": 1000, "output": 2000}}),
                    ModelConfig("m2", "Keep", raw={"name": "Keep"}),
                ],
            )
        ],
    )
    report = OpenCodeAdapter(tmp_path).merge(
        incoming,
        CredentialBundle({"opencode:existing": {"options": {"apiKey": "OLD"}}}),
        selectors=[],
        dry_run=False,
        force=False,
        update=True,
    )
    data = json.loads(config.read_text())
    provider = data["provider"]["existing"]
    # base_url unchanged
    assert provider["options"]["baseURL"] == "https://old"
    # apiKey unchanged (no credential conflict)
    assert provider["options"]["apiKey"] == "OLD"
    # m1 display_name updated, limits unchanged
    assert provider["models"]["m1"]["name"] == "New Name"
    assert provider["models"]["m1"]["limit"] == {"context": 1000, "output": 2000}
    # m2 untouched
    assert provider["models"]["m2"] == {"name": "Keep"}
    # report: only the name field updated; no conflicts, no skips
    assert any("m1" in u and "name" in u for u in report.updated)
    assert not any("base_url" in u for u in report.updated)
    assert not report.conflicts
    assert not report.skipped


def test_opencode_update_changes_base_url(tmp_path):
    """(b) --update updates base_url while models stay unchanged."""
    config = tmp_path / ".config/opencode/opencode.json"
    write_json(
        config,
        {
            "provider": {
                "existing": {
                    "options": {"baseURL": "https://old", "apiKey": "OLD"},
                    "models": {"m1": {"name": "Keep"}},
                }
            }
        },
    )
    incoming = ClientConfig(
        "opencode",
        "~/.config/opencode/opencode.json",
        [
            ProviderConfig(
                "existing",
                base_url="https://new",
                credential_ref="opencode:existing",
                raw={"options": {"baseURL": "https://new"}, "models": {}},
                models=[ModelConfig("m1", "Keep", raw={"name": "Keep"})],
            )
        ],
    )
    report = OpenCodeAdapter(tmp_path).merge(
        incoming,
        CredentialBundle({"opencode:existing": {"options": {"apiKey": "OLD"}}}),
        selectors=[],
        dry_run=False,
        force=False,
        update=True,
    )
    data = json.loads(config.read_text())
    provider = data["provider"]["existing"]
    assert provider["options"]["baseURL"] == "https://new"
    assert provider["options"]["apiKey"] == "OLD"
    assert provider["models"]["m1"] == {"name": "Keep"}
    assert any("base_url" in u for u in report.updated)
    assert not any("m1" in u for u in report.updated)
    assert not report.conflicts


def test_opencode_update_credential_value_no_conflict(tmp_path):
    """(c) --update updates credential value when it differs and does NOT report a conflict."""
    config = tmp_path / ".config/opencode/opencode.json"
    write_json(
        config,
        {
            "provider": {
                "existing": {
                    "options": {"baseURL": "https://old", "apiKey": "OLD"},
                    "models": {"m1": {"name": "Keep"}},
                }
            }
        },
    )
    incoming = ClientConfig(
        "opencode",
        "~/.config/opencode/opencode.json",
        [
            ProviderConfig(
                "existing",
                base_url="https://old",
                credential_ref="opencode:existing",
                raw={"options": {"baseURL": "https://old"}, "models": {}},
                models=[ModelConfig("m1", "Keep", raw={"name": "Keep"})],
            )
        ],
    )
    report = OpenCodeAdapter(tmp_path).merge(
        incoming,
        CredentialBundle({"opencode:existing": {"options": {"apiKey": "NEW"}}}),
        selectors=[],
        dry_run=False,
        force=False,
        update=True,
    )
    data = json.loads(config.read_text())
    assert data["provider"]["existing"]["options"]["apiKey"] == "NEW"
    assert any("credential" in u for u in report.updated)
    # No conflict reported even though the field existed
    assert not report.conflicts


def test_opencode_update_adds_new_model_to_existing_provider(tmp_path):
    """(d) --update adds a new model_id to an existing provider -> report.added."""
    config = tmp_path / ".config/opencode/opencode.json"
    write_json(
        config,
        {
            "provider": {
                "existing": {
                    "options": {"baseURL": "https://old", "apiKey": "OLD"},
                    "models": {"m1": {"name": "Keep"}},
                }
            }
        },
    )
    incoming = ClientConfig(
        "opencode",
        "~/.config/opencode/opencode.json",
        [
            ProviderConfig(
                "existing",
                base_url="https://old",
                credential_ref="opencode:existing",
                raw={"options": {"baseURL": "https://old"}, "models": {}},
                models=[
                    ModelConfig("m1", "Keep", raw={"name": "Keep"}),
                    ModelConfig("m2", "New Model", raw={"name": "New Model"}),
                ],
            )
        ],
    )
    report = OpenCodeAdapter(tmp_path).merge(
        incoming,
        CredentialBundle({"opencode:existing": {"options": {"apiKey": "OLD"}}}),
        selectors=[],
        dry_run=False,
        force=False,
        update=True,
    )
    data = json.loads(config.read_text())
    models = data["provider"]["existing"]["models"]
    assert models["m1"] == {"name": "Keep"}
    assert models["m2"] == {"name": "New Model"}
    assert any("m2" in a for a in report.added)
    assert not any("m2" in u for u in report.updated)


# ---------------------------------------------------------------------------
# Claude Code --update tests
# ---------------------------------------------------------------------------


def test_claude_update_model_env_value_preserves_other_keys(tmp_path):
    """(e) --update updates ANTHROPIC_MODEL value, other env keys (API key, OTHER) stay unchanged."""
    config = tmp_path / ".claude/settings.json"
    write_json(
        config,
        {"env": {"ANTHROPIC_MODEL": "claude-old", "ANTHROPIC_API_KEY": "OLD", "OTHER": "keep"}},
    )
    incoming = ClientConfig(
        "claude-code",
        "~/.claude/settings.json",
        [
            ProviderConfig(
                "anthropic-env",
                base_url=None,
                credential_ref="claude-code:anthropic-env",
                raw={"env": {}},
                models=[ModelConfig("claude-new", raw={"env_key": "ANTHROPIC_MODEL", "name_key": "ANTHROPIC_MODEL_NAME"})],
            )
        ],
    )
    report = ClaudeCodeAdapter(tmp_path).merge(
        incoming,
        CredentialBundle({"claude-code:anthropic-env": {"env": {"ANTHROPIC_API_KEY": "OLD"}}}),
        selectors=[],
        dry_run=False,
        force=False,
        update=True,
    )
    data = json.loads(config.read_text())
    env = data["env"]
    assert env["ANTHROPIC_MODEL"] == "claude-new"
    assert env["ANTHROPIC_API_KEY"] == "OLD"
    assert env["OTHER"] == "keep"
    assert any("claude-new" in u for u in report.updated)
    assert not report.conflicts


# ---------------------------------------------------------------------------
# CLI mutual-exclusion tests
# ---------------------------------------------------------------------------


def test_update_and_force_are_mutually_exclusive():
    """(f) Passing both --update and --force causes argparse to exit."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["import", "--force", "--update", "--input", "x.json"])


def test_update_flag_appears_in_import_help(capsys):
    """Smoke: --update is advertised on `import --help` alongside --force."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["import", "--help"])
    out = capsys.readouterr().out
    assert "--update" in out
    assert "--force" in out


# ---------------------------------------------------------------------------
# Regression tests: default and force behavior unchanged
# ---------------------------------------------------------------------------


def test_default_skip_behavior_unchanged(tmp_path):
    """(g) Without --update or --force, existing provider/model/credential are skipped/conflicted (no writes)."""
    config = tmp_path / ".config/opencode/opencode.json"
    write_json(
        config,
        {"provider": {"existing": {"options": {"apiKey": "OLD"}, "models": {"m1": {"name": "Old"}}}}},
    )
    incoming = ClientConfig(
        "opencode",
        "~/.config/opencode/opencode.json",
        [
            ProviderConfig(
                "existing",
                credential_ref="opencode:existing",
                raw={"options": {}, "models": {}},
                models=[ModelConfig("m1", "New", raw={"name": "New"})],
            )
        ],
    )
    report = OpenCodeAdapter(tmp_path).merge(
        incoming,
        CredentialBundle({"opencode:existing": {"options": {"apiKey": "NEW"}}}),
        selectors=[],
        dry_run=False,
        force=False,
        update=False,
    )
    assert "provider exists" in " ".join(report.skipped)
    assert "m1 model exists" in " ".join(report.conflicts)
    assert "credential field exists" in " ".join(report.conflicts)
    # Data untouched
    data = json.loads(config.read_text())
    assert data["provider"]["existing"]["options"]["apiKey"] == "OLD"
    assert data["provider"]["existing"]["models"]["m1"] == {"name": "Old"}


def test_force_override_behavior_unchanged(tmp_path):
    """(h) With --force (and no --update), the existing provider/models/credentials are overwritten wholesale."""
    config = tmp_path / ".config/opencode/opencode.json"
    write_json(
        config,
        {
            "provider": {
                "existing": {
                    "options": {"apiKey": "OLD", "baseURL": "https://old"},
                    "models": {"m1": {"name": "Old"}},
                }
            }
        },
    )
    incoming = ClientConfig(
        "opencode",
        "~/.config/opencode/opencode.json",
        [
            ProviderConfig(
                "existing",
                base_url="https://new",
                credential_ref="opencode:existing",
                raw={"options": {"baseURL": "https://new"}, "models": {"m1": {"name": "New"}}},
                models=[ModelConfig("m1", "New", raw={"name": "New"})],
            )
        ],
    )
    report = OpenCodeAdapter(tmp_path).merge(
        incoming,
        CredentialBundle({"opencode:existing": {"options": {"apiKey": "NEW"}}}),
        selectors=[],
        dry_run=False,
        force=True,
        update=False,
    )
    data = json.loads(config.read_text())
    provider = data["provider"]["existing"]
    assert provider["options"]["baseURL"] == "https://new"
    assert provider["options"]["apiKey"] == "NEW"
    assert provider["models"]["m1"] == {"name": "New"}
    # Force mode still records the provider-level update
    assert any("provider" in u for u in report.updated)
