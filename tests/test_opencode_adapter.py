from __future__ import annotations

import json
from pathlib import Path

from ai_config_sync.adapters.opencode import OpenCodeAdapter
from ai_config_sync.models import ClientConfig, CredentialBundle, ModelConfig, ProviderConfig


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_opencode_reads_provider_only_and_extracts_credentials(tmp_path):
    write_json(
        tmp_path / ".config/opencode/opencode.json",
        {
            "theme": "dark",
            "provider": {
                "sense-nova": {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "Sense Nova",
                    "options": {"baseURL": "https://example", "apiKey": "SECRET", "extra": "ok"},
                    "models": {"deepseek-v4-flash": {"name": "DeepSeek", "limit": {"context": 256000, "output": 65536}}},
                }
            },
        },
    )
    client, creds = OpenCodeAdapter(tmp_path).read()
    assert client is not None
    provider = client.providers[0]
    assert provider.provider_type == "openai-compatible"
    assert provider.base_url == "https://example"
    assert provider.credential_ref == "opencode:sense-nova"
    assert provider.raw["options"] == {"baseURL": "https://example", "extra": "ok"}
    assert provider.models[0].context_limit == 256000
    assert creds.secrets == {"opencode:sense-nova": {"options": {"apiKey": "SECRET"}}}


def test_opencode_merge_preserves_unrelated_top_level_and_skips_without_force(tmp_path):
    config = tmp_path / ".config/opencode/opencode.json"
    write_json(config, {"theme": "dark", "provider": {"existing": {"options": {"apiKey": "OLD"}, "models": {"m1": {}}}}})
    incoming = ClientConfig(
        "opencode",
        "~/.config/opencode/opencode.json",
        [ProviderConfig("existing", credential_ref="opencode:existing", raw={"options": {"baseURL": "https://new"}, "models": {}}, models=[ModelConfig("m1", raw={"name": "new"}), ModelConfig("m2", raw={})])],
    )
    report = OpenCodeAdapter(tmp_path).merge(incoming, CredentialBundle({"opencode:existing": {"options": {"apiKey": "NEW"}}}), selectors=[], dry_run=False, force=False)
    data = json.loads(config.read_text())
    assert data["theme"] == "dark"
    assert data["provider"]["existing"]["options"]["apiKey"] == "OLD"
    assert "m2" in data["provider"]["existing"]["models"]
    assert "m1 model exists" in " ".join(report.conflicts)
    assert list(config.parent.glob("opencode.json.bak.*"))
