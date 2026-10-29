from __future__ import annotations

import html
import inspect
import os
import re
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib import robotparser
from urllib.parse import urlparse

import feedparser
import requests
import structlog
from pybreaker import CircuitBreakerError
from radar_core import AdaptiveThrottler, CrawlHealthStore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .common.validators import is_challenge_or_error_page
from .exceptions import NetworkError, ParseError, SourceError
from .models import Article, Paper, Source
from .raw_logger import RawLogger
from .resilience import get_circuit_breaker_manager

logger = structlog.get_logger(__name__)

# Identifying client name. Public feeds may reject the default python-requests
# agent. This is a fixed product name, not a browser impersonation list.
PAPER_RADAR_USER_AGENT = (
    "PaperRadar/0.1 (+https://github.com/ai-frendly-datahub/PaperRadar; public-rss)"
)
RSS_TIMEOUT_SECONDS = 45
_ENV_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": PAPER_RADAR_USER_AGENT,
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}
_DEFAULT_HEALTH_DB_PATH = "data/radar_data.duckdb"
_ARXIV_MIN_INTERVAL_SECONDS = 3.0
# export.arxiv.org/rss and arxiv.org/rss are not the canonical feed. The export
# host's robots.txt disallows every path, and its /rss/* responses are HTTP 200
# channels with zero <item> elements. rss.arxiv.org is the documented RSS host.
_LEGACY_ARXIV_RSS_HOSTS = frozenset({"export.arxiv.org", "arxiv.org", "www.arxiv.org"})
_ARXIV_RSS_PATH = re.compile(r"^/(?:rss|atom)/[A-Za-z][A-Za-z0-9.+_-]*$")
_COLLECTION_CONTROL_LOCK = threading.Lock()
_ACTIVE_THROTTLER: AdaptiveThrottler | None = None
_ACTIVE_HEALTH_STORE: CrawlHealthStore | None = None


# Bounded cooldown policy for access-block (403) sources. Opt-in per source via
# ``retry_after_cooldown_statuses: [403]``. 403 may be a temporary bot/IP block,
# so a disabled source is probed at most once per week, and only when
# robots.txt can be read and allows the feed. Permanent errors stay disabled.
_ACCESS_BLOCK_COOLDOWN_SECONDS = 7 * 86400
_ROBOTS_TIMEOUT_SECONDS = 10
_ALLOWED_EXTRA_RETRY_STATUSES = frozenset({403})


def _cooldown_policy(source: Source) -> tuple[frozenset[int], float | None] | None:
    """Return ``(extra_statuses, cooldown_seconds)`` or None when config is invalid."""
    raw_statuses = source.config.get("retry_after_cooldown_statuses") or []
    raw_seconds = source.config.get("retry_after_cooldown_seconds")
    try:
        statuses = frozenset(int(item) for item in raw_statuses)
        seconds = float(raw_seconds) if raw_seconds is not None else None
    except (TypeError, ValueError):
        return None
    if not statuses <= _ALLOWED_EXTRA_RETRY_STATUSES:
        return None
    if seconds is not None and seconds != seconds:  # NaN
        return None
    if statuses:
        seconds = max(seconds or 0.0, float(_ACCESS_BLOCK_COOLDOWN_SECONDS))
    return statuses, seconds


def _core_supports_status_opt_in(claim_retry: Any) -> bool:
    try:
        params = inspect.signature(claim_retry).parameters
    except (TypeError, ValueError):
        return False
    return "retry_statuses" in params or any(
        param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values()
    )


