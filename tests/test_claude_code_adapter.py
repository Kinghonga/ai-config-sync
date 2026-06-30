from __future__ import annotations

import json
from pathlib import Path

from ai_config_sync.adapters.claude_code import ClaudeCodeAdapter
from ai_config_sync.models import ClientConfig, CredentialBundle, ModelConfig, ProviderConfig


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_claude_reads_env_as_synthetic_provider(tmp_path):
    write_json(
        tmp_path / ".claude/settings.json",
        {"permissions": {"allow": []}, "env": {"ANTHROPIC_BASE_URL": "https://api", "ANTHROPIC_API_KEY": "SECRET", "ANTHROPIC_MODEL": "claude-sonnet", "ANTHROPIC_MODEL_NAME": "Sonnet", "OTHER": "keep"}},
    )
    client, creds = ClaudeCodeAdapter(tmp_path).read()
    assert client is not None
    provider = client.providers[0]
    assert provider.provider_id == "anthropic-env"
    assert provider.provider_type == "anthropic-compatible"
    assert provider.base_url == "https://api"
    assert provider.models[0].model_id == "claude-sonnet"
    assert provider.models[0].display_name == "Sonnet"
    assert creds.secrets == {"claude-code:anthropic-env": {"env": {"ANTHROPIC_API_KEY": "SECRET"}}}


def test_claude_merge_preserves_unrelated_settings_and_env(tmp_path):
    config = tmp_path / ".claude/settings.json"
    write_json(config, {"permissions": {"allow": []}, "env": {"OTHER": "keep"}})
    incoming = ClientConfig(
        "claude-code",
        "~/.claude/settings.json",
        [ProviderConfig("anthropic-env", base_url="https://api", credential_ref="claude-code:anthropic-env", raw={"env": {"ANTHROPIC_BASE_URL": "https://api"}}, models=[ModelConfig("claude-sonnet", "Sonnet", raw={"env_key": "ANTHROPIC_MODEL", "name_key": "ANTHROPIC_MODEL_NAME"})])],
    )
    ClaudeCodeAdapter(tmp_path).merge(incoming, CredentialBundle({"claude-code:anthropic-env": {"env": {"ANTHROPIC_API_KEY": "SECRET"}}}), selectors=[], dry_run=False, force=False)
    data = json.loads(config.read_text())
    assert data["permissions"] == {"allow": []}
    assert data["env"]["OTHER"] == "keep"
    assert data["env"]["ANTHROPIC_MODEL"] == "claude-sonnet"
    assert data["env"]["ANTHROPIC_API_KEY"] == "SECRET"
    assert list(config.parent.glob("settings.json.bak.*"))
