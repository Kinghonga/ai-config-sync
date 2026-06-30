from __future__ import annotations

from copy import deepcopy
from typing import Any

from ai_config_sync.adapters._json import backup_and_atomic_write, read_json, without_keys
from ai_config_sync.adapters.base import ClientAdapter
from ai_config_sync.models import ClientConfig, CredentialBundle, ImportReport, ModelConfig, ProviderConfig
from ai_config_sync.selectors import selection_matches

SECRET_FIELDS = {"apiKey", "api_key", "token", "authToken", "authorization"}


class OpenCodeAdapter(ClientAdapter):
    client_id = "opencode"
    config_relpath = ".config/opencode/opencode.json"

    def read(self) -> tuple[ClientConfig | None, CredentialBundle]:
        path = self.config_path
        if not path.exists():
            return None, CredentialBundle()
        data = read_json(path)
        provider_section = data.get("provider") or {}
        if not isinstance(provider_section, dict):
            return ClientConfig(self.client_id, self.display_config_path, []), CredentialBundle()

        providers: list[ProviderConfig] = []
        credentials: dict[str, dict[str, Any]] = {}
        for provider_id, provider_data in provider_section.items():
            if not isinstance(provider_data, dict):
                continue
            options = provider_data.get("options") or {}
            if not isinstance(options, dict):
                options = {}
            secret_values = {k: deepcopy(v) for k, v in options.items() if k in SECRET_FIELDS}
            credential_ref = f"{self.client_id}:{provider_id}" if secret_values else None
            if credential_ref:
                credentials[credential_ref] = {"options": secret_values}
            models = []
            model_section = provider_data.get("models") or {}
            if isinstance(model_section, dict):
                for model_id, model_data in model_section.items():
                    if not isinstance(model_data, dict):
                        model_data = {}
                    limit = model_data.get("limit") or {}
                    if not isinstance(limit, dict):
                        limit = {}
                    model_raw = deepcopy(model_data)
                    models.append(
                        ModelConfig(
                            model_id=model_id,
                            display_name=model_data.get("name") or model_data.get("displayName") or model_data.get("display_name"),
                            context_limit=limit.get("context"),
                            output_limit=limit.get("output"),
                            raw=model_raw,
                        )
                    )
            npm = provider_data.get("npm")
            provider_type = "openai-compatible" if npm == "@ai-sdk/openai-compatible" else "unknown"
            safe_options = without_keys(options, SECRET_FIELDS)
            raw = deepcopy(provider_data)
            raw["options"] = safe_options
            providers.append(
                ProviderConfig(
                    provider_id=provider_id,
                    display_name=provider_data.get("name") or provider_data.get("displayName") or provider_data.get("display_name"),
                    provider_type=provider_type,
                    base_url=options.get("baseURL") or options.get("base_url"),
                    credential_ref=credential_ref,
                    credentials_omitted=False,
                    models=models,
                    raw=raw,
                )
            )
        return ClientConfig(self.client_id, self.display_config_path, providers), CredentialBundle(credentials)

    def merge(self, incoming: ClientConfig, credentials: CredentialBundle, *, selectors: list[Any], dry_run: bool = False, force: bool = False, update: bool = False) -> ImportReport:
        report = ImportReport()
        path = self.config_path
        file_existed = path.exists()
        if not file_existed:
            data = {"$schema": "https://opencode.ai/config.json"}
        else:
            data = read_json(path)
        original = deepcopy(data)
        provider_section = data.setdefault("provider", {})
        if not isinstance(provider_section, dict):
            provider_section = {}
            data["provider"] = provider_section

        for provider in incoming.providers:
            if selectors and not any(selector.client == self.client_id and (selector.provider is None or selector.provider == provider.provider_id) for selector in selectors):
                continue
            selected_models = [m for m in provider.models if selection_matches(selectors, self.client_id, provider.provider_id, m.model_id)]
            has_model_selector = any(selector.client == self.client_id and selector.provider == provider.provider_id and selector.model is not None for selector in selectors)
            if has_model_selector and not selected_models:
                continue
            provider_exists = provider.provider_id in provider_section and isinstance(provider_section.get(provider.provider_id), dict)
            provider_was_new = not provider_exists
            in_update_mode = update and not force and provider_exists
            if provider_exists:
                dest_provider = provider_section[provider.provider_id]
                if force or not update:
                    report.skipped.append(f"{self.client_id}:{provider.provider_id} provider exists")
            else:
                dest_provider = deepcopy(provider.raw) if provider.raw else {}
                dest_provider.setdefault("models", {})
                if has_model_selector and isinstance(dest_provider.get("models"), dict):
                    dest_provider["models"] = {model.model_id: deepcopy(model.raw) if model.raw else _model_to_raw(model) for model in selected_models}
                provider_section[provider.provider_id] = dest_provider
                report.added.append(f"{self.client_id}:{provider.provider_id}")

            if force or not provider_exists:
                if provider.raw:
                    new_provider = deepcopy(provider.raw)
                    existing_models_value = dest_provider.get("models")
                    existing_models = deepcopy(existing_models_value) if isinstance(existing_models_value, dict) else {}
                    existing_options_value = dest_provider.get("options")
                    existing_options = deepcopy(existing_options_value) if isinstance(existing_options_value, dict) else {}
                    incoming_options_value = new_provider.get("options")
                    incoming_options = deepcopy(incoming_options_value) if isinstance(incoming_options_value, dict) else {}
                    incoming_options.update({k: v for k, v in existing_options.items() if k in SECRET_FIELDS})
                    new_provider["options"] = incoming_options
                    if force:
                        new_provider["models"] = deepcopy(new_provider.get("models")) if isinstance(new_provider.get("models"), dict) else {}
                    else:
                        new_provider["models"] = existing_models
                    provider_section[provider.provider_id] = new_provider
                    dest_provider = provider_section[provider.provider_id]
                    if force and provider_exists:
                        report.updated.append(f"{self.client_id}:{provider.provider_id} provider")
                if provider.base_url:
                    dest_provider.setdefault("options", {})
                    key = "baseURL" if "baseURL" in (provider.raw.get("options", {}) if provider.raw else {}) else "base_url"
                    dest_provider["options"][key] = provider.base_url

            if in_update_mode:
                dest_options = dest_provider.setdefault("options", {})
                if not isinstance(dest_options, dict):
                    dest_options = {}
                    dest_provider["options"] = dest_options
                if provider.base_url:
                    current_base_url = dest_options.get("baseURL") if "baseURL" in dest_options else dest_options.get("base_url")
                    if current_base_url != provider.base_url:
                        key = "baseURL" if "baseURL" in dest_options else "base_url"
                        dest_options[key] = provider.base_url
                        report.updated.append(f"{self.client_id}:{provider.provider_id} base_url")
                incoming_options = ((provider.raw or {}).get("options") or {})
                if isinstance(incoming_options, dict):
                    for opt_key, opt_value in incoming_options.items():
                        if opt_key in SECRET_FIELDS:
                            continue
                        if dest_options.get(opt_key) != opt_value:
                            dest_options[opt_key] = deepcopy(opt_value)
                            report.updated.append(f"{self.client_id}:{provider.provider_id} options.{opt_key}")

            dest_models = dest_provider.setdefault("models", {})
            if not isinstance(dest_models, dict):
                dest_models = {}
                dest_provider["models"] = dest_models
            for model in selected_models:
                model_exists = model.model_id in dest_models
                if model_exists:
                    if provider_was_new:
                        # Model was populated from provider.raw during creation — skip silently
                        continue
                    if in_update_mode:
                        dest_model = dest_models[model.model_id]
                        if not isinstance(dest_model, dict):
                            dest_model = {}
                            dest_models[model.model_id] = dest_model
                        if model.display_name is not None and dest_model.get("name") != model.display_name:
                            dest_model["name"] = model.display_name
                            report.updated.append(f"{self.client_id}:{provider.provider_id}:{model.model_id} name")
                        if model.context_limit is not None:
                            limit = dest_model.get("limit")
                            if not isinstance(limit, dict):
                                limit = {}
                            if limit.get("context") != model.context_limit:
                                limit["context"] = model.context_limit
                                dest_model["limit"] = limit
                                report.updated.append(f"{self.client_id}:{provider.provider_id}:{model.model_id} context_limit")
                        if model.output_limit is not None:
                            limit = dest_model.get("limit")
                            if not isinstance(limit, dict):
                                limit = {}
                            if limit.get("output") != model.output_limit:
                                limit["output"] = model.output_limit
                                dest_model["limit"] = limit
                                report.updated.append(f"{self.client_id}:{provider.provider_id}:{model.model_id} output_limit")
                        incoming_raw = model.raw or {}
                        if isinstance(incoming_raw, dict) and _deep_merge_dicts(dest_model, incoming_raw):
                            report.updated.append(f"{self.client_id}:{provider.provider_id}:{model.model_id} raw")
                        continue
                    if not force:
                        report.conflicts.append(f"{self.client_id}:{provider.provider_id}:{model.model_id} model exists")
                        continue
                dest_models[model.model_id] = deepcopy(model.raw) if model.raw else _model_to_raw(model)
                if model_exists:
                    report.updated.append(f"{self.client_id}:{provider.provider_id}:{model.model_id}")
                else:
                    report.added.append(f"{self.client_id}:{provider.provider_id}:{model.model_id}")

            if provider.credential_ref:
                if credentials.has_secret_for(provider.credential_ref):
                    report.credentials_present.append(provider.credential_ref)
                    secret_options = credentials.secrets[provider.credential_ref].get("options", {})
                    dest_options = dest_provider.setdefault("options", {})
                    for key, value in secret_options.items():
                        if key in dest_options and not force:
                            if in_update_mode:
                                if dest_options[key] != value:
                                    dest_options[key] = value
                                    report.updated.append(f"{provider.credential_ref} credential")
                                continue
                            report.conflicts.append(f"{provider.credential_ref} credential field exists")
                            continue
                        dest_options[key] = value
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


def _deep_merge_dicts(dest: dict[str, Any], src: dict[str, Any]) -> bool:
    """Deep merge src into dest (mutates dest in place). Returns True if any change was made.

    For nested dict values, recurse. Does not delete dest-only keys.
    """
    changed = False
    for k, v in src.items():
        current = dest.get(k)
        if isinstance(v, dict) and isinstance(current, dict):
            if _deep_merge_dicts(current, v):
                changed = True
        elif current != v:
            dest[k] = deepcopy(v)
            changed = True
    return changed


def _model_to_raw(model: ModelConfig) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    if model.display_name:
        raw["name"] = model.display_name
    limit: dict[str, Any] = {}
    if model.context_limit is not None:
        limit["context"] = model.context_limit
    if model.output_limit is not None:
        limit["output"] = model.output_limit
    if limit:
        raw["limit"] = limit
    return raw