def _robots_allows(feed_url: str) -> bool:
    """True only when a real robots.txt was read and allows ``feed_url``.

    A missing robots.txt (404/410) allows. Anything we cannot read as plain
    robots rules (bot-challenge page, 5xx, redirect, network error) is treated
    as "cannot verify" and blocks the probe. TLS is always verified.
    """
    parsed = urlparse(feed_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        response = requests.get(
            robots_url,
            timeout=_ROBOTS_TIMEOUT_SECONDS,
            headers={"User-Agent": PAPER_RADAR_USER_AGENT},
            allow_redirects=False,
            verify=True,
        )
    except requests.RequestException:
        return False
    if response.status_code in {404, 410}:
        return True
    content_type = response.headers.get("Content-Type", "")
    text = response.text if response.status_code == 200 else ""
    if (
        response.status_code != 200
        or not content_type.lower().startswith("text/plain")
        or "<html" in text[:512].lower()
    ):
        return False
    parser = robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch("PaperRadar", feed_url)


def _set_collection_controls(throttler: AdaptiveThrottler, health_store: CrawlHealthStore) -> None:
    global _ACTIVE_THROTTLER, _ACTIVE_HEALTH_STORE
    with _COLLECTION_CONTROL_LOCK:
        _ACTIVE_THROTTLER = throttler
        _ACTIVE_HEALTH_STORE = health_store


def _clear_collection_controls() -> None:
    global _ACTIVE_THROTTLER, _ACTIVE_HEALTH_STORE
    with _COLLECTION_CONTROL_LOCK:
        _ACTIVE_THROTTLER = None
        _ACTIVE_HEALTH_STORE = None


def _get_collection_controls() -> tuple[AdaptiveThrottler | None, CrawlHealthStore | None]:
    with _COLLECTION_CONTROL_LOCK:
        return _ACTIVE_THROTTLER, _ACTIVE_HEALTH_STORE


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


def _source_host(source: Source) -> str:
    return urlparse(source.url).netloc.lower() or source.name


def _source_min_interval(source: Source, default_interval: float) -> float:
    host = _source_host(source)
    if host.endswith("arxiv.org") or source.type.lower() == "arxiv":
        return max(default_interval, _ARXIV_MIN_INTERVAL_SECONDS)
    return default_interval


def _create_session() -> requests.Session:
    session = requests.Session()
    session.verify = True
    session.headers.update(dict(_DEFAULT_HEADERS))

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


class _CooldownProbeSession(requests.Session):
    """One transport attempt, with no adapter retries or redirect followups."""

    def get(self, url: str | bytes, params: Any = None, **kwargs: Any) -> requests.Response:
        kwargs["allow_redirects"] = False
        return super().get(url, params=params, **kwargs)


def _fetch_url_with_retry(
    url: str,
    timeout: int,
    headers: dict[str, str] | None = None,
    session: requests.Session | None = None,
    source_name: str | None = None,
    throttler: AdaptiveThrottler | None = None,
    health_store: CrawlHealthStore | None = None,
    max_attempts: int = 3,
) -> requests.Response:
    """Fetch URL with retry logic on transient errors."""
    merged = dict(_DEFAULT_HEADERS)
    if headers:
        for key, value in headers.items():
            if key.lower() == "user-agent":
                continue
            merged[key] = value
    merged["User-Agent"] = PAPER_RADAR_USER_AGENT
    if throttler is None or health_store is None:
        active_throttler, active_health_store = _get_collection_controls()
        throttler = throttler or active_throttler
        health_store = health_store or active_health_store

    retryable_errors = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
    )

    is_probe = isinstance(session, _CooldownProbeSession)
    if is_probe:
        max_attempts = 1

    for attempt in range(max_attempts):
        if source_name is not None and throttler is not None:
            throttler.acquire(source_name)

        try:
            if session is not None:
                response = session.get(url, timeout=timeout, headers=merged, verify=True)
            else:
                response = requests.get(url, timeout=timeout, headers=merged, verify=True)
            response.raise_for_status()
            if is_probe and not 200 <= response.status_code < 300:
                raise requests.HTTPError(
                    "Cooldown probe requires a 2xx response", response=response
                )

            if source_name is not None and throttler is not None:
                throttler.record_success(source_name)
                if health_store is not None:
                    delay = throttler.get_current_delay(source_name)
                    health_store.record_success(source_name, delay)

            return response
        except retryable_errors as exc:
            if source_name is not None and throttler is not None:
                retry_after: int | str | None = None
                if isinstance(exc, requests.exceptions.HTTPError):
                    response = exc.response
                    if response is not None and response.status_code == 429:
                        retry_after = _parse_retry_after(response.headers.get("Retry-After"))

                throttler.record_failure(source_name, retry_after=retry_after)
                if health_store is not None:
                    delay = throttler.get_current_delay(source_name)
                    health_store.record_failure(source_name, str(exc), delay)
                    if is_probe and isinstance(exc, requests.exceptions.HTTPError):
                        probe_response = exc.response
                        if probe_response is not None:
                            retry_header = probe_response.headers.get("Retry-After")
                            if retry_header:
                                try:
                                    retry_at = (
                                        datetime.now(UTC) + timedelta(seconds=int(retry_header))
                                        if retry_header.strip().isdigit()
                                        else parsedate_to_datetime(retry_header)
                                    )
                                    if retry_at.tzinfo is not None:
                                        getattr(health_store, "postpone_retry")(
                                            source_name, retry_at
                                        )
                                except (ValueError, TypeError, OverflowError):
                                    pass

            if attempt == max_attempts - 1:
                raise

    raise RuntimeError("Retry loop exited unexpectedly")


