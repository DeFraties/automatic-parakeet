"""Loads `sources.yaml` (per-source settings) and the app `.env` settings."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.core.config import Settings, get_settings

DEFAULT_SOURCES_YAML = Path(__file__).with_name("sources.yaml")


@dataclass
class SourceConfig:
    key: str
    enabled: bool = False
    delay_seconds: float = 5.0
    max_records_per_run: int = 100
    cache_ttl_hours: float = 72
    settings: dict = field(default_factory=dict)  # everything else, passed to the plugin


def load_sources(path: str | Path | None = None) -> dict[str, SourceConfig]:
    with open(path or DEFAULT_SOURCES_YAML, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    out: dict[str, SourceConfig] = {}
    for key, cfg in raw.items():
        cfg = dict(cfg or {})
        out[key] = SourceConfig(
            key=key,
            enabled=bool(cfg.pop("enabled", False)),
            delay_seconds=float(cfg.pop("delay_seconds", 5.0)),
            max_records_per_run=int(cfg.pop("max_records_per_run", 100)),
            cache_ttl_hours=float(cfg.pop("cache_ttl_hours", 72)),
            settings=cfg,
        )
    return out


def settings() -> Settings:
    return get_settings()
