from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import CategoryConfig, EntityDefinition, RadarSettings, Source


def load_settings(config_path: Path | None = None) -> RadarSettings:
    """Load settings from config/config.yaml."""
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "config.yaml"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    return RadarSettings(
        database_path=Path(config["database_path"]),
        report_dir=Path(config["report_dir"]),
        raw_data_dir=Path(config["raw_data_dir"]),
        search_db_path=Path(config["search_db_path"]),
    )


def load_category_config(category: str, categories_dir: Path | None = None) -> CategoryConfig:
    """Load category config from YAML."""
    if categories_dir is None:
        categories_dir = Path(__file__).parent.parent / "config" / "categories"

    config_file = categories_dir / f"{category}.yaml"
    with open(config_file) as f:
        config = yaml.safe_load(f)

    sources = [Source(**src) for src in config.get("sources", [])]
    entities = [EntityDefinition(**ent) for ent in config.get("entities", [])]

    return CategoryConfig(
        category_name=config["category_name"],
        display_name=config["display_name"],
        sources=sources,
        entities=entities,
    )