def _parse_retry_after(value: str | None) -> int | str | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    if stripped.isdigit():
        return int(stripped)

    return stripped


def _env_var_names(value: object) -> list[str]:
    raw_names: list[str] = []
    if isinstance(value, str):
        raw_names = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        raw_names = [str(item) for item in value]
    names: list[str] = []
    for item in raw_names:
        candidate = item.strip()
        if not candidate:
            continue
        if _ENV_VAR_NAME.fullmatch(candidate) is None:
            raise ValueError("required_env must be an environment variable name")
        names.append(candidate)
    return names


def missing_required_env(source: Source) -> list[str]:
    """Return required env var names that are unset. Values are never returned."""
    configured = source.config.get("required_env", source.config.get("required_env_vars"))
    missing: list[str] = []
    for name in _env_var_names(configured):
        if not os.environ.get(name, "").strip():
            missing.append(name)
    return missing


def emit_missing_secret_warning(source_name: str, env_names: str | Sequence[str]) -> None:
    """Warn once that a source was skipped. Prints env var names, never values."""
    names = _env_var_names(env_names if isinstance(env_names, str) else list(env_names))
    if not names:
        raise ValueError("required_env must be an environment variable name")
    message = f"{source_name} skipped; required env {', '.join(names)}"
    print(f"::warning title=PaperRadar missing secret::{message}", flush=True)


def _missing_secret_errors(
    source: Source,
    *,
    raw_logger: RawLogger | None,
) -> list[str] | None:
    try:
        missing_env = missing_required_env(source)
    except ValueError:
        return [f"{source.name}: required_env must be an environment variable name"]
    if not missing_env:
        return None
    emit_missing_secret_warning(source.name, missing_env)
    if raw_logger is not None:
        raw_logger.log_skip(source_name=source.name, required_env=missing_env)
    return [f"{source.name}: skipped_missing_env {', '.join(missing_env)}"]


