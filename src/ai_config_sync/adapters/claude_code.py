from __future__ import annotations

from copy import deepcopy
from typing import Any

from ai_config_sync.adapters._json import backup_and_atomic_write, read_json, without_keys
from ai_config_sync.adapters.base import ClientAdapter
from ai_config_sync.models import ClientConfig, CredentialBundle, ImportReport, ModelConfig, ProviderConfig
from ai_config_sync.selectors import selection_matches

SECRET_ENV_KEYS = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
MODEL_ENV_KEYS = [
    "ANTHROPIC_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
]
BASE_URL_KEY = "ANTHROPIC_BASE_URL"
PROVIDER_ID = "anthropic-env"


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
        secret_values = {k: deepcopy(v) for k, v in env.items() if k in SECRET_ENV_KEYS}
        credential_ref = f"{self.client_id}:{PROVIDER_ID}" if secret_values else None
        credentials = {credential_ref: {"env": secret_values}} if credential_ref else {}
        models: list[ModelConfig] = []
        for key in MODEL_ENV_KEYS:
            model_id = env.get(key)
            if not model_id:
                continue
            display_name = env.get(f"{key}_NAME") or env.get(f"{key}_MODEL_NAME")
            models.append(ModelConfig(model_id=model_id, display_name=display_name, raw={"env_key": key, "name_key": f"{key}_NAME", "alt_name_key": f"{key}_MODEL_NAME"}))
        safe_keys = {BASE_URL_KEY, *MODEL_ENV_KEYS, *(f"{key}_NAME" for key in MODEL_ENV_KEYS), *(f"{key}_MODEL_NAME" for key in MODEL_ENV_KEYS)}
        safe_env = without_keys({k: deepcopy(v) for k, v in env.items() if k in safe_keys}, SECRET_ENV_KEYS)
        provider = ProviderConfig(
            provider_id=PROVIDER_ID,
            display_name="Claude Code Anthropic Env",
            provider_type="anthropic-compatible",
            base_url=env.get(BASE_URL_KEY),
            credential_ref=credential_ref,
            credentials_omitted=False,
            models=models,
            raw={"env": safe_env},
        )
        return ClientConfig(self.client_id, self.display_config_path, [provider]), CredentialBundle(credentials)

    def merge(self, incoming: ClientConfig, credentials: CredentialBundle, *, selectors: list[Any], dry_run: bool = False, force: bool = False, update: bool = False) -> ImportReport:
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
            if provider.provider_id != PROVIDER_ID or (selectors and not any(selector.client == self.client_id and (selector.provider is None or selector.provider == provider.provider_id) for selector in selectors)):
                continue
            in_update_mode = update and not force
            raw_env = deepcopy((provider.raw or {}).get("env") or {})
            for key in [BASE_URL_KEY]:
                if key in raw_env:
                    if key in env and not force:
                        if in_update_mode:
                            if env[key] != raw_env[key]:
                                env[key] = raw_env[key]
                                report.updated.append(f"{self.client_id}:{PROVIDER_ID} {key}")
                        else:
                            report.skipped.append(f"{self.client_id}:{PROVIDER_ID} {key} exists")
                    else:
                        env[key] = raw_env[key]
                        report.updated.append(f"{self.client_id}:{PROVIDER_ID} {key}")
            for model in provider.models:
                if not selection_matches(selectors, self.client_id, PROVIDER_ID, model.model_id):
                    continue
                env_key = (model.raw or {}).get("env_key") or _first_available_model_key(env)
                name_key = (model.raw or {}).get("name_key") or f"{env_key}_NAME"
                exists = env_key in env
                if exists and not force:
                    if in_update_mode:
                        if env[env_key] != model.model_id:
                            env[env_key] = model.model_id
                            report.updated.append(f"{self.client_id}:{PROVIDER_ID}:{model.model_id}")
                        continue
                    report.conflicts.append(f"{self.client_id}:{PROVIDER_ID}:{model.model_id} model env exists")
                    continue
                env[env_key] = model.model_id
                if model.display_name:
                    env[name_key] = model.display_name
                if exists:
                    report.updated.append(f"{self.client_id}:{PROVIDER_ID}:{model.model_id}")
                else:
                    report.added.append(f"{self.client_id}:{PROVIDER_ID}:{model.model_id}")
            if provider.credential_ref:
                if credentials.has_secret_for(provider.credential_ref):
                    report.credentials_present.append(provider.credential_ref)
                    secret_env = credentials.secrets[provider.credential_ref].get("env", {})
                    for key, value in secret_env.items():
                        if key in env and not force:
                            if in_update_mode:
                                if env[key] != value:
                                    env[key] = value
                                    report.updated.append(f"{provider.credential_ref} credential")
                                continue
                            report.conflicts.append(f"{provider.credential_ref} credential field exists")
                            continue
                        env[key] = value
                        report.updated.append(f"{provider.credential_ref} credential")
                else:
                    report.credentials_omitted.append(provider.credential_ref)

        if data != original:
            report.changed_files.add(str(path))
            if not file_existed:
                report.created_files.add(str(path))
            if not dry_run:
                backup = backup_and_atomic_write(path, data)
                if backup:
                    report.backups.append(backup)
        return report


def _first_available_model_key(env: dict[str, Any]) -> str:
    for key in MODEL_ENV_KEYS:
        if key not in env:
            return key
    return MODEL_ENV_KEYS[0]
