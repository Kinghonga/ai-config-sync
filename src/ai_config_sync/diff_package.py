from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ai_config_sync.export_package import load_export_package
from ai_config_sync.models import ClientConfig, ModelConfig, ProviderConfig
from ai_config_sync.scanner import scan
from ai_config_sync.selectors import Selector, selection_matches

STATUS_ONLY_CURRENT = "only-current"
STATUS_ONLY_PACKAGE = "only-package"
STATUS_DIFFERS = "differs"
STATUS_IN_SYNC = "in-sync"

# Statuses shown to humans in the printed report.
_HUMAN_STATUS = {
    STATUS_ONLY_CURRENT: "only on current",
    STATUS_ONLY_PACKAGE: "only in package",
    STATUS_DIFFERS: "differs",
    STATUS_IN_SYNC: "in sync",
}


@dataclass
class DiffEntry:
    client: str
    provider: str | None  # None = client-level (unused in this project, reserved)
    model: str | None  # None = provider-level or credential entry
    kind: str  # "provider" | "model" | "credential"
    status: str
    detail: str | None = None


@dataclass
class DiffReport:
    package_path: str
    source_machine: str | None
    exported_at: str | None
    # Map client_id -> display config path (e.g. "~/.config/opencode/opencode.json").
    # Populated from whichever side exposes the client (current side preferred).
    client_paths: dict[str, str] = field(default_factory=dict)
    entries: list[DiffEntry] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        tally = {STATUS_ONLY_CURRENT: 0, STATUS_ONLY_PACKAGE: 0, STATUS_DIFFERS: 0, STATUS_IN_SYNC: 0}
        for entry in self.entries:
            tally[entry.status] = tally.get(entry.status, 0) + 1
        return tally


def diff_package(
    *,
    input_path: str,
    home: str | None = None,
    selectors: list[Selector] | None = None,
    passphrase: str | None = None,
) -> DiffReport:
    """Compare the current machine's config against an export package file.

    Symmetric diff: for every client/provider/model present on either side,
    report whether it is only-current, only-package, in-sync, or differs.
    Never writes any files and never prints secret values.
    """
    selectors = selectors or []
    current_clients, current_creds = scan(home)
    pkg_clients, pkg_creds, raw = load_export_package(input_path, passphrase)

    current_clients = _filter_clients(current_clients, selectors)
    pkg_clients = _filter_clients(pkg_clients, selectors)

    # Build a client_id -> config_path map (prefer current side).
    client_paths: dict[str, str] = {}
    for client in current_clients:
        client_paths.setdefault(client.client, client.config_path)
    for client in pkg_clients:
        client_paths.setdefault(client.client, client.config_path)

    entries: list[DiffEntry] = []
    current_by_id = {c.client: c for c in current_clients}
    pkg_by_id = {c.client: c for c in pkg_clients}

    for client_id in sorted(set(current_by_id) | set(pkg_by_id)):
        cur_c = current_by_id.get(client_id)
        pkg_c = pkg_by_id.get(client_id)
        cur_providers = {p.provider_id: p for p in (cur_c.providers if cur_c else [])}
        pkg_providers = {p.provider_id: p for p in (pkg_c.providers if pkg_c else [])}

        for provider_id in sorted(set(cur_providers) | set(pkg_providers)):
            cur_p = cur_providers.get(provider_id)
            pkg_p = pkg_providers.get(provider_id)

            if cur_p and not pkg_p:
                entries.append(DiffEntry(client_id, provider_id, None, "provider", STATUS_ONLY_CURRENT))
                continue
            if pkg_p and not cur_p:
                entries.append(DiffEntry(client_id, provider_id, None, "provider", STATUS_ONLY_PACKAGE))
                continue
            # Both sides have the provider (the two early returns above guarantee non-None).
            assert cur_p is not None and pkg_p is not None

            # Compare provider-level fields.
            provider_diffs = _compare_provider_fields(cur_p, pkg_p)
            if provider_diffs:
                entries.append(
                    DiffEntry(client_id, provider_id, None, "provider", STATUS_DIFFERS, detail="; ".join(provider_diffs))
                )
            else:
                entries.append(DiffEntry(client_id, provider_id, None, "provider", STATUS_IN_SYNC))

            # Models (union by model_id).
            cur_models = {m.model_id: m for m in cur_p.models}
            pkg_models = {m.model_id: m for m in pkg_p.models}
            for model_id in sorted(set(cur_models) | set(pkg_models)):
                cur_m = cur_models.get(model_id)
                pkg_m = pkg_models.get(model_id)
                if cur_m and not pkg_m:
                    entries.append(DiffEntry(client_id, provider_id, model_id, "model", STATUS_ONLY_CURRENT))
                    continue
                if pkg_m and not cur_m:
                    entries.append(DiffEntry(client_id, provider_id, model_id, "model", STATUS_ONLY_PACKAGE))
                    continue
                assert cur_m is not None and pkg_m is not None
                model_diffs = _compare_model_fields(cur_m, pkg_m)
                if model_diffs:
                    entries.append(
                        DiffEntry(client_id, provider_id, model_id, "model", STATUS_DIFFERS, detail="; ".join(model_diffs))
                    )
                else:
                    entries.append(DiffEntry(client_id, provider_id, model_id, "model", STATUS_IN_SYNC))

            # Credential (one entry per provider when a credential_ref exists on either side).
            cur_ref = cur_p.credential_ref
            pkg_ref = pkg_p.credential_ref
            ref = cur_ref or pkg_ref
            if ref:
                cur_has = current_creds.has_secret_for(cur_ref)
                pkg_has = pkg_creds.has_secret_for(pkg_ref)
                if cur_has and pkg_has:
                    # has_secret_for guarantees non-None ref on the corresponding side.
                    assert cur_ref is not None and pkg_ref is not None
                    if current_creds.secrets[cur_ref] == pkg_creds.secrets[pkg_ref]:
                        entries.append(DiffEntry(client_id, provider_id, None, "credential", STATUS_IN_SYNC))
                    else:
                        # NEVER include the actual secret values.
                        entries.append(
                            DiffEntry(client_id, provider_id, None, "credential", STATUS_DIFFERS, detail="values differ")
                        )
                elif cur_has and not pkg_has:
                    entries.append(DiffEntry(client_id, provider_id, None, "credential", STATUS_ONLY_CURRENT))
                elif pkg_has and not cur_has:
                    entries.append(DiffEntry(client_id, provider_id, None, "credential", STATUS_ONLY_PACKAGE))
                # Neither side has the secret: emit nothing.

    return DiffReport(
        package_path=str(input_path),
        source_machine=raw.get("source_machine"),
        exported_at=raw.get("exported_at"),
        client_paths=client_paths,
        entries=entries,
    )