def collect_sources(
    sources: list[Source],
    *,
    category: str,
    limit_per_source: int = 30,
    timeout: int = RSS_TIMEOUT_SECONDS,
    min_interval_per_host: float = 0.5,
    max_workers: int | None = None,
    health_db_path: str | None = None,
    raw_logger: RawLogger | None = None,
) -> tuple[list[Article], list[str]]:
    """Fetch items from all configured sources, returning articles and errors.

    Failures return an empty article list for that source. This function never
    invents sample or fake items.
    """
    articles: list[Article] = []
    errors: list[str] = []
    manager = get_circuit_breaker_manager()
    workers = _resolve_max_workers(max_workers)
    enabled_sources = [source for source in sources if source.enabled]
    throttler = AdaptiveThrottler(min_delay=max(0.001, min_interval_per_host))
    health_store = CrawlHealthStore(
        health_db_path or os.environ.get("RADAR_CRAWL_HEALTH_DB_PATH", _DEFAULT_HEALTH_DB_PATH)
    )
    _set_collection_controls(throttler, health_store)
    session = _create_session()

    _js_types = {"javascript", "browser"}
    rss_sources = [s for s in enabled_sources if s.type.lower() not in _js_types]
    js_sources = [s for s in enabled_sources if s.type.lower() in _js_types]
    source_hosts: dict[str, str] = {source.name: _source_host(source) for source in rss_sources}
    host_min_intervals: dict[str, float] = {}
    for source in rss_sources:
        host = source_hosts[source.name]
        host_min_intervals[host] = max(
            host_min_intervals.get(host, min_interval_per_host),
            _source_min_interval(source, min_interval_per_host),
        )
    rate_limiters: dict[str, RateLimiter] = {
        host: RateLimiter(min_interval=interval) for host, interval in host_min_intervals.items()
    }
    host_locks: dict[str, threading.Lock] = {
        host: threading.Lock() for host in set(source_hosts.values())
    }

    def _collect_for_source(source: Source) -> tuple[list[Article], list[str]]:
        secret_errors = _missing_secret_errors(source, raw_logger=raw_logger)
        if secret_errors is not None:
            return [], secret_errors
        probe = False
        if health_store.is_disabled(source.name):
            claim_retry = getattr(health_store, "claim_retry", None)
            policy = _cooldown_policy(source)
            if (
                source.config.get("retry_after_cooldown") is not True
                or policy is None
                or not callable(claim_retry)
                or not callable(getattr(health_store, "finish_retry", None))
                or not callable(getattr(health_store, "postpone_retry", None))
            ):
                return [], [f"{source.name}: Source disabled (crawl health threshold reached)"]
            extra_statuses, cooldown_seconds = policy
            if extra_statuses and not _core_supports_status_opt_in(claim_retry):
                return [], [f"{source.name}: Source disabled (crawl health threshold reached)"]
            claim_kwargs: dict[str, Any] = {}
            if extra_statuses:
                claim_kwargs["retry_statuses"] = sorted(extra_statuses)
            if cooldown_seconds is not None:
                claim_kwargs["cooldown_seconds"] = cooldown_seconds
            if not claim_retry(source.name, **claim_kwargs):
                return [], [f"{source.name}: Source disabled (crawl health threshold reached)"]
            if extra_statuses and not _robots_allows(source.url):
                return [], [
                    f"{source.name}: Cooldown probe skipped; robots.txt disallows or "
                    "could not be verified; still disabled"
                ]
            probe = True

        host = source_hosts[source.name]

        probe_session = _CooldownProbeSession() if probe else None
        try:
            with host_locks[host]:
                rate_limiters[host].acquire()
                breaker = manager.get_breaker(source.name)
                result = breaker.call(
                    _collect_single,
                    source,
                    category=category,
                    limit=min(limit_per_source, 5) if probe else limit_per_source,
                    timeout=timeout,
                    session=probe_session if probe_session is not None else session,
                )
            if probe:
                if not result:
                    return [], [
                        f"{source.name}: Cooldown probe returned no valid items; still disabled"
                    ]
                getattr(health_store, "finish_retry")(source.name)
            return result, []
        except CircuitBreakerError:
            return [], [f"{source.name}: Circuit breaker open (source unavailable)"]
        except SourceError as exc:
            return [], [str(exc)]
        except (NetworkError, ParseError) as exc:
            return [], [f"{source.name}: {exc}"]
        except Exception as exc:
            return [], [f"{source.name}: Unexpected error - {type(exc).__name__}: {exc}"]
        finally:
            if probe_session is not None:
                probe_session.close()

    try:
        if workers == 1:
            for source in rss_sources:
                source_articles, source_errors = _collect_for_source(source)
                articles.extend(source_articles)
                errors.extend(source_errors)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map: list[Future[tuple[list[Article], list[str]]]] = [
                    executor.submit(_collect_for_source, source) for source in rss_sources
                ]

                for future in future_map:
                    source_articles, source_errors = future.result()
                    articles.extend(source_articles)
                    errors.extend(source_errors)

        if js_sources:
            runnable_js: list[Source] = []
            for source in js_sources:
                secret_errors = _missing_secret_errors(source, raw_logger=raw_logger)
                if secret_errors is not None:
                    errors.extend(secret_errors)
                    continue
                runnable_js.append(source)
            try:
                from .browser_collector import collect_browser_sources

                js_articles, js_errors = collect_browser_sources(runnable_js, category)
                articles.extend(js_articles)
                errors.extend(js_errors)
            except ImportError:
                logger.warning(
                    "playwright_unavailable",
                    js_source_count=len(js_sources),
                    hint="pip install 'radar-core[browser]'",
                )
    finally:
        session.close()
        health_store.close()
        _clear_collection_controls()

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


