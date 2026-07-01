[English](#english) | [中文](#中文)

---

<a id="english"></a>

# ai-config-sync

![tests](https://github.com/Kinghonga/ai-config-sync/actions/workflows/test.yml/badge.svg)

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

### Standalone script (zero dependencies)

```bash
curl -O https://raw.githubusercontent.com/Kinghonga/ai-config-sync/main/ai-sync.py
python3 ai-sync.py export
```

No Python packages required — runs on stdlib alone. Designed for locked-down machines where `pip install` isn't an option.

| Command / Option | pip version | Standalone script |
|------------------|:-----------:|:-----------------:|
| `list` | ✅ | ✅ |
| `export` | ✅ | ✅ |
| `import` | ✅ | ✅ |
| `import --force` | ✅ | ✅ |
| `import --dry-run` | ✅ | ✅ |
| `import --yes` | ✅ | ✅ |
| `diff` | ✅ | — |
| `import --update` | ✅ | — |
| Encryption | AES-256-GCM | xor-hmac-sha256 |

Packages exported by one version **cannot** be decrypted by the other (different cipher). Use the same installation path on both machines.

## Commands

### `list` — show detected configs

```bash
ai-sync list
```

Lists OpenCode and Claude Code providers and models found on this machine.

### `export` — package configs to a file

```bash
ai-sync export                                  # all configs
ai-sync export --include opencode:sense-nova    # one provider
ai-sync export --no-credentials                 # skip API keys
```

### `diff` — compare local config against a package

```bash
ai-sync diff                                    # compare against ai-sync.json
ai-sync diff --include opencode:sense-nova      # one provider only
```

Shows, for each provider/model/credential, whether it is only-on-current, only-in-package, in-sync, or differs. Never writes files, never prints secret values.

### `import` — apply a package

```bash
ai-sync import --dry-run    # preview changes without writing
ai-sync import              # apply with confirmation
ai-sync import --update     # merge only differing fields (safer)
ai-sync import --force      # overwrite existing (full replace)
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
| "No supported configs found" | Run `ai-sync list` to check |
| Import shows "conflicts" | Run `diff` to inspect; use `--update` to merge fields or `--force` to replace |
| Wrong passphrase | Re-export on the source machine |
| "cannot decrypt (AES-256-GCM)" | Standalone script can't decrypt pip-version packages; re-export with the standalone script |

## License

MIT

---

<a id="中文"></a>

# ai-config-sync

![tests](https://github.com/Kinghonga/ai-config-sync/actions/workflows/test.yml/badge.svg)

> 一句导出，一句导入。AI 模型配置，跨机器迁移。

OpenCode 和 Claude Code 的模型供应商配置、API Key 加密后在不同机器间传输。纯本地运行，不依赖服务器。

> **单向迁移：** 在源机器导出，在目标机器导入。不做持续同步，不解决冲突。导入前可用 `diff` 预览差异。

## 快速开始

```bash
# 安装
pip install git+https://github.com/Kinghonga/ai-config-sync.git

# 在机器 A — 导出
ai-sync export

# 把 ai-sync.json 拷到机器 B（U盘、邮件、网盘）

# 在机器 B — 先预览再导入
ai-sync diff        # 查看差异（不写入）
ai-sync import      # 确认后应用
```

需要 Python 3.10+。

### 单文件脚本（零依赖）

```bash
curl -O https://raw.githubusercontent.com/Kinghonga/ai-config-sync/main/ai-sync.py
python3 ai-sync.py export
```

无需安装任何 Python 包，仅依赖标准库。适用于无法 `pip install` 的受限环境。

| 命令 / 选项 | pip 版本 | 单文件脚本 |
|------------|:--------:|:---------:|
| `list` | ✅ | ✅ |
| `export` | ✅ | ✅ |
| `import` | ✅ | ✅ |
| `import --force` | ✅ | ✅ |
| `import --dry-run` | ✅ | ✅ |
| `import --yes` | ✅ | ✅ |
| `diff` | ✅ | — |
| `import --update` | ✅ | — |
| 加密算法 | AES-256-GCM | xor-hmac-sha256 |

两个版本导出的包**无法**互相解密（加密算法不同）。请在两台机器上使用相同的安装方式。

## 命令

### `list` — 查看检测到的配置

```bash
ai-sync list
```

显示本机上检测到的 OpenCode 和 Claude Code 供应商与模型。

### `export` — 打包配置到文件

```bash
ai-sync export                                  # 全部配置
ai-sync export --include opencode:sense-nova    # 单个供应商
ai-sync export --no-credentials                 # 不含 API Key
```

### `diff` — 对比本地配置与导出包

```bash
ai-sync diff                                    # 与 ai-sync.json 对比
ai-sync diff --include opencode:sense-nova      # 只看某个供应商
```

逐个供应商/模型/凭据显示：仅本地有、仅包里有、已同步、还是有差异。绝不写入文件，绝不打印密钥。

### `import` — 应用导出包

```bash
ai-sync import --dry-run    # 预览变更不写入
ai-sync import              # 确认后应用
ai-sync import --update     # 只合并差异字段（更安全）
ai-sync import --force      # 覆盖已有（整体替换）
```

`--update` 与 `--force` 互斥：
- **默认**：跳过已存在的供应商/模型/凭据字段（记为 conflict）
- **`--update`**：只更新有差异的字段，其余保持不变
- **`--force`**：用导出包的值整体替换供应商/模型

## 选项

| 选项 | 适用于 | 说明 |
|--------|------------|------|
| `--include SELECTOR` | export、import、diff | 过滤：`client`、`client:provider`、`client:provider:model` |
| `--no-credentials` | export | 导出不含 API Key |
| `--dry-run` | import | 预览变更不写入 |
| `--update` | import | 只更新差异字段，保留其余（字段级合并） |
| `--force` | import | 覆盖已有供应商/模型/凭据字段（整体替换） |
| `--yes` | import | 跳过确认（自动化） |
| `--output FILE` | export | 自定义导出路径（默认：`ai-sync.json`） |
| `--input FILE` | import、diff | 自定义导入包路径（默认：`ai-sync.json`） |
| `--home PATH` | 全部 | 自定义 home 目录 |

## AI 助手模式

把 [SKILL.md](SKILL.md) 安装到 AI 编码客户端，然后用自然语言提需求：

```bash
# OpenCode
cp SKILL.md ~/.config/opencode/skills/

# Claude Code
cp SKILL.md ~/.claude/skills/
```

> **你：** "帮我把公司电脑的 AI 模型配置迁移过来"
>
> **AI：** 下载 ai-sync、执行 export、引导你完成 import。

AI 负责下载脚本、运行命令、诊断错误。

## 支持的客户端

| 客户端 | 配置 | 状态 |
|--------|------|--------|
| OpenCode | `opencode.json` | ✅ |
| Claude Code | `settings.json` | ✅ |
| Cursor | — | 🚧 计划中 |
| Codex | — | 🚧 计划中 |
| Trae | — | 🚧 计划中 |
| Continue.dev | — | 🚧 计划中 |

## 安全

- API Key 用 PBKDF2-SHA256（60 万次迭代）+ 认证加密算法加密
- passphrase 交互输入，不存储，不留 shell 历史
- 设置 `AI_SYNC_PASSPHRASE` 环境变量用于自动化
- 导入时创建带时间戳的 `.bak` 备份
- 通过临时文件 + 重命名实现原子写入
- 纯本地运行，无网络请求

## 常见问题

| 问题 | 解决 |
|------|------|
| `python3: command not found` | 从 python.org 安装 Python 3.10+ |
| "No supported configs found" | 运行 `ai-sync list` 检查 |
| 导入显示 "conflicts" | 运行 `diff` 查看；用 `--update` 合并字段或 `--force` 整体替换 |
| passphrase 不对 | 回到源机器重新导出 |
| "cannot decrypt (AES-256-GCM)" | 单文件脚本无法解密 pip 版本的包；用单文件脚本重新导出 |

## 许可证

MIT
