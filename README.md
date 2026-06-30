[中文文档](README_CN.md)

# ai-config-sync

> One command to export, one command to import. AI model configs, migrated across machines.

OpenCode and Claude Code model provider configs, API keys encrypted, transferred between machines. Pure local, no servers.

> **One-way migration:** export on the source machine, import on the target. No continuous sync, no conflict resolution. Use `diff` to preview changes before applying.

## Quick Start

```bash
# Install
pip install git+https://github.com/Kinghonga/ai-config-sync.git

# On Machine A — export
ai-sync export

# Copy ai-sync.json to Machine B (USB, email, cloud drive)

# On Machine B — preview, then import
ai-sync diff        # see what differs (no writes)
ai-sync import      # apply with confirmation
```

Requires Python 3.10+.

### Zero-dependency fallback (lags behind pip version)

```bash
curl -O https://raw.githubusercontent.com/Kinghonga/ai-config-sync/main/ai-sync.py
python3 ai-sync.py export
```

The single-file script lacks the latest `diff` and `--update` commands. For full features, use the pip install above.

## Commands

### `list` — show detected configs

```bash
python3 ai-sync.py list
```

Lists OpenCode and Claude Code providers and models found on this machine.

### `export` — package configs to a file

```bash
python3 ai-sync.py export                                  # all configs
python3 ai-sync.py export --include opencode:sense-nova      # one provider
python3 ai-sync.py export --no-credentials                 # skip API keys
```

### `diff` — compare local config against a package

```bash
python3 ai-sync.py diff                                    # compare against ai-sync.json
python3 ai-sync.py diff --include opencode:sense-nova        # one provider only
```

Shows, for each provider/model/credential, whether it is only-on-current, only-in-package, in-sync, or differs. Never writes files, never prints secret values.

### `import` — apply a package

```bash
python3 ai-sync.py import --dry-run    # preview changes without writing
python3 ai-sync.py import              # apply with confirmation
python3 ai-sync.py import --update     # merge only differing fields (safer)
python3 ai-sync.py import --force      # overwrite existing (full replace)
```

`--update` and `--force` are mutually exclusive:
- **default**: skip existing providers/models/credential fields (report as conflict)
- **`--update`**: update only the fields that differ, preserve everything else
- **`--force`**: replace whole providers/models with the incoming values

## Options

| Option | Applies to | Description |
|--------|------------|-------------|
| `--include SELECTOR` | export, import, diff | Filter: `client`, `client:provider`, `client:provider:model` |
| `--no-credentials` | export | Export without API keys |
| `--dry-run` | import | Preview changes without writing |
| `--update` | import | Update only differing fields, preserve the rest (field-level merge) |
| `--force` | import | Overwrite existing providers/models/credential fields (full replace) |
| `--yes` | import | Skip confirmation prompt (automation) |
| `--output FILE` | export | Custom export path (default: `ai-sync.json`) |
| `--input FILE` | import, diff | Custom package path (default: `ai-sync.json`) |
| `--home PATH` | all | Custom home directory |

## AI Agent Mode

Install [SKILL.md](SKILL.md) into your AI coding client, then ask in natural language:

```bash
# OpenCode
cp SKILL.md ~/.config/opencode/skills/

# Claude Code
cp SKILL.md ~/.claude/skills/
```

> **You:** "Migrate my AI model configs from my work computer"
>
> **AI:** Downloads ai-sync.py, runs export, guides you through import.

The AI handles downloading the script, running commands, and diagnosing errors.

## Supported Clients

| Client | Config | Status |
|--------|--------|--------|
| OpenCode | `opencode.json` | ✅ |
| Claude Code | `settings.json` | ✅ |
| Cursor | — | 🚧 Planned |
| Codex | — | 🚧 Planned |
| Trae | — | 🚧 Planned |
| Continue.dev | — | 🚧 Planned |

## Security

- API keys encrypted with PBKDF2-SHA256 (600k iterations) + authenticated cipher
- Passphrase entered interactively — never stored, never in shell history
- Set `AI_SYNC_PASSPHRASE` env var for automation
- Import creates timestamped `.bak` backups
- Atomic writes via temp file + rename
- Pure local — no network calls

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `python3: command not found` | Install Python 3.10+ from python.org |
| "No supported configs found" | Run `python3 ai-sync.py list` to check |
| Import shows "conflicts" | Run `diff` to inspect; use `--update` to merge fields or `--force` to replace |
| Wrong passphrase | Re-export on the source machine |
| "cannot decrypt (AES-256-GCM)" | Standalone script can't decrypt pip-version packages; re-export with the standalone script |

## License

MIT