def _rewrite_arxiv_rss_url(url: str) -> str:
    """Point legacy arXiv RSS URLs at the canonical rss.arxiv.org feed.

    ``export.arxiv.org/rss/<category>`` returns HTTP 200 with an empty channel,
    so feedparser reports zero entries and the source looks successful.
    """
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if host not in _LEGACY_ARXIV_RSS_HOSTS:
        return url
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return url
    path = parsed.path.rstrip("/")
    if _ARXIV_RSS_PATH.fullmatch(path) is None:
        return url
    return f"https://rss.arxiv.org{path}"


def _canonical_arxiv_feed_url(feed: Any, fetched_url: str) -> str | None:
    """Return a different official arXiv feed URL declared by an empty channel."""
    channel = getattr(feed, "feed", None)
    if not isinstance(channel, Mapping):
        return None

    candidates: list[str] = []
    links = channel.get("links")
    if isinstance(links, list):
        for item in links:
            if not isinstance(item, Mapping) or item.get("rel") != "self":
                continue
            href = item.get("href")
            if isinstance(href, str) and href.strip():
                candidates.append(href.strip())
    link = channel.get("link")
    if isinstance(link, str) and link.strip():
        candidates.append(link.strip())

    fetched = urlparse(fetched_url)
    fetched_host = fetched.netloc.lower()
    fetched_path = fetched.path.rstrip("/")
    for raw in candidates:
        parsed = urlparse(raw)
        host = parsed.netloc.lower()
        if parsed.scheme not in {"http", "https"} or host != "rss.arxiv.org":
            continue
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            continue
        path = parsed.path.rstrip("/")
        if _ARXIV_RSS_PATH.fullmatch(path) is None:
            continue
        if host == fetched_host and path == fetched_path:
            continue
        return f"https://rss.arxiv.org{path}"
    return None


def _collect_rss(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
    feed_url: str | None = None,
    allow_canonical_follow: bool = True,
) -> list[Article]:
    """Collect articles from RSS feeds."""
    request_url = feed_url or _rewrite_arxiv_rss_url(source.url)
    try:
        response = _fetch_url_with_retry(
            request_url,
            timeout,
            session=session,
            source_name=source.name,
        )
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
        raise NetworkError(f"Network error fetching {source.name}: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise SourceError(source.name, f"Request failed: {exc}", exc) from exc

    try:
        feed = feedparser.parse(response.content)
        items: list[Article] = []
        dropped_challenge = 0

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
            if not summary:
                summary = title
            summary = html.unescape(summary.strip())
            if is_challenge_or_error_page(title, summary):
                dropped_challenge += 1
                continue

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

        if items:
            return items
        if dropped_challenge:
            raise ParseError(
                f"Feed from {source.name} was a challenge, Cloudflare, or cookie-wall page"
            )
        if allow_canonical_follow and not feed.entries:
            canonical = _canonical_arxiv_feed_url(feed, request_url)
            if canonical is not None:
                logger.info(
                    "arxiv_rss_empty_channel",
                    source=source.name,
                    fetched_url=request_url,
                    canonical_url=canonical,
                )
                time.sleep(_ARXIV_MIN_INTERVAL_SECONDS)
                return _collect_rss(
                    source,
                    category=category,
                    limit=limit,
                    timeout=timeout,
                    session=session,
                    feed_url=canonical,
                    allow_canonical_follow=False,
                )
        return items
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"Failed to parse feed from {source.name}: {exc}") from exc


