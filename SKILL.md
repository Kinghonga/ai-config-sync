---
name: ai-config-sync
summary: Use ai-sync to migrate AI coding client third-party model provider configs safely across machines.
---

# ai-config-sync Skill

Use this skill when a user asks to migrate, back up, restore, list, export, import, or synchronize AI coding client third-party model/provider configuration across machines.

## How to get ai-sync

Do not assume pip is available. The user may not have pip. Always use the standalone script:

```bash
# Download the single-file script (zero dependencies)
curl -sSLO https://raw.githubusercontent.com/Kinghonga/ai-config-sync/main/ai-sync.py
# Or if curl is missing
python3 -c "import urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/Kinghonga/ai-config-sync/main/ai-sync.py', 'ai-sync.py')"
```

If the script is already present in the current directory, skip the download step.

Run it with `python3 ai-sync.py <command>`.

> The standalone script currently lacks `diff` and `--update`. If the user has pip, prefer `pip install ai-config-sync` for full features.

## What ai-sync handles

`ai-sync` syncs only third-party model provider configuration for supported AI coding clients:

- OpenCode provider config from `~/.config/opencode/opencode.json`
- Claude Code model/provider-related `env` keys from `~/.claude/settings.json` as `claude-code:anthropic-env`

It does not sync full app settings, skills, presets, themes, keybindings, commands, permissions, agents, plugins, or unrelated config.

## Safety rules

- Never print API keys, auth tokens, authorization headers, or decrypted credential values.
- Do not manually copy/edit secret values unless the user explicitly asks and understands the risk.
- Prefer `python3 ai-sync.py export` and `python3 ai-sync.py import` over manual JSON edits.
- Recommend `--dry-run` before importing when possible.
- Recommend interactive passphrase entry via getpass for security.
- Explain that passphrase is resolved from `AI_SYNC_PASSPHRASE` env var (for automation) or interactive getpass prompt. There is no `--passphrase` CLI flag to avoid shell history leaks.
- Do not claim any network upload is involved. `ai-sync` is local-only.

## Common commands

```bash
# Check if script exists, download if not, then list
[ -f ai-sync.py ] || curl -sSLO https://raw.githubusercontent.com/Kinghonga/ai-config-sync/main/ai-sync.py
python3 ai-sync.py list

# Export to ai-sync.json (will prompt for passphrase)
python3 ai-sync.py export

# Export without credentials
python3 ai-sync.py export --no-credentials

# Selective export
python3 ai-sync.py export --include opencode:sense-nova

# Compare local config against a package (no writes)
python3 ai-sync.py diff

# Dry-run import
python3 ai-sync.py import --dry-run

# Import with confirmation
python3 ai-sync.py import

# Import with field-level merge (safer than --force)
python3 ai-sync.py import --update --yes

# Force overwrite
python3 ai-sync.py import --force

# Automation (no prompt)
AI_SYNC_PASSPHRASE=mysecret python3 ai-sync.py import --yes

# Custom home directory (testing/staging)
python3 ai-sync.py list --home /path/to/home
python3 ai-sync.py export --home /path/to/home --output package.json
python3 ai-sync.py import --home /path/to/home --input package.json --dry-run
```

## Workflow: export from Machine A, import on Machine B

1. On Machine A (user's work computer), download and run export:
   ```bash
   curl -sSLO https://raw.githubusercontent.com/Kinghonga/ai-config-sync/main/ai-sync.py
   python3 ai-sync.py export
   ```
2. Ask the user to copy the generated `ai-sync.json` to Machine B (USB, email, cloud drive).
3. On Machine B (user's home computer), download and import:
   ```bash
   curl -sSLO https://raw.githubusercontent.com/Kinghonga/ai-config-sync/main/ai-sync.py
   python3 ai-sync.py import --dry-run    # preview first
   python3 ai-sync.py import              # apply
   ```

Always recommend `--dry-run` before actual import so the user sees what will change.
