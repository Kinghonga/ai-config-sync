#!/usr/bin/env python3
"""ai-sync — AI model config migrator. Single-file, zero external dependencies.

Note: This standalone is a zero-dependency fallback that may lag the pip version. For `diff` and `--update` commands, install via `pip install ai-config-sync`.

Usage:
    ai-sync export                                      # export all to ai-sync.json
    ai-sync export --include opencode:sense-nova        # selective export
    ai-sync export --no-credentials                     # skip API keys
    ai-sync import                                      # import from ai-sync.json
    ai-sync import --dry-run                            # preview only
    ai-sync import --force                              # overwrite existing
    ai-sync import --yes                                # skip confirmation (automation)
    ai-sync list                                        # show detected AI tool configs
"""

from __future__ import annotations
import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import platform
import socket
import sys
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Constants ────────────────────────────────────────────────────────────────
__version__ = "0.2.0"
DEFAULT_PACKAGE_FILE = "ai-sync.json"

# Standalone crypto (stdlib only — less throughput than AES-GCM, identical
# security margin for short secrets like API keys)
_CRYPTO_ALGORITHM = "xor-hmac-sha256"
_CRYPTO_KDF = "pbkdf2-sha256"
_CRYPTO_ITERATIONS = 600_000
_CRYPTO_SALT_BYTES = 16
_CRYPTO_NONCE_BYTES = 8
_CRYPTO_HMAC_KEY_BYTES = 32
_CRYPTO_STREAM_KEY_BYTES = 32
_CRYPTO_DERIVED_LENGTH = _CRYPTO_HMAC_KEY_BYTES + _CRYPTO_STREAM_KEY_BYTES


# ── Crypto (stdlib-only replacement for cryptography) ──────────────────────

def _b64e(v: bytes) -> str:
    return base64.b64encode(v).decode("ascii")


def _b64d(v: str) -> bytes:
    return base64.b64decode(v.encode("ascii"))


def _derive_keys(passphrase: str, salt: bytes) -> tuple[bytes, bytes]:
    raw = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, _CRYPTO_ITERATIONS, dklen=_CRYPTO_DERIVED_LENGTH)
    return raw[:_CRYPTO_HMAC_KEY_BYTES], raw[_CRYPTO_HMAC_KEY_BYTES:]


def _xor_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """XOR encrypt using a keystream derived from SHA256(key || counter)."""
    out = bytearray()
    counter = 0
    while len(out) < len(plaintext):
        block = hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
        need = min(len(block), len(plaintext) - len(out))
        for i in range(need):
            out.append(plaintext[len(out)] ^ block[i])
        counter += 1
    return bytes(out)


def encrypt_credentials(credentials: dict[str, Any], passphrase: str) -> dict[str, Any]:
    salt = os.urandom(_CRYPTO_SALT_BYTES)
    nonce = os.urandom(_CRYPTO_NONCE_BYTES)
    hmac_key, stream_key = _derive_keys(passphrase, salt)
    plaintext = json.dumps(credentials, sort_keys=True, separators=(",", ":")).encode("utf-8")
    # Mix nonce into keystream so same credentials + passphrase produce different ciphertexts
    mixed_stream = hashlib.sha256(stream_key + nonce).digest() + stream_key
    ciphertext = _xor_encrypt(plaintext, mixed_stream)
    tag = hmac.new(hmac_key, ciphertext, "sha256").hexdigest()
    return {
        "algorithm": _CRYPTO_ALGORITHM,
        "kdf": _CRYPTO_KDF,
        "iterations": _CRYPTO_ITERATIONS,
        "salt": _b64e(salt),
        "nonce": _b64e(nonce),
        "tag": tag,
        "ciphertext": _b64e(ciphertext),
    }