def _collect_arxiv(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Paper]:
    """Collect articles from arXiv API with rate limiting (max 3 requests/second)."""
    try:
        response = _fetch_url_with_retry(
            source.url,
            timeout,
            session=session,
            source_name=source.name,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise NetworkError(f"arXiv API request failed: {exc}") from exc

    try:
        feed = feedparser.parse(response.content)
        items: list[Paper] = []

        for entry in feed.entries[:limit]:
            title = html.unescape(_entry_text(entry, "title").strip())
            raw_id = _entry_text(entry, "id").strip()
            link = _entry_text(entry, "link").strip() or raw_id

            # Skip entries with empty title or link
            if not title or not link:
                continue

            # Extract abstract from arXiv entry
            summary = html.unescape(_entry_text(entry, "summary").strip())
            content = entry.get("content", [])
            if not summary and isinstance(content, list) and content:
                summary = html.unescape(str(content[0].get("value", "")).strip()) if content else ""

            published = _extract_datetime(entry)
            arxiv_id = _extract_arxiv_id(raw_id or link)
            authors = _extract_authors(entry)

            items.append(
                Paper(
                    title=title,
                    link=link,
                    abstract=summary,
                    authors=authors,
                    published=published,
                    source=source.name,
                    category=category,
                    arxiv_id=arxiv_id,
                    pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None,
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
        response = _fetch_url_with_retry(
            source.url,
            timeout,
            session=session,
            source_name=source.name,
        )
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
        response = _fetch_url_with_retry(
            source.url,
            timeout,
            session=session,
            source_name=source.name,
        )
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
        response = _fetch_url_with_retry(
            source.url,
            timeout,
            session=session,
            source_name=source.name,
        )
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
        response = _fetch_url_with_retry(
            source.url,
            timeout,
            session=session,
            source_name=source.name,
        )
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
            title = work.get("display_title") or work.get("display_name") or work.get("title") or ""
            if not title:
                continue

            doi = str(work.get("doi") or work.get("ids", {}).get("doi") or "").strip()
            openalex_id = str(work.get("id") or "").strip()
            if doi:
                link = doi if doi.startswith("http") else f"https://doi.org/{doi}"
            elif openalex_id:
                link = (
                    openalex_id
                    if openalex_id.startswith("http")
                    else f"https://openalex.org/{openalex_id}"
                )
            else:
                continue

            citation_count = work.get("cited_by_count")
            publication_date = str(work.get("publication_date") or "").strip()
            publication_year = work.get("publication_year") or work.get("year")
            summary_parts: list[str] = []
            abstract = work.get("abstract", "") or ""
            if abstract:
                summary_parts.append(str(abstract))
            if doi:
                summary_parts.append(f"DOI: {doi}")
            if isinstance(citation_count, int):
                summary_parts.append(f"Citation count: {citation_count}")
            if publication_date:
                summary_parts.append(f"Publication date: {publication_date}")
            elif publication_year:
                summary_parts.append(f"Publication year: {publication_year}")
            if openalex_id:
                summary_parts.append(f"OpenAlex ID: {openalex_id}")

            # Extract publish date
            published = None
            if publication_date:
                try:
                    published = datetime.fromisoformat(publication_date).replace(tzinfo=UTC)
                except ValueError:
                    published = None
            elif publication_year:
                try:
                    published = datetime(int(publication_year), 1, 1, tzinfo=UTC)
                except (TypeError, ValueError):
                    published = None
            if source.config.get("event_model") == "citation_snapshot":
                published = None

            items.append(
                Article(
                    title=title,
                    link=link,
                    summary=". ".join(summary_parts),
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
        response = _fetch_url_with_retry(
            source.url,
            timeout,
            session=session,
            source_name=source.name,
        )
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


def _extract_arxiv_id(value: str) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    candidate = parsed.path.rsplit("/", maxsplit=1)[-1] if parsed.path else value
    candidate = candidate.strip()
    return candidate or None


def _extract_authors(entry: Mapping[str, Any]) -> list[str]:
    authors_raw = entry.get("authors", [])
    authors: list[str] = []
    if isinstance(authors_raw, list):
        for author in authors_raw:
            if isinstance(author, Mapping):
                name = author.get("name")
                if isinstance(name, str) and name.strip():
                    authors.append(name.strip())
    if authors:
        return authors

    author = entry.get("author")
    if isinstance(author, str) and author.strip():
        return [author.strip()]
    return []


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value if isinstance(value, str) else ""
