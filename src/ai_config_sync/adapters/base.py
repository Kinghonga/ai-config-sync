from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ai_config_sync.models import ClientConfig, CredentialBundle, ImportReport


class ClientAdapter(ABC):
    client_id: str
    config_relpath: str

    def __init__(self, home: str | Path | None = None):
        self.home = Path(home).expanduser() if home is not None else Path.home()

    @property
    def config_path(self) -> Path:
        return self.home / self.config_relpath

    @property
    def display_config_path(self) -> str:
        return "~/" + self.config_relpath

    @abstractmethod
    def read(self) -> tuple[ClientConfig | None, CredentialBundle]:
        raise NotImplementedError

    @abstractmethod
    def merge(self, incoming: ClientConfig, credentials: CredentialBundle, *, selectors: list[Any], dry_run: bool = False, force: bool = False, update: bool = False) -> ImportReport:
        raise NotImplementedError
