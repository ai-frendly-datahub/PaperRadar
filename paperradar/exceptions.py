from __future__ import annotations

from radar_core.exceptions import (  # noqa: F401
    CollectionError,
    ConfigError,
    NetworkError,
    NotificationError,
    ParseError,
    RadarError,
    ReportError,
    SearchError,
    SourceError,
    StorageError,
)


class EmptyCollectionError(CollectionError):
    """Enabled sources produced no papers. An empty run is not success."""


__all__ = [
    "RadarError",
    "ConfigError",
    "CollectionError",
    "EmptyCollectionError",
    "SourceError",
    "NetworkError",
    "ParseError",
    "StorageError",
    "ReportError",
    "SearchError",
    "NotificationError",
]
