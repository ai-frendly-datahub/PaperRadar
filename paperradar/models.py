from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Re-export from radar-core shared package
from radar_core.models import (
    Article,
    CategoryConfig,
    EmailSettings,
    EntityDefinition,
    NotificationConfig,
    RadarSettings,
    Source,
    TelegramSettings,
)


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

    @property
    def summary(self) -> str:
        return self.abstract


__all__ = [
    "Article",
    "CategoryConfig",
    "EmailSettings",
    "EntityDefinition",
    "NotificationConfig",
    "Paper",
    "RadarSettings",
    "Source",
    "TelegramSettings",
]
