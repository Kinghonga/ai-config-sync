from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    if path.exists():
        backup_path = path.with_name(path.name + f".bak.{timestamp}")
        backup_path.write_bytes(path.read_bytes())
        backup = str(backup_path)
    rendered = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    json.loads(rendered)
    tmp_path = path.with_name(path.name + f".tmp.{os.getpid()}")
    try:
        tmp_path.write_text(rendered, encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return backup


def without_keys(data: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in keys}
