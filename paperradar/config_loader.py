from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import yaml

from .models import (
    CategoryConfig,
    EmailSettings,
    EntityDefinition,
    NotificationConfig,
    RadarSettings,
    Source,
    TelegramSettings,
)


def load_settings(config_path: Path | None = None) -> RadarSettings:
    """Load settings from config/config.yaml."""
    resolve_relative_paths = config_path is None
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    project_root = config_path.resolve().parents[1]

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    def _path(key: str) -> Path:
        value = Path(config[key])
        if resolve_relative_paths and not value.is_absolute():
            return (project_root / value).resolve()
        return value

    return RadarSettings(
        database_path=_path("database_path"),
        report_dir=_path("report_dir"),
        raw_data_dir=_path("raw_data_dir"),
        search_db_path=_path("search_db_path"),
    )


def load_category_config(category: str, categories_dir: Path | None = None) -> CategoryConfig:
    """Load category config from YAML."""
    if categories_dir is None:
        categories_dir = Path(__file__).parent.parent / "config" / "categories"

    config_file = categories_dir / f"{category}.yaml"
    with open(config_file, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    sources = [Source(**src) for src in config.get("sources", [])]
    entities = [EntityDefinition(**ent) for ent in config.get("entities", [])]

    return CategoryConfig(
        category_name=config["category_name"],
        display_name=config["display_name"],
        sources=sources,
        entities=entities,
    )


def load_category_quality_config(
    category: str, categories_dir: Path | None = None
) -> dict[str, object]:
    """Load data quality metadata from a category YAML."""
    if categories_dir is None:
        categories_dir = Path(__file__).parent.parent / "config" / "categories"

    config_file = categories_dir / f"{category}.yaml"
    with open(config_file, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        return {"data_quality": {}, "source_backlog": {}}

    data_quality = config.get("data_quality", {})
    source_backlog = config.get("source_backlog", {})
    return {
        "data_quality": data_quality if isinstance(data_quality, dict) else {},
        "source_backlog": source_backlog if isinstance(source_backlog, dict) else {},
    }


def _resolve_env_refs(value: object) -> object:
    """Resolve ${VAR} environment variable references in strings."""
    if isinstance(value, str):
        result = value
        import re

        for match in re.finditer(r"\$\{([^}]+)\}", value):
            var_name = match.group(1)
            env_value = os.environ.get(var_name, "")
            result = result.replace(match.group(0), env_value)
        return result
    elif isinstance(value, dict):
        return {k: _resolve_env_refs(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_refs(item) for item in value]
    return value


def load_notification_config(
    config_path: Path | None = None,
) -> NotificationConfig:
    """Load notification configuration from notifications.yaml.

    Args:
        config_path: Path to notifications.yaml. If None, uses project_root/config/notifications.yaml

    Returns:
        NotificationConfig with resolved environment variables

    Raises:
        FileNotFoundError: If notifications.yaml does not exist
    """
    project_root = Path(__file__).resolve().parent.parent
    config_file = config_path or project_root / "config" / "notifications.yaml"

    if not config_file.exists():
        return NotificationConfig(enabled=False, channels=[])

    with open(config_file, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        return NotificationConfig(enabled=False, channels=[])

    notifications_dict = raw.get("notifications", {})
    if not isinstance(notifications_dict, dict):
        return NotificationConfig(enabled=False, channels=[])

    enabled = bool(notifications_dict.get("enabled", False))
    channels_raw = notifications_dict.get("channels", [])
    channels = [str(c) for c in cast(list[object], channels_raw) if isinstance(c, str)]

    email_settings = None
    email_raw = notifications_dict.get("email")
    if isinstance(email_raw, dict):
        email_dict = cast(dict[str, object], _resolve_env_refs(email_raw))
        try:
            smtp_port_raw = email_dict.get("smtp_port", 587)
            smtp_port = int(smtp_port_raw) if isinstance(smtp_port_raw, (int, str)) else 587
            email_settings = EmailSettings(
                smtp_host=str(email_dict.get("smtp_host", "")),
                smtp_port=smtp_port,
                username=str(email_dict.get("username", "")),
                password=str(email_dict.get("password", "")),
                from_address=str(email_dict.get("from_address", "")),
                to_addresses=[
                    str(addr)
                    for addr in cast(list[object], email_dict.get("to_addresses", []))
                    if isinstance(addr, str)
                ],
            )
        except (ValueError, KeyError):
            email_settings = None

    webhook_url = None
    webhook_raw = notifications_dict.get("webhook_url")
    if isinstance(webhook_raw, str):
        resolved = _resolve_env_refs(webhook_raw)
        webhook_url = str(resolved) if resolved else None

    telegram_settings = None
    telegram_raw = notifications_dict.get("telegram")
    if isinstance(telegram_raw, dict):
        telegram_dict = cast(dict[str, object], _resolve_env_refs(telegram_raw))
        try:
            telegram_settings = TelegramSettings(
                bot_token=str(telegram_dict.get("bot_token", "")),
                chat_id=str(telegram_dict.get("chat_id", "")),
            )
        except (ValueError, KeyError):
            telegram_settings = None

    rules_raw = notifications_dict.get("rules", {})
    rules = (
        cast(dict[str, object], _resolve_env_refs(rules_raw)) if isinstance(rules_raw, dict) else {}
    )

    return NotificationConfig(
        enabled=enabled,
        channels=channels,
        email=email_settings,
        webhook_url=webhook_url,
        telegram=telegram_settings,
        rules=rules,
    )