def decrypt_credentials(encrypted: dict[str, Any] | None, passphrase: str | None) -> dict[str, Any]:
    if encrypted is None:
        return {}
    if not passphrase:
        raise ValueError("passphrase is required to decrypt credentials")
    algorithm = encrypted.get("algorithm")
    if algorithm != _CRYPTO_ALGORITHM:
        if algorithm == "aes-256-gcm":
            raise ValueError(
                "This package was exported with the pip version (AES-256-GCM). "
                "The standalone script cannot decrypt it. "
                "Install the pip version: pip install ai-config-sync, "
                "or re-export using the standalone script on the source machine.")
        raise ValueError(f"unsupported credential encryption algorithm: {algorithm}")
    salt = _b64d(encrypted["salt"])
    nonce = _b64d(encrypted["nonce"])
    ciphertext = _b64d(encrypted["ciphertext"])
    tag_expected = encrypted.get("tag", "")
    hmac_key, stream_key = _derive_keys(passphrase, salt)
    tag_actual = hmac.new(hmac_key, ciphertext, "sha256").hexdigest()
    if not hmac.compare_digest(tag_expected, tag_actual):
        raise ValueError("could not decrypt credentials; check passphrase")
    mixed_stream = hashlib.sha256(stream_key + nonce).digest() + stream_key
    plaintext = _xor_encrypt(ciphertext, mixed_stream)
    return json.loads(plaintext.decode("utf-8"))


# ── Models ─────────────────────────────────────────────────────────────────

@dataclass
class ModelConfig:
    model_id: str
    display_name: str | None = None
    context_limit: int | None = None
    output_limit: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"model_id": self.model_id, "display_name": self.display_name,
                "context_limit": self.context_limit, "output_limit": self.output_limit, "raw": self.raw}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelConfig":
        return cls(model_id=data["model_id"], display_name=data.get("display_name"),
                   context_limit=data.get("context_limit"), output_limit=data.get("output_limit"),
                   raw=data.get("raw") or {})


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
        return {"provider_id": self.provider_id, "display_name": self.display_name,
                "provider_type": self.provider_type, "base_url": self.base_url,
                "credential_ref": self.credential_ref, "credentials_omitted": self.credentials_omitted,
                "models": [m.to_dict() for m in self.models], "raw": self.raw}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProviderConfig":
        return cls(provider_id=data["provider_id"], display_name=data.get("display_name"),
                   provider_type=data.get("provider_type") or "unknown", base_url=data.get("base_url"),
                   credential_ref=data.get("credential_ref"),
                   credentials_omitted=bool(data.get("credentials_omitted", False)),
                   models=[ModelConfig.from_dict(m) for m in data.get("models", [])],
                   raw=data.get("raw") or {})


@dataclass
class ClientConfig:
    client: str
    config_path: str
    providers: list[ProviderConfig] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"client": self.client, "config_path": self.config_path,
                "providers": [p.to_dict() for p in self.providers]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClientConfig":
        return cls(client=data["client"], config_path=data["config_path"],
                   providers=[ProviderConfig.from_dict(p) for p in data.get("providers", [])])


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


# ── Selectors ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Selector:
    client: str
    provider: str | None = None
    model: str | None = None

    def matches(self, client: str, provider: str | None = None, model: str | None = None) -> bool:
        if self.client != client:
            return False
        if self.provider is not None and (provider is None or self.provider != provider):
            return False
        if self.model is not None and (model is None or self.model != model):
            return False
        return True


def parse_selector(value: str) -> Selector:
    if not value:
        raise ValueError("selector must not be empty")
    parts = value.split(":")
    if len(parts) > 3:
        raise ValueError(f"invalid selector '{value}': expected client, client:provider, or client:provider:model")
    if any(p == "" for p in parts):
        raise ValueError(f"invalid selector '{value}': selector IDs must not be empty")
    return Selector(client=parts[0], provider=parts[1] if len(parts) >= 2 else None,
                    model=parts[2] if len(parts) == 3 else None)


def parse_selectors(values: list[str] | None) -> list[Selector]:
    return [parse_selector(v) for v in (values or [])]


def selection_matches(selectors: list[Selector], client: str, provider: str | None = None, model: str | None = None) -> bool:
    if not selectors:
        return True
    return any(s.matches(client, provider, model) for s in selectors)


# ── JSON utility ───────────────────────────────────────────────────────────

