from __future__ import annotations

import html
import os
import threading
import time
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests
from pybreaker import CircuitBreakerError
from requests.adapters import HTTPAdapter
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from urllib3.util.retry import Retry

from .exceptions import NetworkError, ParseError, SourceError
from .models import Article, Source
from .resilience import get_circuit_breaker_manager


_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (compatible; RadarTemplateBot/1.0; +https://github.com/zzragida/ai-frendly-datahub)",
}


class RateLimiter:
    def __init__(self, min_interval: float = 0.5):
        self._min_interval: float = min_interval
        self._last_request: float = 0.0
        self._lock: threading.Lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request = time.monotonic()


def _resolve_max_workers(max_workers: int | None = None) -> int:
    if max_workers is None:
        raw_value = os.environ.get("RADAR_MAX_WORKERS", "5")
        try:
            parsed = int(raw_value)
        except ValueError:
            parsed = 5
    else:
        parsed = max_workers

    return max(1, min(parsed, 10))


def _create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_DEFAULT_HEADERS)

    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[408, 429, 500, 502, 503, 504, 522, 524],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


def _fetch_url_with_retry(
    url: str,
    timeout: int,
    headers: dict[str, str] | None = None,
    session: requests.Session | None = None,
) -> requests.Response:
    """Fetch URL with retry logic on transient errors."""
    merged = {**_DEFAULT_HEADERS, **(headers or {})}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        reraise=True,
    )
    def _fetch() -> requests.Response:
        if session is not None:
            response = session.get(url, timeout=timeout, headers=merged)
        else:
            response = requests.get(url, timeout=timeout, headers=merged)
        response.raise_for_status()
        return response

    return _fetch()


def collect_sources(
    sources: list[Source],
    *,
    category: str,
    limit_per_source: int = 30,
    timeout: int = 15,
    min_interval_per_host: float = 0.5,
    max_workers: int | None = None,
) -> tuple[list[Article], list[str]]:
    """Fetch items from all configured sources, returning articles and errors."""
    articles: list[Article] = []
    errors: list[str] = []
    manager = get_circuit_breaker_manager()
    workers = _resolve_max_workers(max_workers)
    source_hosts: dict[str, str] = {
        source.name: (urlparse(source.url).netloc.lower() or source.name) for source in sources
    }
    rate_limiters: dict[str, RateLimiter] = {
        host: RateLimiter(min_interval=min_interval_per_host) for host in set(source_hosts.values())
    }
    session = _create_session()

    def _collect_for_source(source: Source) -> tuple[list[Article], list[str]]:
        host = source_hosts[source.name]
        rate_limiters[host].acquire()

        try:
            breaker = manager.get_breaker(source.name)
            result = breaker.call(
                _collect_single,
                source,
                category=category,
                limit=limit_per_source,
                timeout=timeout,
                session=session,
            )
            return result, []
        except CircuitBreakerError:
            return [], [f"{source.name}: Circuit breaker open (source unavailable)"]
        except SourceError as exc:
            return [], [str(exc)]
        except (NetworkError, ParseError) as exc:
            return [], [f"{source.name}: {exc}"]
        except Exception as exc:
            return [], [f"{source.name}: Unexpected error - {type(exc).__name__}: {exc}"]

    try:
        if workers == 1:
            for source in sources:
                source_articles, source_errors = _collect_for_source(source)
                articles.extend(source_articles)
                errors.extend(source_errors)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map: list[Future[tuple[list[Article], list[str]]]] = [
                    executor.submit(_collect_for_source, source) for source in sources
                ]

                for future in future_map:
                    source_articles, source_errors = future.result()
                    articles.extend(source_articles)
                    errors.extend(source_errors)
    finally:
        session.close()

    return articles, errors


def _collect_single(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Article]:
    source_type = source.type.lower()

    # Handle RSS feeds
    if source_type == "rss":
        return _collect_rss(
            source, category=category, limit=limit, timeout=timeout, session=session
        )

    # Handle academic APIs
    if source_type == "arxiv":
        return _collect_arxiv(
            source, category=category, limit=limit, timeout=timeout, session=session
        )
    elif source_type == "semantic_scholar":
        return _collect_semantic_scholar(
            source, category=category, limit=limit, timeout=timeout, session=session
        )
    elif source_type == "pubmed":
        return _collect_pubmed(
            source, category=category, limit=limit, timeout=timeout, session=session
        )
    elif source_type == "biorxiv":
        return _collect_biorxiv(
            source, category=category, limit=limit, timeout=timeout, session=session
        )
    elif source_type == "openalex":
        return _collect_openalex(
            source, category=category, limit=limit, timeout=timeout, session=session
        )
    elif source_type == "crossref":
        return _collect_crossref(
            source, category=category, limit=limit, timeout=timeout, session=session
        )

    raise SourceError(source.name, f"Unsupported source type '{source.type}'")


