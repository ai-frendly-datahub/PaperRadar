"""
Data validation utilities for Radar articles.

Provides functions for:
- Title normalization (whitespace, special characters)
- URL similarity detection
- Article validation
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

from paperradar.models import Paper

_ERROR_PAGE_TITLE_RE = re.compile(
    r"^(?:"
    r"just a moment\.{0,3}|"
    r"attention required!?|"
    r"access denied|"
    r"403 forbidden|"
    r"404(?: not found)?|"
    r"not found|"
    r"enable javascript and cookies to continue"
    r")(?:\s*\|\s*.*)?$",
    re.IGNORECASE,
)


def is_challenge_or_error_page(title: str | None, body: str | None = None) -> bool:
    """True when a fetched document is a bot wall, Cloudflare interstitial, or error page.

    These responses are not papers. Callers drop them instead of storing the page.
    TLS verification stays on; this function does not bypass the wall.
    """
    title_text = (title or "").strip()
    body_text = body or ""
    if title_text and _ERROR_PAGE_TITLE_RE.match(title_text):
        return True

    blob = f"{title_text}\n{body_text}".lower()
    if "just a moment" in blob and (
        "cloudflare" in blob or "security verification" in blob or "verify you are human" in blob
    ):
        return True
    if "attention required" in blob and ("cloudflare" in blob or "been blocked" in blob):
        return True
    if "cf-browser-verification" in blob or "challenges.cloudflare.com" in blob:
        return True
    if "slowaes.decrypt" in blob and "cupid" in blob:
        return True
    if "enable javascript and cookies to continue" in blob:
        return True
    return False


def normalize_title(title: str) -> str:
    """
    Normalize article title by removing extra whitespace and special characters.

    Args:
        title: Raw article title

    Returns:
        Normalized title (lowercase, no extra spaces, minimal special chars)

    Examples:
        >>> normalize_title("  Breaking News  ")
        "breaking news"
        >>> normalize_title("Title (Updated)")
        "title updated"
    """
    if not title:
        return ""

    normalized = title.lower()

    normalized = re.sub(r"\s+", " ", normalized).strip()

    normalized = re.sub(r"[^\w\s\-]", "", normalized)

    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


def validate_url_format(url: str) -> bool:
    """
    Validate if URL has valid format.

    Args:
        url: URL to validate

    Returns:
        True if URL is valid, False otherwise

    Examples:
        >>> validate_url_format("https://example.com/article")
        True
        >>> validate_url_format("not-a-url")
        False
        >>> validate_url_format("")
        False
    """
    if not url:
        return False

    try:
        parsed = urlparse(url)
        # Must have scheme and netloc
        return bool(parsed.scheme and parsed.netloc)
    except Exception:
        return False


def is_similar_url(url1: str, url2: str, threshold: float = 0.8) -> bool:
    """
    Check if two URLs are similar (same domain and similar path).

    Args:
        url1: First URL
        url2: Second URL
        threshold: Similarity threshold (0.0-1.0)

    Returns:
        True if URLs are similar, False otherwise

    Examples:
        >>> is_similar_url(
        ...     "https://example.com/article/123",
        ...     "https://example.com/article/123?ref=abc"
        ... )
        True
        >>> is_similar_url(
        ...     "https://example.com/article/123",
        ...     "https://other.com/article/123"
        ... )
        False
    """
    try:
        parsed1 = urlparse(url1)
        parsed2 = urlparse(url2)

        if parsed1.netloc != parsed2.netloc:
            return False

        path1 = parsed1.path
        path2 = parsed2.path

        if path1 == path2:
            return True

        ratio = SequenceMatcher(None, path1, path2).ratio()
        return ratio >= threshold

    except Exception:
        return False


def detect_duplicate_articles(
    title1: str,
    url1: str,
    title2: str,
    url2: str,
    title_threshold: float = 0.85,
    url_threshold: float = 0.8,
) -> bool:
    """
    Detect if two articles are duplicates based on title and URL similarity.

    Args:
        title1: First article title
        url1: First article URL
        title2: Second article title
        url2: Second article URL
        title_threshold: Title similarity threshold
        url_threshold: URL similarity threshold

    Returns:
        True if articles are likely duplicates, False otherwise

    Examples:
        >>> detect_duplicate_articles(
        ...     "Breaking News",
        ...     "https://example.com/article/123",
        ...     "Breaking News",
        ...     "https://example.com/article/123?ref=abc"
        ... )
        True
    """
    # Normalize titles
    norm_title1 = normalize_title(title1)
    norm_title2 = normalize_title(title2)

    # Check title similarity
    title_ratio = SequenceMatcher(None, norm_title1, norm_title2).ratio()
    if title_ratio < title_threshold:
        return False

    # Check URL similarity
    return is_similar_url(url1, url2, url_threshold)


def validate_article(article: Paper) -> tuple[bool, list[str]]:
    """
    Validate an Article object for data quality.

    Args:
        article: Article to validate

    Returns:
        Tuple of (is_valid, error_messages)

    Examples:
        >>> from paperradar.models import Paper
        >>> from datetime import datetime
        >>> article = Paper(
        ...     title="Valid Article",
        ...     link="https://example.com/article",
        ...     abstract="Summary",
        ...     authors=["Author"],
        ...     published=datetime.now(),
        ...     source="Example",
        ...     category="news"
        ... )
        >>> is_valid, errors = validate_article(article)
        >>> is_valid
        True
    """
    errors: list[str] = []

    # Validate title
    if not article.title:
        errors.append("title is missing or not a string")
    elif len(article.title.strip()) == 0:
        errors.append("title is empty")

    # Validate link
    if not article.link:
        errors.append("link is missing or not a string")
    elif not validate_url_format(article.link):
        errors.append(f"link has invalid URL format: {article.link}")

    # Validate summary
    _summary = getattr(article, "abstract", None) or getattr(article, "summary", None)
    if not _summary:
        errors.append("summary is missing or not a string")
    elif len(_summary.strip()) == 0:
        errors.append("summary is empty")

    # Validate source
    if not article.source:
        errors.append("source is missing or not a string")

    # Validate category
    if not article.category:
        errors.append("category is missing or not a string")

    title_text = article.title if isinstance(article.title, str) else ""
    summary_text = _summary if isinstance(_summary, str) else ""
    if is_challenge_or_error_page(title_text, summary_text):
        errors.append("content appears to be a challenge or error page")

    return len(errors) == 0, errors
