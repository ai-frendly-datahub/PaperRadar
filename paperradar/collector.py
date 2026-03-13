from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import cast
from xml.etree import ElementTree as ET

import requests
from pybreaker import CircuitBreakerError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .exceptions import NetworkError, ParseError, SourceError
from .models import Paper, Source
from .resilience import get_circuit_breaker_manager


def _parse_iso_date(date_str: str) -> datetime | None:
    """Parse ISO format date string (YYYY-MM-DD or full ISO with timezone)."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _parse_iso_or_year(date_str: str, year: int | None) -> datetime | None:
    """Parse ISO date or fall back to year-only datetime."""
    if date_str:
        result = _parse_iso_date(date_str)
        if result:
            return result
    if year is not None and 1900 < year < 2100:
        return datetime(year, 1, 1, tzinfo=UTC)
    return None


def _parse_pubmed_date(date_str: str) -> datetime | None:
    """Parse PubMed date formats: YYYY/MM/DD (sortpubdate), YYYYMMDD, YYYY."""
    if not date_str:
        return None
    # sortpubdate format: "2023/05/15 00:00"
    date_str = date_str.strip().split(" ")[0]
    for fmt in ("%Y/%m/%d", "%Y%m%d", "%Y"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_date_parts(date_parts: list[int]) -> datetime | None:
    """Parse CrossRef date-parts: [year, month?, day?]."""
    if not date_parts:
        return None
    try:
        year = int(date_parts[0])
        month = int(date_parts[1]) if len(date_parts) > 1 else 1
        day = int(date_parts[2]) if len(date_parts) > 2 else 1
        return datetime(year, month, day, tzinfo=UTC)
    except (ValueError, IndexError, TypeError):
        return None


_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (compatible; PaperRadarBot/1.0; +https://github.com/zzragida/ai-frendly-datahub)",
}


class RateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval_seconds = min_interval_seconds
        self._lock = threading.Lock()
        self._last_called_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_called_at
            if elapsed < self._min_interval_seconds:
                time.sleep(self._min_interval_seconds - elapsed)
            self._last_called_at = time.monotonic()


_SEMANTIC_SCHOLAR_RATE_LIMITER = RateLimiter(min_interval_seconds=3.0)


def _create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(_DEFAULT_HEADERS)
    return session


def _fetch_url_with_retry(
    url: str,
    timeout: int,
    headers: dict[str, str] | None = None,
    *,
    session: requests.Session | None = None,
) -> requests.Response:
    merged_headers = {**_DEFAULT_HEADERS, **(headers or {})}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(requests.exceptions.RequestException),
        reraise=True,
    )
    def _fetch() -> requests.Response:
        if session is not None:
            response = session.get(url, timeout=timeout, headers=merged_headers)
        else:
            response = requests.get(url, timeout=timeout, headers=merged_headers)
        response.raise_for_status()
        return response

    return _fetch()


def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """
    Reconstruct abstract text from Semantic Scholar's inverted index format.

    Args:
        inverted_index: Dictionary mapping words to lists of positions

    Returns:
        Reconstructed abstract text with words in correct order
    """
    if not inverted_index:
        return ""
    # Build word list: {word: [position1, position2, ...]}
    words: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            words.append((pos, word))
    words.sort(key=lambda x: x[0])
    return " ".join(w for _, w in words)


def collect_sources(
    sources: list[Source],
    *,
    category: str,
    limit_per_source: int = 30,
    timeout: int = 15,
) -> tuple[list[Paper], list[str]]:
    """Fetch papers from all configured sources."""
    papers: list[Paper] = []
    errors: list[str] = []
    manager = get_circuit_breaker_manager()
    session = _create_session()

    try:
        for source in sources:
            try:
                breaker = manager.get_breaker(source.name)
                if source.type.lower() == "arxiv":
                    papers.extend(
                        breaker.call(
                            _collect_arxiv,
                            source,
                            category,
                            limit_per_source,
                            timeout,
                            session,
                        )
                    )
                elif source.type.lower() == "pubmed":
                    papers.extend(
                        breaker.call(
                            _collect_pubmed,
                            source,
                            category,
                            limit_per_source,
                            timeout,
                            session,
                        )
                    )
                elif source.type.lower() == "semantic_scholar":
                    papers.extend(
                        breaker.call(
                            _collect_semantic_scholar,
                            source,
                            category,
                            limit_per_source,
                            timeout,
                            session,
                            _SEMANTIC_SCHOLAR_RATE_LIMITER,
                        )
                    )
                elif source.type.lower() == "biorxiv":
                    papers.extend(
                        breaker.call(
                            _collect_biorxiv,
                            source,
                            category,
                            limit_per_source,
                            timeout,
                            session,
                        )
                    )
                elif source.type.lower() == "ssrn":
                    papers.extend(
                        breaker.call(
                            _collect_ssrn,
                            source,
                            category,
                            limit_per_source,
                            timeout,
                        )
                    )
                elif source.type.lower() == "openalex":
                    papers.extend(
                        breaker.call(
                            _collect_openalex,
                            source,
                            category,
                            limit_per_source,
                            timeout,
                            session,
                        )
                    )
                elif source.type.lower() == "crossref":
                    papers.extend(
                        breaker.call(
                            _collect_crossref,
                            source,
                            category,
                            limit_per_source,
                            timeout,
                            session,
                        )
                    )
                else:
                    errors.append(f"{source.name}: Unsupported source type '{source.type}'")
            except CircuitBreakerError:
                errors.append(f"{source.name}: Circuit breaker open (source unavailable)")
            except SourceError as exc:
                errors.append(str(exc))
            except (NetworkError, ParseError) as exc:
                errors.append(f"{source.name}: {exc}")
            except Exception as exc:
                errors.append(f"{source.name}: Unexpected error - {type(exc).__name__}: {exc}")
    finally:
        session.close()

    return papers, errors


def _collect_arxiv(
    source: Source,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Paper]:
    """Collect from arXiv API."""
    papers: list[Paper] = []
    query = source.url.split("?q=")[-1] if "?q=" in source.url else "cat:cs.AI"

    url = f"http://export.arxiv.org/api/query?search_query={query}&start=0&max_results={limit}&sortBy=submittedDate&sortOrder=descending"

    response = _fetch_url_with_retry(url, timeout, session=session)

    root = ET.fromstring(response.content)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for entry in root.findall("atom:entry", ns):
        title = entry.findtext("atom:title", "", ns).strip()
        arxiv_id = entry.findtext("atom:id", "", ns).split("/abs/")[-1]
        summary = entry.findtext("atom:summary", "", ns).strip()
        published_str = entry.findtext("atom:published", "", ns)

        authors = [
            author.findtext("atom:name", "", ns) for author in entry.findall("atom:author", ns)
        ]

        published = None
        if published_str:
            try:
                published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            except Exception:
                pass

        papers.append(
            Paper(
                title=title,
                link=f"https://arxiv.org/abs/{arxiv_id}",
                abstract=summary,
                authors=authors,
                published=published,
                source=source.name,
                category=category,
                arxiv_id=arxiv_id,
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            )
        )

    return papers


def _collect_pubmed(
    source: Source,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Paper]:
    """Collect from PubMed E-utilities."""
    papers: list[Paper] = []
    query = source.url.split("?term=")[-1] if "?term=" in source.url else "machine learning"

    search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={query}&retmax={limit}&rettype=json"

    response = _fetch_url_with_retry(search_url, timeout, session=session)
    data = response.json()

    pmids = data.get("esearchresult", {}).get("idlist", [])

    if pmids:
        fetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={','.join(pmids)}&rettype=json"
        fetch_response = _fetch_url_with_retry(fetch_url, timeout, session=session)
        fetch_data = fetch_response.json()

        for article in fetch_data.get("result", {}).get("uids", []):
            if article == "uids":
                continue
            article_data = fetch_data["result"][article]

            title = article_data.get("title", "")
            pmid = article_data.get("uid", "")
            abstract = article_data.get("abstract", "")
            authors = [a.get("name", "") for a in article_data.get("authors", [])]
            pubdate_str = article_data.get("sortpubdate") or article_data.get("pubdate") or ""
            published = _parse_pubmed_date(str(pubdate_str))

            papers.append(
                Paper(
                    title=title,
                    link=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    abstract=abstract,
                    authors=authors,
                    published=published,
                    source=source.name,
                    category=category,
                )
            )

    return papers


def _collect_semantic_scholar(
    source: Source,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
    rate_limiter: RateLimiter | None = None,
) -> list[Paper]:
    """Collect from Semantic Scholar API."""
    papers: list[Paper] = []
    query = source.url.split("?query=")[-1] if "?query=" in source.url else "machine learning"

    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={query}&limit={limit}&fields=title,authors,abstract,venue,citationCount,url,externalIds,publicationDate,year"

    active_rate_limiter = rate_limiter or _SEMANTIC_SCHOLAR_RATE_LIMITER
    active_rate_limiter.wait()
    response = _fetch_url_with_retry(url, timeout, session=session)
    data = response.json()

    for paper_data in data.get("data", []):
        title = paper_data.get("title", "")
        authors = [a.get("name", "") for a in paper_data.get("authors", [])]
        abstract = paper_data.get("abstract", "")
        venue = paper_data.get("venue", "")
        citation_count = paper_data.get("citationCount", 0)
        url = paper_data.get("url", "")
        pub_date_str = paper_data.get("publicationDate") or ""
        year_int = paper_data.get("year")
        published = _parse_iso_or_year(
            str(pub_date_str), int(year_int) if isinstance(year_int, int) else None
        )

        papers.append(
            Paper(
                title=title,
                link=url,
                abstract=abstract,
                authors=authors,
                published=published,
                source=source.name,
                category=category,
                venue=venue,
                citation_count=citation_count,
            )
        )

    return papers


def _collect_biorxiv(
    source: Source,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Paper]:
    """Collect from bioRxiv API."""
    papers: list[Paper] = []
    query = source.url.split("?query=")[-1] if "?query=" in source.url else "machine learning"

    url = f"https://api.biorxiv.org/details/biorxiv/{query}/0/{limit}"

    response = _fetch_url_with_retry(url, timeout, session=session)
    data = response.json()

    for paper_data in data.get("collection", []):
        title = paper_data.get("title", "")
        authors_raw = paper_data.get("authors")
        authors = authors_raw.split(";") if isinstance(authors_raw, str) else []
        abstract = paper_data.get("abstract", "")
        doi = paper_data.get("doi", "")
        date_str = paper_data.get("date") or ""
        published = _parse_iso_date(str(date_str))

        papers.append(
            Paper(
                title=title,
                link=f"https://www.biorxiv.org/content/{doi}",
                abstract=abstract,
                authors=[a.strip() for a in authors],
                published=published,
                source=source.name,
                category=category,
                doi=doi,
            )
        )

    return papers


def _collect_ssrn(_source: Source, _category: str, _limit: int, _timeout: int) -> list[Paper]:
    """Collect from SSRN (basic implementation)."""
    papers: list[Paper] = []
    # SSRN requires scraping; basic stub
    return papers


def _collect_openalex(
    source: Source,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Paper]:
    """Collect from OpenAlex API."""
    papers: list[Paper] = []
    query = source.url.split("?query=")[-1] if "?query=" in source.url else "machine learning"

    url = (
        f"https://api.openalex.org/works?search={query}&per-page={limit}&sort=publication_date:desc"
    )

    response = _fetch_url_with_retry(url, timeout, session=session)
    data = response.json()

    for work in data.get("results", []):
        title = work.get("title", "")
        authors = [a.get("author", {}).get("display_name", "") for a in work.get("authorships", [])]
        raw_abstract = work.get("abstract_inverted_index")
        abstract = ""
        if isinstance(raw_abstract, dict):
            abstract = _reconstruct_abstract(cast(dict[str, list[int]], raw_abstract))
        doi = work.get("doi", "").replace("https://doi.org/", "")
        url_str = work.get("url", "")
        pub_date = work.get("publication_date") or ""
        pub_year = work.get("publication_year")
        published = _parse_iso_or_year(
            str(pub_date), int(pub_year) if isinstance(pub_year, int) else None
        )

        papers.append(
            Paper(
                title=title,
                link=url_str,
                abstract=abstract,
                authors=authors,
                published=published,
                source=source.name,
                category=category,
                doi=doi if doi else None,
            )
        )

    return papers


def _collect_crossref(
    source: Source,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Paper]:
    """Collect from CrossRef API."""
    papers: list[Paper] = []
    query = source.url.split("?query=")[-1] if "?query=" in source.url else "machine learning"

    url = f"https://api.crossref.org/works?query={query}&rows={limit}&sort=published&order=desc"

    response = _fetch_url_with_retry(url, timeout, session=session)
    data = response.json()

    for item in data.get("message", {}).get("items", []):
        title = "".join(item.get("title", []))
        authors = [a.get("given", "") + " " + a.get("family", "") for a in item.get("author", [])]
        doi = item.get("DOI", "")
        url_str = item.get("URL", "")
        published: datetime | None = None
        issued_val = item.get("issued")
        if isinstance(issued_val, dict):
            issued_typed = cast(dict[str, list[list[int]]], issued_val)
            dp_outer = issued_typed.get("date-parts", [])
            if dp_outer:
                published = _parse_date_parts(dp_outer[0])

        papers.append(
            Paper(
                title=title,
                link=url_str,
                abstract="",
                authors=authors,
                published=published,
                source=source.name,
                category=category,
                doi=doi,
            )
        )

    return papers
