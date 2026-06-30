from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelConfig:
    model_id: str
    display_name: str | None = None
    context_limit: int | None = None
    output_limit: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "display_name": self.display_name,
            "context_limit": self.context_limit,
            "output_limit": self.output_limit,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelConfig":
        return cls(
            model_id=data["model_id"],
            display_name=data.get("display_name"),
            context_limit=data.get("context_limit"),
            output_limit=data.get("output_limit"),
            raw=data.get("raw") or {},
        )


@dataclass
class ProviderConfig:
    provider_id: str
    display_name: str | None = None
    provider_type: str = "unknown"
    base_url: str | None = None
    credential_ref: str | None = None
    credentials_omitted: bool = False
    models: list[ModelConfig] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "provider_type": self.provider_type,
            "base_url": self.base_url,
            "credential_ref": self.credential_ref,
            "credentials_omitted": self.credentials_omitted,
            "models": [m.to_dict() for m in self.models],
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderConfig":
        return cls(
            provider_id=data["provider_id"],
            display_name=data.get("display_name"),
            provider_type=data.get("provider_type") or "unknown",
            base_url=data.get("base_url"),
            credential_ref=data.get("credential_ref"),
            credentials_omitted=bool(data.get("credentials_omitted", False)),
            models=[ModelConfig.from_dict(m) for m in data.get("models", [])],
            raw=data.get("raw") or {},
        )


@dataclass
class ClientConfig:
    client: str
    config_path: str
    providers: list[ProviderConfig] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "client": self.client,
            "config_path": self.config_path,
            "providers": [p.to_dict() for p in self.providers],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClientConfig":
        return cls(
            client=data["client"],
            config_path=data["config_path"],
            providers=[ProviderConfig.from_dict(p) for p in data.get("providers", [])],
        )


@dataclass
class CredentialBundle:
    secrets: dict[str, dict[str, Any]] = field(default_factory=dict)

    def has_secret_for(self, credential_ref: str | None) -> bool:
        return bool(credential_ref and credential_ref in self.secrets and self.secrets[credential_ref])


@dataclass
class ImportReport:
    changed_files: set[str] = field(default_factory=set)
    created_files: set[str] = field(default_factory=set)
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    credentials_present: list[str] = field(default_factory=list)
    credentials_omitted: list[str] = field(default_factory=list)
    backups: list[str] = field(default_factory=list)

    def merge(self, other: "ImportReport") -> None:
        self.changed_files.update(other.changed_files)
        self.created_files.update(other.created_files)
        self.added.extend(other.added)
        self.updated.extend(other.updated)
        self.skipped.extend(other.skipped)
        self.conflicts.extend(other.conflicts)
        self.credentials_present.extend(other.credentials_present)
        self.credentials_omitted.extend(other.credentials_omitted)
        self.backups.extend(other.backups)
