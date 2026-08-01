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
    config: dict[str, Any] = {}
    if path.exists():
        with path.open("rb") as handle:
            config = tomllib.load(handle)
    state_path = config_dir() / "features.toml"
    if state_path.exists():
        with state_path.open("rb") as handle:
            config = deep_merge(config, tomllib.load(handle))
    return config


def search_enabled() -> bool:
    return bool(load_config().get("search", {}).get("enabled", False))


def set_search_enabled(enabled: bool) -> Path:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "features.toml"
    path.write_text(f"[search]\nenabled = {'true' if enabled else 'false'}\n", encoding="utf-8")
    return path


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
