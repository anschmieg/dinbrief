from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from platformdirs import user_cache_path, user_config_path


def config_dir() -> Path:
    return user_config_path("dinbrief")


def cache_dir() -> Path:
    path = user_cache_path("dinbrief")
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config() -> dict[str, Any]:
    path = config_dir() / "config.toml"
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def effective_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    defaults = config.get("defaults", {})
    merged = deep_merge(defaults, raw)
    sender = merged.get("sender")
    if isinstance(sender, str):
        profiles = config.get("senders", {})
        if sender not in profiles:
            raise ValueError(f"Unknown sender profile: {sender}")
        merged["sender"] = profiles[sender]
        merged["sender_profile"] = sender
    return merged
