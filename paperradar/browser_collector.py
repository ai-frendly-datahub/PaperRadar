"""Browser-based article collection for JavaScript-rendered sources."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

import structlog

from .models import Article


if TYPE_CHECKING:
    from .models import Source

logger = structlog.get_logger()

_BROWSER_COLLECTION_AVAILABLE = False
try:
    _module = importlib.import_module("radar_core.browser_collector")
    _core_collect = _module.collect_browser_sources

    _BROWSER_COLLECTION_AVAILABLE = True
except ImportError:
    _core_collect = None  # type: ignore[assignment]


def collect_browser_sources(
    sources: list[Source],
    category: str,
    *,
    timeout: int = 15_000,
    health_db_path: str | None = None,
) -> tuple[list[Article], list[str]]:
    if not sources:
        return [], []

    if not _BROWSER_COLLECTION_AVAILABLE or _core_collect is None:
        logger.warning(
            "browser_collection_unavailable",
            reason="radar_core.browser_collector not installed",
            source_count=len(sources),
            hint="pip install 'radar-core[browser]'",
        )
        return [], [
            f"Browser collection unavailable for {len(sources)} JS source(s). "
            "Install radar-core[browser]."
        ]

    try:
        source_dicts: list[dict[str, Any]] = [
            {"name": s.name, "type": s.type, "url": s.url} for s in sources
        ]
        core_articles, errors = _core_collect(
            sources=source_dicts,
            category=category,
            timeout=timeout,
            health_db_path=health_db_path,
        )
    except ImportError:
        logger.warning(
            "playwright_not_installed",
            source_count=len(sources),
            hint="pip install 'radar-core[browser]'",
        )
        return [], [
            f"Playwright not installed for {len(sources)} JS source(s). "
            "Install radar-core[browser]."
        ]
    except Exception as exc:
        logger.error(
            "browser_collection_failed",
            error=str(exc),
            source_count=len(sources),
        )
        return [], [f"Browser collection failed: {exc}"]

    local_articles: list[Article] = []
    for article in core_articles:
        local_articles.append(
            Article(
                title=article.title,
                link=article.link,
                summary=article.summary,
                published=article.published,
                source=article.source,
                category=article.category or category,
            )
        )

    if local_articles:
        logger.info(
            "browser_collection_complete",
            article_count=len(local_articles),
            error_count=len(errors),
        )

    return local_articles, errors
