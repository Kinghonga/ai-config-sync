from __future__ import annotations

from pathlib import Path

from ai_config_sync.adapters import ADAPTERS
from ai_config_sync.export_package import load_export_package
from ai_config_sync.models import ImportReport
from ai_config_sync.selectors import Selector


def import_package(*, input_path: str | Path, home: str | Path | None = None, selectors: list[Selector] | None = None, dry_run: bool = False, force: bool = False, update: bool = False, passphrase: str | None = None) -> ImportReport:
    clients, credentials, _ = load_export_package(input_path, passphrase)
    adapters = {adapter_cls.client_id: adapter_cls(home) for adapter_cls in ADAPTERS}
    report = ImportReport()
    selectors = selectors or []
    for client in clients:
        if selectors and not any(selector.client == client.client for selector in selectors):
            continue
        adapter = adapters.get(client.client)
        if adapter is None:
            report.skipped.append(f"{client.client} unsupported client")
            continue
        report.merge(adapter.merge(client, credentials, selectors=selectors, dry_run=dry_run, force=force, update=update))
    return report
