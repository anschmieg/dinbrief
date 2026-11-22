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


class ConfigError(ValueError):
    """The dinbrief configuration has an invalid structure."""


class UnknownSenderProfileError(ValueError):
    """A letter names a sender profile that is absent from the configuration."""

    def __init__(self, sender: str, metadata: dict[str, Any]) -> None:
        super().__init__(f"Unknown sender profile: {sender}")
        self.metadata = metadata


def effective_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    defaults = config.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ConfigError("`defaults` must be a TOML table.")
    merged = deep_merge(defaults, raw)
    sender = merged.get("sender")
    if isinstance(sender, str):
        profiles = config.get("senders", {})
        if not isinstance(profiles, dict):
            raise ConfigError("`senders` must be a TOML table.")
        if sender not in profiles:
            raise UnknownSenderProfileError(sender, merged)
        profile = profiles[sender]
        if not isinstance(profile, dict):
            raise ConfigError(f"Sender profile `{sender}` must be a TOML table.")
        merged["sender"] = profile
    return merged
