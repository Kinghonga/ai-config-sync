from __future__ import annotations

from ai_config_sync.adapters.base import ClientAdapter
from ai_config_sync.adapters.claude_code import ClaudeCodeAdapter
from ai_config_sync.adapters.opencode import OpenCodeAdapter

ADAPTERS: list[type[ClientAdapter]] = [OpenCodeAdapter, ClaudeCodeAdapter]

__all__ = ["ADAPTERS", "ClientAdapter", "OpenCodeAdapter", "ClaudeCodeAdapter"]
