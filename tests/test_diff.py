from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_config_sync.cli import main
from ai_config_sync.diff_package import diff_package
from ai_config_sync.export_package import build_export_package, write_export_package
from ai_config_sync.selectors import parse_selectors


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# A minimal opencode config with one provider, one model, and an apiKey credential.
OPENCODE_BASE = {
    "provider": {
        "sense-nova": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Sense Nova",
            "options": {"baseURL": "https://api.example.com", "apiKey": "SECRET_A"},
            "models": {
                "glm-4": {"name": "GLM-4", "limit": {"context": 128000, "output": 4096}},
            },
        }
    }
}


def _export_package(home: Path, output: Path, *, include_credentials: bool = True, passphrase: str | None = "pw") -> Path:
    package = build_export_package(
        home=home,
        include_credentials=include_credentials,
        passphrase=passphrase if include_credentials else None,
    )
    write_export_package(package, output)
    return output


def _status_counts(entries) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.status] = counts.get(e.status, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# (a) Round-trip in-sync: export A, diff A against the package → all in-sync.
# ---------------------------------------------------------------------------
def test_diff_round_trip_all_in_sync(tmp_path):
    home_a = tmp_path / "a"
    write_json(home_a / ".config/opencode/opencode.json", OPENCODE_BASE)
    package = _export_package(home_a, tmp_path / "pkg.json")

    report = diff_package(input_path=str(package), home=str(home_a), passphrase="pw")

    counts = _status_counts(report.entries)
    assert counts.get("only-current", 0) == 0
    assert counts.get("only-package", 0) == 0
    assert counts.get("differs", 0) == 0
    assert counts.get("in-sync", 0) > 0
    # sanity: at least one provider, one model, one credential entry
    kinds = {e.kind for e in report.entries}
    assert {"provider", "model", "credential"}.issubset(kinds)


# ---------------------------------------------------------------------------
# (b) only-package: empty home diffed against package → all only-in-package.
# ---------------------------------------------------------------------------
def test_diff_empty_home_all_only_in_package(tmp_path):
    home_a = tmp_path / "a"
    home_b = tmp_path / "b"  # empty
    home_b.mkdir()
    write_json(home_a / ".config/opencode/opencode.json", OPENCODE_BASE)
    package = _export_package(home_a, tmp_path / "pkg.json")

    report = diff_package(input_path=str(package), home=str(home_b), passphrase="pw")

    counts = _status_counts(report.entries)
    assert counts.get("only-current", 0) == 0
    assert counts.get("in-sync", 0) == 0
    assert counts.get("differs", 0) == 0
    assert counts.get("only-package", 0) > 0
    # For only-package providers we emit a single provider-level entry (the
    # spec sample shows e.g. "provider moonshot  only on current" with no
    # model/credential sub-entries). So every only-package entry is a provider.
    only_pkg_kinds = {e.kind for e in report.entries if e.status == "only-package"}
    assert only_pkg_kinds == {"provider"}


# ---------------------------------------------------------------------------
# (c) only-current + differs: A exported; home C has an extra provider and
#     a modified model field → diff reports only-current and differs.
# ---------------------------------------------------------------------------
def test_diff_only_current_and_differs(tmp_path):
    home_a = tmp_path / "a"
    write_json(home_a / ".config/opencode/opencode.json", OPENCODE_BASE)
    package = _export_package(home_a, tmp_path / "pkg.json")

    home_c = tmp_path / "c"
    home_c_config = json.loads(json.dumps(OPENCODE_BASE))
    # Modify the model display_name so it differs from the package.
    home_c_config["provider"]["sense-nova"]["models"]["glm-4"]["name"] = "GLM-4 Flash"
    # Add an extra provider that exists only on current side.
    home_c_config["provider"]["moonshot"] = {
        "npm": "@ai-sdk/openai-compatible",
        "options": {"baseURL": "https://moonshot.cn", "apiKey": "MOONSHOT_SECRET"},
        "models": {"moonshot-v1": {"name": "Moonshot v1"}},
    }
    write_json(home_c / ".config/opencode/opencode.json", home_c_config)

    report = diff_package(input_path=str(package), home=str(home_c), passphrase="pw")

    statuses = {(e.client, e.provider, e.model, e.kind, e.status, e.detail) for e in report.entries}

    # sense-nova provider: in-sync (base_url/type/display_name match)
    assert ("opencode", "sense-nova", None, "provider", "in-sync", None) in statuses
    # glm-4 model: differs (display_name changed)
    glm4 = [e for e in report.entries if e.client == "opencode" and e.provider == "sense-nova" and e.model == "glm-4" and e.kind == "model"]
    assert len(glm4) == 1
    assert glm4[0].status == "differs"
    assert "display_name" in (glm4[0].detail or "")
    # moonshot provider: only on current
    moonshot = [e for e in report.entries if e.client == "opencode" and e.provider == "moonshot" and e.kind == "provider"]
    assert len(moonshot) == 1
    assert moonshot[0].status == "only-current"

    counts = _status_counts(report.entries)
    assert counts.get("only-current", 0) >= 1
    assert counts.get("differs", 0) >= 1


# ---------------------------------------------------------------------------
# (d) Selector filter: --include opencode:sense-nova only compares that
#     provider; an unrelated provider should not appear in the report.
# ---------------------------------------------------------------------------
def test_diff_selector_filters_to_one_provider(tmp_path):
    home_a = tmp_path / "a"
    config = {
        "provider": {
            "sense-nova": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": "https://api.example.com", "apiKey": "SECRET"},
                "models": {"glm-4": {"name": "GLM-4"}},
            },
            "moonshot": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": "https://moonshot.cn", "apiKey": "MOON"},
                "models": {"moonshot-v1": {}},
            },
        }
    }
    write_json(home_a / ".config/opencode/opencode.json", config)
    package = _export_package(home_a, tmp_path / "pkg.json")

    selectors = parse_selectors(["opencode:sense-nova"])
    report = diff_package(input_path=str(package), home=str(home_a), selectors=selectors, passphrase="pw")

    provider_ids = {e.provider for e in report.entries}
    assert provider_ids == {"sense-nova"}
    assert "moonshot" not in provider_ids


