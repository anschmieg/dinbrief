from pathlib import Path

from dinbrief import config


def test_search_is_disabled_by_default(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)  # type: ignore[attr-defined]

    assert config.search_enabled() is False


def test_managed_feature_state_overrides_user_default(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)  # type: ignore[attr-defined]
    (tmp_path / "config.toml").write_text("[search]\nenabled = false\n", encoding="utf-8")

    path = config.set_search_enabled(True)

    assert path == tmp_path / "features.toml"
    assert config.search_enabled() is True
    assert "enabled = false" in (tmp_path / "config.toml").read_text(encoding="utf-8")
