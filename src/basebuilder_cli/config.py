from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_API_BASE = "https://www.basebuilder.cn"


@dataclass
class CliConfig:
    api_base: str
    token: str = ""


def state_dir() -> Path:
    return Path(os.environ.get("BB_HOME", "~/.basebuilder")).expanduser()


def config_path() -> Path:
    return state_dir() / "config.json"


def runs_dir() -> Path:
    return state_dir() / "runs"


def load_config() -> CliConfig:
    path = config_path()
    data: dict[str, Any] = {}
    if path.exists():
        data = json.loads(path.read_text())
    return CliConfig(
        api_base=str(os.environ.get("BB_API_BASE") or data.get("api_base") or DEFAULT_API_BASE).rstrip("/"),
        token=str(data.get("token") or ""),
    )


def save_config(config: CliConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"api_base": config.api_base, "token": config.token}, ensure_ascii=False, indent=2))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def clear_token() -> None:
    config = load_config()
    config.token = ""
    save_config(config)
