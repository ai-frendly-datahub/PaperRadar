from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from xml.etree import ElementTree as ET

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from .models import Paper, Source


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
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

    for source in sources:
        try:
            if source.type.lower() == "arxiv":
                papers.extend(_collect_arxiv(source, category, limit_per_source, timeout))
            elif source.type.lower() == "pubmed":
                papers.extend(_collect_pubmed(source, category, limit_per_source, timeout))
            elif source.type.lower() == "semantic_scholar":
                papers.extend(_collect_semantic_scholar(source, category, limit_per_source, timeout))
            elif source.type.lower() == "biorxiv":
                papers.extend(_collect_biorxiv(source, category, limit_per_source, timeout))
            elif source.type.lower() == "ssrn":
                papers.extend(_collect_ssrn(source, category, limit_per_source, timeout))
            elif source.type.lower() == "openalex":
                papers.extend(_collect_openalex(source, category, limit_per_source, timeout))
            elif source.type.lower() == "crossref":
                papers.extend(_collect_crossref(source, category, limit_per_source, timeout))
            else:
                errors.append(f"{source.name}: Unsupported source type '{source.type}'")
        except Exception as exc:
            errors.append(f"{source.name}: {exc}")

    return papers, errors


def _collect_arxiv(source: Source, category: str, limit: int, timeout: int) -> list[Paper]:
    """Collect from arXiv API."""
    papers: list[Paper] = []
    query = source.url.split("?q=")[-1] if "?q=" in source.url else "cat:cs.AI"
    
    url = f"http://export.arxiv.org/api/query?search_query={query}&start=0&max_results={limit}&sortBy=submittedDate&sortOrder=descending"
    
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    
    root = ET.fromstring(response.content)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    
    for entry in root.findall("atom:entry", ns):
        title = entry.findtext("atom:title", "", ns).strip()
        arxiv_id = entry.findtext("atom:id", "", ns).split("/abs/")[-1]
        summary = entry.findtext("atom:summary", "", ns).strip()
        published_str = entry.findtext("atom:published", "", ns)
        
        authors = [author.findtext("atom:name", "", ns) for author in entry.findall("atom:author", ns)]
        
        published = None
        if published_str:
            try:
                published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            except Exception:
                pass
        
        papers.append(Paper(
            title=title,
            link=f"https://arxiv.org/abs/{arxiv_id}",
            abstract=summary,
            authors=authors,
            published=published,
            source=source.name,
            category=category,
            arxiv_id=arxiv_id,
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        ))
    
    return papers


def _collect_pubmed(source: Source, category: str, limit: int, timeout: int) -> list[Paper]:
    """Collect from PubMed E-utilities."""
    papers: list[Paper] = []
    query = source.url.split("?term=")[-1] if "?term=" in source.url else "machine learning"
    
    search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={query}&retmax={limit}&rettype=json"
    
    response = requests.get(search_url, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    
    pmids = data.get("esearchresult", {}).get("idlist", [])
    
    if pmids:
        fetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={','.join(pmids)}&rettype=json"
        fetch_response = requests.get(fetch_url, timeout=timeout)
        fetch_response.raise_for_status()
        fetch_data = fetch_response.json()
        
        for article in fetch_data.get("result", {}).get("uids", []):
            if article == "uids":
                continue
            article_data = fetch_data["result"][article]
            
            title = article_data.get("title", "")
            pmid = article_data.get("uid", "")
            abstract = article_data.get("abstract", "")
            authors = [a.get("name", "") for a in article_data.get("authors", [])]
            
            papers.append(Paper(
                title=title,
                link=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                abstract=abstract,
                authors=authors,
                published=None,
                source=source.name,
                category=category,
            ))
    
    return papers


def _collect_semantic_scholar(source: Source, category: str, limit: int, timeout: int) -> list[Paper]:
    """Collect from Semantic Scholar API."""
    papers: list[Paper] = []
    query = source.url.split("?query=")[-1] if "?query=" in source.url else "machine learning"
    
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={query}&limit={limit}&fields=title,authors,abstract,venue,citationCount,url,externalIds"
    
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    
    for paper_data in data.get("data", []):
        title = paper_data.get("title", "")
        authors = [a.get("name", "") for a in paper_data.get("authors", [])]
        abstract = paper_data.get("abstract", "")
        venue = paper_data.get("venue", "")
        citation_count = paper_data.get("citationCount", 0)
        url = paper_data.get("url", "")
        
        papers.append(Paper(
            title=title,
            link=url,
            abstract=abstract,
            authors=authors,
            published=None,
            source=source.name,
            category=category,
            venue=venue,
            citation_count=citation_count,
        ))
    
    return papers


def _collect_biorxiv(source: Source, category: str, limit: int, timeout: int) -> list[Paper]:
    """Collect from bioRxiv API."""
    papers: list[Paper] = []
    query = source.url.split("?query=")[-1] if "?query=" in source.url else "machine learning"
    
    url = f"https://api.biorxiv.org/details/biorxiv/{query}/0/{limit}"
    
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    
    for paper_data in data.get("collection", []):
        title = paper_data.get("title", "")
        authors = paper_data.get("authors", "").split(";") if paper_data.get("authors") else []
        abstract = paper_data.get("abstract", "")
        doi = paper_data.get("doi", "")
        
        papers.append(Paper(
            title=title,
            link=f"https://www.biorxiv.org/content/{doi}",
            abstract=abstract,
            authors=[a.strip() for a in authors],
            published=None,
            source=source.name,
            category=category,
            doi=doi,
        ))
    
    return papers


def _collect_ssrn(source: Source, category: str, limit: int, timeout: int) -> list[Paper]:
    """Collect from SSRN (basic implementation)."""
    papers: list[Paper] = []
    # SSRN requires scraping; basic stub
    return papers


def _collect_openalex(source: Source, category: str, limit: int, timeout: int) -> list[Paper]:
    """Collect from OpenAlex API."""
    papers: list[Paper] = []
    query = source.url.split("?query=")[-1] if "?query=" in source.url else "machine learning"
    
    url = f"https://api.openalex.org/works?search={query}&per-page={limit}&sort=publication_date:desc"
    
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    
    for work in data.get("results", []):
        title = work.get("title", "")
        authors = [a.get("author", {}).get("display_name", "") for a in work.get("authorships", [])]
        abstract = work.get("abstract_inverted_index", {})
        doi = work.get("doi", "").replace("https://doi.org/", "")
        url_str = work.get("url", "")
        
        papers.append(Paper(
            title=title,
            link=url_str,
            abstract=str(abstract),
            authors=authors,
            published=None,
            source=source.name,
            category=category,
            doi=doi if doi else None,
        ))
    
    return papers


def _collect_crossref(source: Source, category: str, limit: int, timeout: int) -> list[Paper]:
    """Collect from CrossRef API."""
    papers: list[Paper] = []
    query = source.url.split("?query=")[-1] if "?query=" in source.url else "machine learning"
    
    url = f"https://api.crossref.org/works?query={query}&rows={limit}&sort=published&order=desc"
    
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    
    for item in data.get("message", {}).get("items", []):
        title = "".join(item.get("title", []))
        authors = [a.get("given", "") + " " + a.get("family", "") for a in item.get("author", [])]
        doi = item.get("DOI", "")
        url_str = item.get("URL", "")
        
        papers.append(Paper(
            title=title,
            link=url_str,
            abstract="",
            authors=authors,
            published=None,
            source=source.name,
            category=category,
            doi=doi,
        ))
    
    return papers