def _filter_clients(clients: list[ClientConfig], selectors: list[Selector]) -> list[ClientConfig]:
    """Apply selector filtering mirroring build_export_package semantics."""
    if not selectors:
        return clients
    selected: list[ClientConfig] = []
    for client in clients:
        if not any(s.client == client.client for s in selectors):
            continue
        providers: list[ProviderConfig] = []
        for provider in client.providers:
            if not _provider_matches(selectors, client.client, provider.provider_id):
                continue
            models = [
                m for m in provider.models if selection_matches(selectors, client.client, provider.provider_id, m.model_id)
            ]
            has_model_selector = any(
                s.client == client.client and s.provider == provider.provider_id and s.model is not None
                for s in selectors
            )
            if has_model_selector and not models:
                continue
            providers.append(replace(provider, models=models))
        if providers:
            selected.append(replace(client, providers=providers))
    return selected


def _provider_matches(selectors: list[Selector], client_id: str, provider_id: str) -> bool:
    if not selectors:
        return True
    return any(s.client == client_id and (s.provider is None or s.provider == provider_id) for s in selectors)


def _compare_provider_fields(cur: ProviderConfig, pkg: ProviderConfig) -> list[str]:
    diffs: list[str] = []
    for field_name in ("base_url", "provider_type", "display_name"):
        cv = getattr(cur, field_name)
        pv = getattr(pkg, field_name)
        if cv != pv:
            diffs.append(f"{field_name}: current={_truncate(cv)} vs package={_truncate(pv)}")
    return diffs


def _compare_model_fields(cur: ModelConfig, pkg: ModelConfig) -> list[str]:
    diffs: list[str] = []
    # model_id is the union key so it is always equal; compare the meaningful payload fields.
    for field_name in ("display_name", "context_limit", "output_limit", "raw"):
        cv = getattr(cur, field_name)
        pv = getattr(pkg, field_name)
        if cv != pv:
            diffs.append(f"{field_name}: current={_truncate(cv)} vs package={_truncate(pv)}")
    return diffs


def _truncate(value: Any, max_len: int = 60) -> str:
    """Render a value with repr, truncating to at most max_len characters."""
    rendered = repr(value)
    if len(rendered) <= max_len:
        return rendered
    # Use ASCII "..." so the marker is console-safe on Windows shells.
    return rendered[: max_len - 3] + "..."