def _collect_rss(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Article]:
    """Collect articles from RSS feeds."""
    try:
        response = _fetch_url_with_retry(source.url, timeout, session=session)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
        raise NetworkError(f"Network error fetching {source.name}: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise SourceError(source.name, f"Request failed: {exc}", exc) from exc

    try:
        feed = feedparser.parse(response.content)
        items: list[Article] = []

        for entry in feed.entries[:limit]:
            published = _extract_datetime(entry)
            summary = _entry_text(entry, "summary") or _entry_text(entry, "description")
            if not summary:
                _content = entry.get("content", [])
                if isinstance(_content, list) and _content:
                    first_item = _content[0]
                    if isinstance(first_item, Mapping):
                        value = first_item.get("value")
                        if isinstance(value, str):
                            summary = value

            title = html.unescape(_entry_text(entry, "title").strip()) or "(no title)"
            link = _entry_text(entry, "link").strip()

            # Skip entries with empty title or link
            if not title or title == "(no title)" or not link:
                continue

            items.append(
                Article(
                    title=title,
                    link=link,
                    summary=html.unescape(summary.strip()),
                    published=published,
                    source=source.name,
                    category=category,
                )
            )

        return items
    except Exception as exc:
        raise ParseError(f"Failed to parse feed from {source.name}: {exc}") from exc


def _collect_arxiv(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Article]:
    """Collect articles from arXiv API with rate limiting (max 3 requests/second)."""
    try:
        response = _fetch_url_with_retry(source.url, timeout, session=session)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise NetworkError(f"arXiv API request failed: {exc}") from exc

    try:
        feed = feedparser.parse(response.content)
        items: list[Article] = []

        for entry in feed.entries[:limit]:
            title = html.unescape(_entry_text(entry, "title").strip())
            link = _entry_text(entry, "link").strip()

            # Skip entries with empty title or link
            if not title or not link:
                continue

            # Extract abstract from arXiv entry
            summary = ""
            content = entry.get("content", [])
            if isinstance(content, list) and content:
                summary = html.unescape(str(content[0].get("value", "")).strip()) if content else ""

            published = _extract_datetime(entry)

            items.append(
                Article(
                    title=title,
                    link=link,
                    summary=summary,
                    published=published,
                    source=source.name,
                    category=category,
                )
            )

        return items
    except Exception as exc:
        raise ParseError(f"Failed to parse arXiv response: {exc}") from exc


def _collect_semantic_scholar(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Article]:
    """Collect articles from Semantic Scholar API (rate limit: 6 calls/second)."""
    try:
        response = _fetch_url_with_retry(source.url, timeout, session=session)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        raise NetworkError(f"Semantic Scholar API request failed: {exc}") from exc
    except ValueError as exc:
        raise ParseError(f"Failed to parse Semantic Scholar JSON response: {exc}") from exc

    try:
        items: list[Article] = []
        papers = data.get("data", [])[:limit]

        for paper in papers:
            title = paper.get("title", "")
            if not title:
                continue

            # Build link from externalLinks or create URL
            external_links = paper.get("externalLinks", [])
            link = ""
            for ext_link in external_links:
                if ext_link.get("url"):
                    link = ext_link["url"]
                    break
            if not link:
                paper_id = paper.get("externalIds", {}).get("DOI", "")
                if paper_id:
                    link = f"https://doi.org/{paper_id}"
                else:
                    continue

            abstract = paper.get("abstract", "")
            if abstract and isinstance(abstract, list):
                abstract = (
                    abstract[0].get("text", "") if abstract and isinstance(abstract, list) else ""
                )

            # Extract publish date
            published = None
            year = paper.get("year")
            if year:
                published = datetime(year, 1, 1, tzinfo=UTC)

            items.append(
                Article(
                    title=title,
                    link=link,
                    summary=str(abstract) if abstract else "",
                    published=published,
                    source=source.name,
                    category=category,
                )
            )

        return items
    except Exception as exc:
        raise ParseError(f"Failed to parse Semantic Scholar data: {exc}") from exc


def _collect_pubmed(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Article]:
    """Collect articles from PubMed API (rate limit: 3 requests/second)."""
    try:
        response = _fetch_url_with_retry(source.url, timeout, session=session)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise NetworkError(f"PubMed API request failed: {exc}") from exc

    try:
        feed = feedparser.parse(response.content)
        items: list[Article] = []

        for entry in feed.entries[:limit]:
            title = html.unescape(_entry_text(entry, "title").strip())
            link = _entry_text(entry, "link").strip()

            # Skip entries with empty title or link
            if not title or not link:
                continue

            summary = html.unescape(
                (_entry_text(entry, "summary") or _entry_text(entry, "description")).strip()
            )
            published = _extract_datetime(entry)

            items.append(
                Article(
                    title=title,
                    link=link,
                    summary=summary,
                    published=published,
                    source=source.name,
                    category=category,
                )
            )

        return items
    except Exception as exc:
        raise ParseError(f"Failed to parse PubMed response: {exc}") from exc


def _collect_biorxiv(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Article]:
    """Collect articles from bioRxiv API."""
    try:
        response = _fetch_url_with_retry(source.url, timeout, session=session)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        raise NetworkError(f"bioRxiv API request failed: {exc}") from exc
    except ValueError as exc:
        raise ParseError(f"Failed to parse bioRxiv JSON response: {exc}") from exc

    try:
        items: list[Article] = []
        entries = data.get("entries", [])[:limit]

        for entry in entries:
            title = entry.get("title", "")
            if not title:
                continue

            link = entry.get("links", {}).get("htmlUrl", "")
            if not link:
                doi = entry.get("doi", "")
                if doi:
                    link = f"https://doi.org/{doi}"
                else:
                    continue

            abstract = entry.get("abstract", "")
            if abstract and isinstance(abstract, list):
                abstract = " ".join([para.get("data", "") for para in abstract])

            # Extract publish date
            published = None
            published_date = entry.get("published")
            if published_date:
                try:
                    published = datetime.fromisoformat(published_date.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

            items.append(
                Article(
                    title=title,
                    link=link,
                    summary=str(abstract) if abstract else "",
                    published=published,
                    source=source.name,
                    category=category,
                )
            )

        return items
    except Exception as exc:
        raise ParseError(f"Failed to parse bioRxiv data: {exc}") from exc


def _collect_openalex(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Article]:
    """Collect articles from OpenAlex API (rate limit: 2 requests/second)."""
    try:
        response = _fetch_url_with_retry(source.url, timeout, session=session)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        raise NetworkError(f"OpenAlex API request failed: {exc}") from exc
    except ValueError as exc:
        raise ParseError(f"Failed to parse OpenAlex JSON response: {exc}") from exc

    try:
        items: list[Article] = []
        works = data.get("results", [])[:limit]

        for work in works:
            title = work.get("display_title", "")
            if not title:
                continue

            link = work.get("id", "").split("/")[-1]
            link = (
                f"https://doi.org/{link}"
                if link.startswith("10.")
                else f"https://openalex.org/{link}"
            )

            abstract = work.get("abstract", "") or ""

            # Extract publish date
            published = None
            published_in = work.get("published_in", {})
            year = published_in.get("year") if published_in else work.get("year")
            if year:
                published = datetime(year, 1, 1, tzinfo=UTC)

            items.append(
                Article(
                    title=title,
                    link=link,
                    summary=str(abstract) if abstract else "",
                    published=published,
                    source=source.name,
                    category=category,
                )
            )

        return items
    except Exception as exc:
        raise ParseError(f"Failed to parse OpenAlex data: {exc}") from exc


def _collect_crossref(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Article]:
    """Collect articles from CrossRef API."""
    try:
        response = _fetch_url_with_retry(source.url, timeout, session=session)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        raise NetworkError(f"CrossRef API request failed: {exc}") from exc
    except ValueError as exc:
        raise ParseError(f"Failed to parse CrossRef JSON response: {exc}") from exc

    try:
        items: list[Article] = []
        items_data = data.get("items", [])[:limit]

        for item in items_data:
            title_list = item.get("title", [])
            title = title_list[0] if isinstance(title_list, list) and title_list else ""
            if not title:
                continue

            # Get DOI link
            doi = item.get("DOI", "")
            link = f"https://doi.org/{doi}" if doi else ""
            if not link:
                continue

            # Get abstract
            abstract = item.get("abstract", "") or ""

            # Extract publish date
            published = None
            published = item.get("published", {})
            if published and isinstance(published, dict):
                date_parts = published.get("date-parts", [[]])
                if date_parts and date_parts[0]:
                    try:
                        year = date_parts[0][0]
                        month = date_parts[0][1] if len(date_parts[0]) > 1 else 1
                        day = date_parts[0][2] if len(date_parts[0]) > 2 else 1
                        published = datetime(year, month, day, tzinfo=UTC)
                    except (ValueError, IndexError):
                        published = None
                else:
                    published = None

            items.append(
                Article(
                    title=title,
                    link=link,
                    summary=str(abstract) if abstract else "",
                    published=published,
                    source=source.name,
                    category=category,
                )
            )

        return items
    except Exception as exc:
        raise ParseError(f"Failed to parse CrossRef data: {exc}") from exc


def _extract_datetime(entry: Mapping[str, Any]) -> datetime | None:
    """Parse a feed entry date into a timezone-aware datetime."""
    published_parsed = entry.get("published_parsed")
    if isinstance(published_parsed, time.struct_time):
        return datetime.fromtimestamp(time.mktime(published_parsed), tz=UTC)

    updated_parsed = entry.get("updated_parsed")
    if isinstance(updated_parsed, time.struct_time):
        return datetime.fromtimestamp(time.mktime(updated_parsed), tz=UTC)

    for key in ("published", "updated", "date"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(str(raw))
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt
            except Exception:
                continue
    return None


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value if isinstance(value, str) else ""
