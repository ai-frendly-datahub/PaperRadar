from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Source:
    name: str
    type: str
    url: str


@dataclass
class EntityDefinition:
    name: str
    display_name: str
    keywords: list[str]


@dataclass
class Paper:
    title: str
    link: str
    abstract: str
    authors: list[str]
    published: datetime | None
    source: str
    category: str
    doi: str | None = None
    arxiv_id: str | None = None
    pdf_url: str | None = None
    venue: str | None = None
    citation_count: int | None = None
    categories: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    matched_entities: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Article:
    title: str
    link: str
    summary: str
    published: datetime | None
    source: str
    category: str
    matched_entities: dict[str, list[str]] = field(default_factory=dict)
    collected_at: datetime | None = None


@dataclass
class CategoryConfig:
    category_name: str
    display_name: str
    sources: list[Source]
    entities: list[EntityDefinition]


@dataclass
class RadarSettings:
    database_path: Path
    report_dir: Path
    raw_data_dir: Path
    search_db_path: Path


@dataclass
class EmailSettings:
    smtp_host: str
    smtp_port: int
    username: str
    password: str
    from_address: str
    to_addresses: list[str]


@dataclass
class TelegramSettings:
    bot_token: str
    chat_id: str


@dataclass
class NotificationConfig:
    enabled: bool
    channels: list[str]
    email: EmailSettings | None = None
    webhook_url: str | None = None
    telegram: TelegramSettings | None = None
    rules: dict[str, object] = field(default_factory=dict)
