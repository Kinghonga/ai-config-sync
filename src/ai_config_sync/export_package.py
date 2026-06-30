from __future__ import annotations

import json
import socket
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_config_sync.crypto import decrypt_credentials, encrypt_credentials
from ai_config_sync.models import ClientConfig, CredentialBundle
from ai_config_sync.scanner import scan
from ai_config_sync.selectors import Selector, selection_matches

SCHEMA = "ai-config-sync.v1"
VERSION = 1


def build_export_package(*, home: str | Path | None = None, selectors: list[Selector] | None = None, include_credentials: bool = True, passphrase: str | None = None) -> dict[str, Any]:
    clients, credentials = scan(home)
    selectors = selectors or []
    selected_clients: list[ClientConfig] = []
    selected_secret_refs: set[str] = set()
    for client in clients:
        providers = []
        for provider in client.providers:
            if selectors and not any(selector.client == client.client and (selector.provider is None or selector.provider == provider.provider_id) for selector in selectors):
                continue
            provider_copy = deepcopy(provider)
            provider_copy.models = [m for m in provider.models if selection_matches(selectors, client.client, provider.provider_id, m.model_id)]
            has_model_selector = any(selector.client == client.client and selector.provider == provider.provider_id and selector.model is not None for selector in selectors)
            if has_model_selector and not provider_copy.models:
                continue
            if isinstance(provider_copy.raw.get("models"), dict):
                provider_copy.raw["models"] = {model.model_id: deepcopy(model.raw) for model in provider_copy.models}
            if provider.credential_ref and credentials.has_secret_for(provider.credential_ref) and include_credentials:
                selected_secret_refs.add(provider.credential_ref)
                provider_copy.credentials_omitted = False
            elif provider.credential_ref and credentials.has_secret_for(provider.credential_ref) and not include_credentials:
                provider_copy.credentials_omitted = True
            providers.append(provider_copy)
        if providers:
            selected_clients.append(ClientConfig(client.client, client.config_path, providers))
    selected_credentials = {ref: credentials.secrets[ref] for ref in selected_secret_refs}
    if selected_credentials:
        if not passphrase:
            raise ValueError("passphrase is required when exporting credentials")
        encrypted_credentials = encrypt_credentials(selected_credentials, passphrase)
    else:
        encrypted_credentials = None
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_machine": socket.gethostname(),
        "clients": [client.to_dict() for client in selected_clients],
        "encrypted_credentials": encrypted_credentials,
    }


def write_export_package(package: dict[str, Any], output: str | Path) -> None:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(package, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def load_export_package(input_path: str | Path, passphrase: str | None = None) -> tuple[list[ClientConfig], CredentialBundle, dict[str, Any]]:
    path = Path(input_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_export_package(data)
    credentials = decrypt_credentials(data.get("encrypted_credentials"), passphrase) if data.get("encrypted_credentials") else {}
    clients = [ClientConfig.from_dict(c) for c in data.get("clients", [])]
    return clients, CredentialBundle(credentials), data


def validate_export_package(data: dict[str, Any]) -> None:
    if data.get("schema") != SCHEMA:
        raise ValueError(f"unsupported schema: {data.get('schema')}")
    if data.get("version") != VERSION:
        raise ValueError(f"unsupported version: {data.get('version')}")
    if not isinstance(data.get("clients"), list):
        raise ValueError("export package clients must be a list")
    if "encrypted_credentials" not in data:
        raise ValueError("export package missing encrypted_credentials")