# ---------------------------------------------------------------------------
# (e) No-credentials package: diff works without supplying a passphrase.
# ---------------------------------------------------------------------------
def test_diff_no_credentials_package_does_not_require_passphrase(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_SYNC_PASSPHRASE", raising=False)
    home_a = tmp_path / "a"
    write_json(home_a / ".config/opencode/opencode.json", OPENCODE_BASE)
    package = _export_package(home_a, tmp_path / "pkg.json", include_credentials=False, passphrase=None)

    # No passphrase passed and no env var set — should not raise.
    report = diff_package(input_path=str(package), home=str(home_a), passphrase=None)

    # The package omitted credentials, so credential entries reflect that the
    # current side has a secret but the package does not.
    cred_entries = [e for e in report.entries if e.kind == "credential"]
    assert cred_entries, "expected at least one credential entry"
    assert all(e.status == "only-current" for e in cred_entries)


# ---------------------------------------------------------------------------
# (f) Credential differs: same ref, different values → differs, and the
#     detail must not leak any secret value.
# ---------------------------------------------------------------------------
def test_diff_credential_differs_does_not_leak_value(tmp_path, capsys):
    home_a = tmp_path / "a"
    config_a = json.loads(json.dumps(OPENCODE_BASE))
    config_a["provider"]["sense-nova"]["options"]["apiKey"] = "SECRET_A"
    write_json(home_a / ".config/opencode/opencode.json", config_a)
    package = _export_package(home_a, tmp_path / "pkg.json", include_credentials=True, passphrase="pw")

    home_b = tmp_path / "b"
    config_b = json.loads(json.dumps(OPENCODE_BASE))
    config_b["provider"]["sense-nova"]["options"]["apiKey"] = "SECRET_B"
    write_json(home_b / ".config/opencode/opencode.json", config_b)

    report = diff_package(input_path=str(package), home=str(home_b), passphrase="pw")

    cred = [e for e in report.entries if e.kind == "credential"]
    assert len(cred) == 1
    assert cred[0].status == "differs"
    assert cred[0].detail == "values differ"

    # Make sure neither secret value appears anywhere in the rendered report.
    rendered = json.dumps([e.__dict__ for e in report.entries])
    assert "SECRET_A" not in rendered
    assert "SECRET_B" not in rendered


# ---------------------------------------------------------------------------
# CLI smoke: `ai-sync diff` end-to-end through main() returns 0 and prints
# the expected header. Also confirms no secret leaks to stdout.
# ---------------------------------------------------------------------------
def test_cli_diff_smoke(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("AI_SYNC_PASSPHRASE", "pw")
    home_a = tmp_path / "a"
    write_json(home_a / ".config/opencode/opencode.json", OPENCODE_BASE)
    package = tmp_path / "pkg.json"
    assert main(["export", "--home", str(home_a), "--output", str(package)]) == 0

    rc = main(["diff", "--home", str(home_a), str(package)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Comparing current machine against" in out
    assert "Summary:" in out
    # No secret value should ever be printed.
    assert "SECRET_A" not in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
