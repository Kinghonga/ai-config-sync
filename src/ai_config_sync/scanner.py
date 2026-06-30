from __future__ import annotations

from pathlib import Path

from ai_config_sync.adapters import ADAPTERS
from ai_config_sync.models import ClientConfig, CredentialBundle


def scan(home: str | Path | None = None) -> tuple[list[ClientConfig], CredentialBundle]:
    clients: list[ClientConfig] = []
    merged_credentials: dict[str, dict] = {}
    for adapter_cls in ADAPTERS:
        client, credentials = adapter_cls(home).read()
        if client is not None:
            clients.append(client)
        merged_credentials.update(credentials.secrets)
    return clients, CredentialBundle(merged_credentials)