def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def backup_and_atomic_write(path: Path, data: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = ""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    if path.exists():
        bk = path.with_name(path.name + f".bak.{ts}")
        bk.write_bytes(path.read_bytes())
        backup = str(bk)
    rendered = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    json.loads(rendered)  # validate
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(rendered, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return backup


def without_keys(data: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in keys}


# ── Adapter base ───────────────────────────────────────────────────────────

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
        ...

    @abstractmethod
    def merge(self, incoming: ClientConfig, credentials: CredentialBundle, *,
              selectors: list[Any], dry_run: bool = False, force: bool = False) -> ImportReport:
        ...


# ── OpenCode adapter ──────────────────────────────────────────────────────

_SECRET_FIELDS = {"apiKey", "api_key", "token", "authToken", "authorization"}


class OpenCodeAdapter(ClientAdapter):
    client_id = "opencode"
    config_relpath = ".config/opencode/opencode.json"

    def read(self) -> tuple[ClientConfig | None, CredentialBundle]:
        path = self.config_path
        if not path.exists():
            return None, CredentialBundle()
        data = read_json(path)
        ps = data.get("provider") or {}
        if not isinstance(ps, dict):
            return ClientConfig(self.client_id, self.display_config_path, []), CredentialBundle()
        providers: list[ProviderConfig] = []
        creds: dict[str, dict[str, Any]] = {}
        for pid, pd in ps.items():
            if not isinstance(pd, dict):
                continue
            opts = pd.get("options") or {}
            if not isinstance(opts, dict):
                opts = {}
            sv = {k: deepcopy(v) for k, v in opts.items() if k in _SECRET_FIELDS}
            cr = f"{self.client_id}:{pid}" if sv else None
            if cr:
                creds[cr] = {"options": sv}
            models = []
            ms = pd.get("models") or {}
            if isinstance(ms, dict):
                for mid, md in ms.items():
                    if not isinstance(md, dict):
                        md = {}
                    lim = md.get("limit") or {}
                    if not isinstance(lim, dict):
                        lim = {}
                    models.append(ModelConfig(model_id=mid,
                                              display_name=md.get("name") or md.get("displayName") or md.get("display_name"),
                                              context_limit=lim.get("context"), output_limit=lim.get("output"),
                                              raw=deepcopy(md)))
            npm = pd.get("npm")
            ptype = "openai-compatible" if npm == "@ai-sdk/openai-compatible" else "unknown"
            safe_opts = without_keys(opts, _SECRET_FIELDS)
            raw = deepcopy(pd)
            raw["options"] = safe_opts
            providers.append(ProviderConfig(provider_id=pid, display_name=pd.get("name") or pd.get("displayName") or pd.get("display_name"),
                                            provider_type=ptype, base_url=opts.get("baseURL") or opts.get("base_url"),
                                            credential_ref=cr, credentials_omitted=False, models=models, raw=raw))
        return ClientConfig(self.client_id, self.display_config_path, providers), CredentialBundle(creds)

    def merge(self, incoming: ClientConfig, credentials: CredentialBundle, *,
              selectors: list[Any], dry_run: bool = False, force: bool = False) -> ImportReport:
        report = ImportReport()
        path = self.config_path
        file_existed = path.exists()
        if not file_existed:
            data = {"$schema": "https://opencode.ai/config.json"}
        else:
            data = read_json(path)
        original = deepcopy(data)
        ps = data.setdefault("provider", {})
        if not isinstance(ps, dict):
            ps = {}
            data["provider"] = ps
        for provider in incoming.providers:
            if selectors and not any(s.client == self.client_id and (s.provider is None or s.provider == provider.provider_id) for s in selectors):
                continue
            sel_models = [m for m in provider.models if selection_matches(selectors, self.client_id, provider.provider_id, m.model_id)]
            has_model_sel = any(s.client == self.client_id and s.provider == provider.provider_id and s.model is not None for s in selectors)
            if has_model_sel and not sel_models:
                continue
            exists = provider.provider_id in ps and isinstance(ps.get(provider.provider_id), dict)
            new_prov = not exists
            if exists:
                dp = ps[provider.provider_id]
                report.skipped.append(f"{self.client_id}:{provider.provider_id} provider exists")
            else:
                dp = deepcopy(provider.raw) if provider.raw else {}
                dp.setdefault("models", {})
                if has_model_sel and isinstance(dp.get("models"), dict):
                    dp["models"] = {m.model_id: deepcopy(m.raw) if m.raw else _model_to_raw(m) for m in sel_models}
                ps[provider.provider_id] = dp
                report.added.append(f"{self.client_id}:{provider.provider_id}")
            if force or new_prov:
                if provider.raw:
                    np = deepcopy(provider.raw)
                    ex_m = deepcopy(dp.get("models")) if isinstance(dp.get("models"), dict) else {}
                    ex_o = deepcopy(dp.get("options")) if isinstance(dp.get("options"), dict) else {}
                    inc_o = deepcopy(np.get("options")) if isinstance(np.get("options"), dict) else {}
                    inc_o.update({k: v for k, v in ex_o.items() if k in _SECRET_FIELDS})
                    np["options"] = inc_o
                    if force:
                        np["models"] = deepcopy(np.get("models")) if isinstance(np.get("models"), dict) else {}
                    else:
                        np["models"] = ex_m
                    ps[provider.provider_id] = np
                    dp = ps[provider.provider_id]
                    if force and exists:
                        report.updated.append(f"{self.client_id}:{provider.provider_id} provider")
                if provider.base_url:
                    dp.setdefault("options", {})
                    key = "baseURL" if "baseURL" in (provider.raw.get("options", {}) if provider.raw else {}) else "base_url"
                    dp["options"][key] = provider.base_url
            dest_m = dp.setdefault("models", {})
            if not isinstance(dest_m, dict):
                dest_m = {}
                dp["models"] = dest_m
            for model in sel_models:
                me = model.model_id in dest_m
                if me and new_prov:
                    continue
                if me and not force:
                    report.conflicts.append(f"{self.client_id}:{provider.provider_id}:{model.model_id} model exists")
                    continue
                dest_m[model.model_id] = deepcopy(model.raw) if model.raw else _model_to_raw(model)
                if me:
                    report.updated.append(f"{self.client_id}:{provider.provider_id}:{model.model_id}")
                else:
                    report.added.append(f"{self.client_id}:{provider.provider_id}:{model.model_id}")
            if provider.credential_ref:
                if credentials.has_secret_for(provider.credential_ref):
                    report.credentials_present.append(provider.credential_ref)
                    sec = credentials.secrets[provider.credential_ref].get("options", {})
                    do = dp.setdefault("options", {})
                    for k, v in sec.items():
                        if k in do and not force:
                            report.conflicts.append(f"{provider.credential_ref} credential field exists")
                            continue
                        do[k] = v
                        report.updated.append(f"{provider.credential_ref} credential")
                else:
                    report.credentials_omitted.append(provider.credential_ref)
        if data != original:
            report.changed_files.add(str(path))
            if not file_existed:
                report.created_files.add(str(path))
            if not dry_run:
                bk = backup_and_atomic_write(path, data)
                if bk:
                    report.backups.append(bk)
        return report


def _model_to_raw(model: ModelConfig) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    if model.display_name:
        raw["name"] = model.display_name
    lim: dict[str, Any] = {}
    if model.context_limit is not None:
        lim["context"] = model.context_limit
    if model.output_limit is not None:
        lim["output"] = model.output_limit
    if lim:
        raw["limit"] = lim
    return raw


# ── Claude Code adapter ───────────────────────────────────────────────────

_SECRET_ENV_KEYS = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
_MODEL_ENV_KEYS = ["ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
                   "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
                   "ANTHROPIC_DEFAULT_SONNET_MODEL"]
_BASE_URL_KEY = "ANTHROPIC_BASE_URL"
_CC_PROVIDER_ID = "anthropic-env"


class ClaudeCodeAdapter(ClientAdapter):
    client_id = "claude-code"
    config_relpath = ".claude/settings.json"

    def read(self) -> tuple[ClientConfig | None, CredentialBundle]:
        path = self.config_path
        if not path.exists():
            return None, CredentialBundle()
        data = read_json(path)
        env = data.get("env") or {}
        if not isinstance(env, dict):
            env = {}
        sv = {k: deepcopy(v) for k, v in env.items() if k in _SECRET_ENV_KEYS}
        cr = f"{self.client_id}:{_CC_PROVIDER_ID}" if sv else None
        creds = {cr: {"env": sv}} if cr else {}
        models = []
        for key in _MODEL_ENV_KEYS:
            mid = env.get(key)
            if not mid:
                continue
            dn = env.get(f"{key}_NAME") or env.get(f"{key}_MODEL_NAME")
            models.append(ModelConfig(model_id=mid, display_name=dn,
                                      raw={"env_key": key, "name_key": f"{key}_NAME", "alt_name_key": f"{key}_MODEL_NAME"}))
        safe_keys = {_BASE_URL_KEY, *_MODEL_ENV_KEYS, *(f"{k}_NAME" for k in _MODEL_ENV_KEYS), *(f"{k}_MODEL_NAME" for k in _MODEL_ENV_KEYS)}
        safe_env = without_keys({k: deepcopy(v) for k, v in env.items() if k in safe_keys}, _SECRET_ENV_KEYS)
        provider = ProviderConfig(provider_id=_CC_PROVIDER_ID, display_name="Claude Code Anthropic Env",
                                  provider_type="anthropic-compatible", base_url=env.get(_BASE_URL_KEY),
                                  credential_ref=cr, credentials_omitted=False, models=models, raw={"env": safe_env})
        return ClientConfig(self.client_id, self.display_config_path, [provider]), CredentialBundle(creds)

    def merge(self, incoming: ClientConfig, credentials: CredentialBundle, *,
              selectors: list[Any], dry_run: bool = False, force: bool = False) -> ImportReport:
        report = ImportReport()
        path = self.config_path
        file_existed = path.exists()
        if not file_existed:
            data = {"env": {}}
        else:
            data = read_json(path)
        original = deepcopy(data)
        env = data.setdefault("env", {})
        if not isinstance(env, dict):
            env = {}
            data["env"] = env
        for provider in incoming.providers:
            if provider.provider_id != _CC_PROVIDER_ID or (selectors and not any(
                    s.client == self.client_id and (s.provider is None or s.provider == provider.provider_id) for s in selectors)):
                continue
            raw_env = deepcopy((provider.raw or {}).get("env") or {})
            for key in [_BASE_URL_KEY]:
                if key in raw_env:
                    if key in env and not force:
                        report.skipped.append(f"{self.client_id}:{_CC_PROVIDER_ID} {key} exists")
                    else:
                        env[key] = raw_env[key]
                        report.updated.append(f"{self.client_id}:{_CC_PROVIDER_ID} {key}")
            for model in provider.models:
                if not selection_matches(selectors, self.client_id, _CC_PROVIDER_ID, model.model_id):
                    continue
                ek = (model.raw or {}).get("env_key") or _first_avail(env)
                nk = (model.raw or {}).get("name_key") or f"{ek}_NAME"
                me = ek in env
                if me and not force:
                    report.conflicts.append(f"{self.client_id}:{_CC_PROVIDER_ID}:{model.model_id} model env exists")
                    continue
                env[ek] = model.model_id
                if model.display_name:
                    env[nk] = model.display_name
                if me:
                    report.updated.append(f"{self.client_id}:{_CC_PROVIDER_ID}:{model.model_id}")
                else:
                    report.added.append(f"{self.client_id}:{_CC_PROVIDER_ID}:{model.model_id}")
            if provider.credential_ref:
                if credentials.has_secret_for(provider.credential_ref):
                    report.credentials_present.append(provider.credential_ref)
                    sec = credentials.secrets[provider.credential_ref].get("env", {})
                    for k, v in sec.items():
                        if k in env and not force:
                            report.conflicts.append(f"{provider.credential_ref} credential field exists")
                            continue
                        env[k] = v
                        report.updated.append(f"{provider.credential_ref} credential")
                else:
                    report.credentials_omitted.append(provider.credential_ref)
        if data != original:
            report.changed_files.add(str(path))
            if not file_existed:
                report.created_files.add(str(path))
            if not dry_run:
                bk = backup_and_atomic_write(path, data)
                if bk:
                    report.backups.append(bk)
        return report


def _first_avail(env: dict[str, Any]) -> str:
    for k in _MODEL_ENV_KEYS:
        if k not in env:
            return k
    return _MODEL_ENV_KEYS[0]


# ── Scanner ────────────────────────────────────────────────────────────────

_ADAPTERS: list[type[ClientAdapter]] = [OpenCodeAdapter, ClaudeCodeAdapter]


def scan(home: str | Path | None = None) -> tuple[list[ClientConfig], CredentialBundle]:
    clients: list[ClientConfig] = []
    merged: dict[str, dict] = {}
    for cls in _ADAPTERS:
        c, creds = cls(home).read()
        if c is not None:
            clients.append(c)
        merged.update(creds.secrets)
    return clients, CredentialBundle(merged)


# ── Export package ─────────────────────────────────────────────────────────

_SCHEMA = "ai-config-sync.v1"
_PKG_VERSION = 1


def build_export_package(*, home: str | Path | None = None, selectors: list[Selector] | None = None,
                         include_credentials: bool = True, passphrase: str | None = None) -> dict[str, Any]:
    clients, credentials = scan(home)
    selectors = selectors or []
    selected_clients: list[ClientConfig] = []
    selected_refs: set[str] = set()
    for client in clients:
        providers = []
        for provider in client.providers:
            if selectors and not any(s.client == client.client and (s.provider is None or s.provider == provider.provider_id) for s in selectors):
                continue
            pc = deepcopy(provider)
            pc.models = [m for m in provider.models if selection_matches(selectors, client.client, provider.provider_id, m.model_id)]
            has_ms = any(s.client == client.client and s.provider == provider.provider_id and s.model is not None for s in selectors)
            if has_ms and not pc.models:
                continue
            if isinstance(pc.raw.get("models"), dict):
                pc.raw["models"] = {m.model_id: deepcopy(m.raw) for m in pc.models}
            if provider.credential_ref and credentials.has_secret_for(provider.credential_ref):
                if include_credentials:
                    selected_refs.add(provider.credential_ref)
                    pc.credentials_omitted = False
                else:
                    pc.credentials_omitted = True
            providers.append(pc)
        if providers:
            selected_clients.append(ClientConfig(client.client, client.config_path, providers))
    sel_creds = {r: credentials.secrets[r] for r in selected_refs}
    if sel_creds:
        if not passphrase:
            raise ValueError("passphrase is required when exporting credentials")
        encrypted = encrypt_credentials(sel_creds, passphrase)
    else:
        encrypted = None
    return {"schema": _SCHEMA, "version": _PKG_VERSION,
            "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source_machine": socket.gethostname(),
            "clients": [c.to_dict() for c in selected_clients],
            "encrypted_credentials": encrypted}


def write_export_package(pkg: dict[str, Any], output: str | Path) -> None:
    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(pkg, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def load_export_package(input_path: str | Path, passphrase: str | None = None) -> tuple[list[ClientConfig], CredentialBundle, dict[str, Any]]:
    p = Path(input_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("schema") != _SCHEMA:
        raise ValueError(f"unsupported schema: {data.get('schema')}")
    if data.get("version") != _PKG_VERSION:
        raise ValueError(f"unsupported version: {data.get('version')}")
    if not isinstance(data.get("clients"), list):
        raise ValueError("export package clients must be a list")
    if "encrypted_credentials" not in data:
        raise ValueError("export package missing encrypted_credentials")
    creds = decrypt_credentials(data.get("encrypted_credentials"), passphrase) if data.get("encrypted_credentials") else {}
    clients = [ClientConfig.from_dict(c) for c in data.get("clients", [])]
    return clients, CredentialBundle(creds), data


# ── Import package ─────────────────────────────────────────────────────────

def import_package(*, input_path: str | Path, home: str | Path | None = None,
                   selectors: list[Selector] | None = None, dry_run: bool = False,
                   force: bool = False, passphrase: str | None = None) -> ImportReport:
    clients, credentials, _ = load_export_package(input_path, passphrase)
    adapters = {cls.client_id: cls(home) for cls in _ADAPTERS}
    report = ImportReport()
    selectors = selectors or []
    for client in clients:
        if selectors and not any(s.client == client.client for s in selectors):
            continue
        adp = adapters.get(client.client)
        if adp is None:
            report.skipped.append(f"{client.client} unsupported client")
            continue
        report.merge(adp.merge(client, credentials, selectors=selectors, dry_run=dry_run, force=force))
    return report


# ── CLI ────────────────────────────────────────────────────────────────────

def resolve_passphrase(*, required: bool) -> str | None:
    env = os.environ.get("AI_SYNC_PASSPHRASE")
    if env:
        return env
    if required:
        if not sys.stdin.isatty():
            raise ValueError(
                "Passphrase required but no terminal available for interactive input. "
                "Set the AI_SYNC_PASSPHRASE environment variable for automation.")
        return getpass.getpass("Enter passphrase: ")
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai-sync",
                                description="AI model config migrator. Export from one machine, import on another.")
    p.add_argument("--version", action="version", version=f"ai-sync {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    lp = sub.add_parser("list", help="Show detected AI tool provider configs")
    lp.add_argument("--home")
    ep = sub.add_parser("export", help="Export provider config package")
    ep.add_argument("--output", default=DEFAULT_PACKAGE_FILE, help=f"Output file (default: {DEFAULT_PACKAGE_FILE})")
    ep.add_argument("--home")
    ep.add_argument("--include", action="append", default=[], help="Selector: client, client:provider, or client:provider:model")
    ep.add_argument("--no-credentials", action="store_true", help="Omit credentials from export")
    ip = sub.add_parser("import", help="Import provider config package")
    ip.add_argument("--input", default=DEFAULT_PACKAGE_FILE, help=f"Input file (default: {DEFAULT_PACKAGE_FILE})")
    ip.add_argument("--home")
    ip.add_argument("--include", action="append", default=[])
    ip.add_argument("--dry-run", action="store_true", help="Preview without writing")
    ip.add_argument("--force", action="store_true", help="Overwrite existing configs")
    ip.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    return p


def _cmd_list(args: argparse.Namespace) -> int:
    clients, _ = scan(args.home)
    if not clients:
        print("No supported AI tool configs found.")
        return 0
    for c in clients:
        print(f"{c.client} {c.config_path}")
        for p in c.providers:
            cs = "credentials: present" if p.credential_ref and not p.credentials_omitted else "credentials: none/omitted"
            print(f"  provider {p.provider_id} ({p.provider_type}) {cs}")
            for m in p.models:
                print(f"    model {m.model_id}")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    selectors = parse_selectors(args.include)
    incl_creds = not args.no_credentials
    pw = resolve_passphrase(required=incl_creds)
    pkg = build_export_package(home=args.home, selectors=selectors, include_credentials=incl_creds, passphrase=pw)
    write_export_package(pkg, args.output)
    cc = len(pkg["clients"])
    pc = sum(len(c.get("providers", [])) for c in pkg["clients"])
    mc = sum(len(p.get("models", [])) for c in pkg["clients"] for p in c.get("providers", []))
    cs = "credentials encrypted" if pkg["encrypted_credentials"] else "credentials omitted"
    print(f"Exported to {args.output}")
    print(f"{cc} clients | {pc} providers | {mc} models | {cs}")
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    selectors = parse_selectors(args.include)
    inp = args.input
    encrypted = False
    try:
        with Path(inp).open("r", encoding="utf-8") as fh:
            encrypted = json.load(fh).get("encrypted_credentials") is not None
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    pw = resolve_passphrase(required=encrypted)
    if args.dry_run:
        report = import_package(input_path=inp, home=args.home, selectors=selectors, dry_run=True, force=args.force, passphrase=pw)
        print("Dry run — changes previewed below (no files written):")
        _print_summary(report)
        return 0
    preview = import_package(input_path=inp, home=args.home, selectors=selectors, dry_run=True, force=args.force, passphrase=pw)
    if not args.yes:
        _print_summary(preview)
        ans = input("Apply changes? [Y/n] ").strip().lower()
        if ans not in ("", "y", "yes"):
            print("Aborted.")
            return 0
    report = import_package(input_path=inp, home=args.home, selectors=selectors, dry_run=False, force=args.force, passphrase=pw)
    print(f"Applied. Backups created: {len(report.backups)} files.")
    return 0


def _print_summary(report: ImportReport) -> None:
    print("Changes to apply:")
    print(f"  {len(report.added)} providers added | {len(report.updated)} updated | {len(report.skipped)} skipped | {len(report.conflicts)} conflict")
    print(f"  credentials: {len(report.credentials_present)} present (encrypted) | {len(report.credentials_omitted)} omitted")
    if report.changed_files:
        created = sorted(report.created_files)
        updated_f = sorted(f for f in report.changed_files if f not in report.created_files)
        lines = []
        for f in created:
            lines.append(f"  CREATE {f} (new file)")
        for f in updated_f:
            lines.append(f"  UPDATE {f}")
        for line in lines:
            print(line)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            return _cmd_list(args)
        if args.command == "export":
            return _cmd_export(args)
        if args.command == "import":
            return _cmd_import(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
