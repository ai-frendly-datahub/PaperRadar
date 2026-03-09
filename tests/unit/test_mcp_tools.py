from __future__ import annotations
from typing import Optional

from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from importlib import import_module
from pathlib import Path

import duckdb


SearchIndex = import_module("paperradar.search_index").SearchIndex
tools = import_module("paperradar.mcp_server.tools")


def _init_papers_table(db_path: Path) -> None:
    conn = duckdb.connect(str(db_path))
    try:
        _ = conn.execute(
            """
            CREATE TABLE papers (
                paper_id VARCHAR PRIMARY KEY,
                title VARCHAR NOT NULL,
                url VARCHAR,
                source_name VARCHAR,
                arxiv_id VARCHAR,
                doi VARCHAR,
                venue VARCHAR,
                citation_count INTEGER,
                publication_date DATE,
                abstract VARCHAR,
                collected_at TIMESTAMP
            )
            """
        )
    finally:
        conn.close()


def _seed_paper(
    *,
    db_path: Path,
    paper_id: str,
    title: str,
    url: str,
    source_name: str,
    arxiv_id: Optional[str] = None,
    doi: Optional[str] = None,
    venue: Optional[str] = None,
    citation_count: Optional[int] = None,
    publication_date: Optional[str] = None,
    abstract: Optional[str] = None,
    collected_at: Optional[datetime] = None,
) -> None:
    conn = duckdb.connect(str(db_path))
    try:
        _ = conn.execute(
            """
            INSERT INTO papers (
                paper_id, title, url, source_name, arxiv_id, doi,
                venue, citation_count, publication_date, abstract, collected_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                paper_id,
                title,
                url,
                source_name,
                arxiv_id,
                doi,
                venue,
                citation_count,
                publication_date,
                abstract,
                collected_at or datetime.now(tz=UTC),
            ],
        )
    finally:
        conn.close()


def test_handle_search(tmp_path: Path) -> None:
    db_path = tmp_path / "papers.duckdb"
    search_db_path = tmp_path / "search.db"
    _init_papers_table(db_path)

    now = datetime.now(tz=UTC)
    recent_paper_id = "arxiv:2301.12345"
    old_paper_id = "arxiv:2201.54321"

    _seed_paper(
        db_path=db_path,
        paper_id=recent_paper_id,
        title="Recent machine learning advances",
        url="https://arxiv.org/abs/2301.12345",
        source_name="arXiv",
        arxiv_id="2301.12345",
        doi="10.48550/arXiv.2301.12345",
        abstract="This paper explores recent advances in machine learning.",
        collected_at=now - timedelta(days=2),
    )
    _seed_paper(
        db_path=db_path,
        paper_id=old_paper_id,
        title="Old machine learning paper",
        url="https://arxiv.org/abs/2201.54321",
        source_name="arXiv",
        arxiv_id="2201.54321",
        doi="10.48550/arXiv.2201.54321",
        abstract="This is an old paper about machine learning.",
        collected_at=now - timedelta(days=20),
    )

    with SearchIndex(search_db_path) as idx:
        idx.upsert(
            recent_paper_id,
            "Recent machine learning advances",
            "This paper explores recent advances in machine learning.",
            "",
        )
        idx.upsert(
            old_paper_id,
            "Old machine learning paper",
            "This is an old paper about machine learning.",
            "",
        )

    output = tools.handle_search(
        search_db_path=search_db_path,
        db_path=db_path,
        query="recent machine learning",
        limit=10,
    )

    assert "Recent machine learning advances" in output
    assert "Old machine learning paper" not in output
    assert "arXiv" in output or "2301" in output


def test_handle_recent_papers(tmp_path: Path) -> None:
    db_path = tmp_path / "papers.duckdb"
    _init_papers_table(db_path)
    now = datetime.now(tz=UTC)

    _seed_paper(
        db_path=db_path,
        paper_id="arxiv:2301.99999",
        title="Very recent paper",
        url="https://arxiv.org/abs/2301.99999",
        source_name="arXiv",
        arxiv_id="2301.99999",
        venue="NeurIPS 2023",
        citation_count=15,
        abstract="A very recent paper.",
        collected_at=now - timedelta(days=2),
    )
    _seed_paper(
        db_path=db_path,
        paper_id="arxiv:2210.00001",
        title="Older paper",
        url="https://arxiv.org/abs/2210.00001",
        source_name="arXiv",
        arxiv_id="2210.00001",
        venue="ICML 2022",
        citation_count=5,
        abstract="An older paper.",
        collected_at=now - timedelta(days=20),
    )

    output = tools.handle_recent_papers(db_path=db_path, days=7, limit=10)

    assert "Very recent paper" in output
    assert "Older paper" not in output
    assert "NeurIPS 2023" in output or "15" in output


def test_handle_sql_select(tmp_path: Path) -> None:
    db_path = tmp_path / "papers.duckdb"
    _init_papers_table(db_path)
    now = datetime.now(tz=UTC)

    _seed_paper(
        db_path=db_path,
        paper_id="arxiv:2301.11111",
        title="Paper 1",
        url="https://arxiv.org/abs/2301.11111",
        source_name="arXiv",
        collected_at=now,
    )
    _seed_paper(
        db_path=db_path,
        paper_id="arxiv:2301.22222",
        title="Paper 2",
        url="https://arxiv.org/abs/2301.22222",
        source_name="Semantic Scholar",
        collected_at=now,
    )
    _seed_paper(
        db_path=db_path,
        paper_id="arxiv:2301.33333",
        title="Paper 3",
        url="https://arxiv.org/abs/2301.33333",
        source_name="PubMed",
        collected_at=now,
    )

    output = tools.handle_sql(db_path=db_path, query="SELECT COUNT(*) AS total FROM papers")

    assert "total" in output
    assert "3" in output


def test_handle_sql_blocked(tmp_path: Path) -> None:
    db_path = tmp_path / "papers.duckdb"
    _init_papers_table(db_path)

    output = tools.handle_sql(db_path=db_path, query="DROP TABLE papers")

    assert "Only SELECT/WITH/EXPLAIN queries are allowed" in output


def test_handle_stats(tmp_path: Path) -> None:
    db_path = tmp_path / "papers.duckdb"
    _init_papers_table(db_path)
    now = datetime.now(tz=UTC)

    _seed_paper(
        db_path=db_path,
        paper_id="arxiv:2301.44444",
        title="arXiv paper 1",
        url="https://arxiv.org/abs/2301.44444",
        source_name="arXiv",
        collected_at=now,
    )
    _seed_paper(
        db_path=db_path,
        paper_id="arxiv:2301.55555",
        title="arXiv paper 2",
        url="https://arxiv.org/abs/2301.55555",
        source_name="arXiv",
        collected_at=now,
    )
    _seed_paper(
        db_path=db_path,
        paper_id="ss:12345",
        title="Semantic Scholar paper",
        url="https://semanticscholar.org/paper/12345",
        source_name="Semantic Scholar",
        collected_at=now,
    )

    output = tools.handle_stats(db_path=db_path)

    assert "arXiv" in output
    assert "2" in output
    assert "Semantic Scholar" in output


def test_handle_paper_by_doi(tmp_path: Path) -> None:
    db_path = tmp_path / "papers.duckdb"
    _init_papers_table(db_path)
    now = datetime.now(tz=UTC)

    test_doi = "10.1234/test.doi"
    _seed_paper(
        db_path=db_path,
        paper_id="doi:10.1234/test.doi",
        title="Paper with DOI",
        url="https://example.com/paper",
        source_name="CrossRef",
        doi=test_doi,
        venue="Nature",
        citation_count=42,
        abstract="This is a test paper.",
        collected_at=now,
    )

    output = tools.handle_paper_by_doi(db_path=db_path, identifier=test_doi)

    assert "Paper with DOI" in output
    assert test_doi in output
    assert "not found" not in output.lower()


def test_handle_paper_by_arxiv_id(tmp_path: Path) -> None:
    db_path = tmp_path / "papers.duckdb"
    _init_papers_table(db_path)
    now = datetime.now(tz=UTC)

    test_arxiv_id = "2301.12345"
    _seed_paper(
        db_path=db_path,
        paper_id="arxiv:2301.12345",
        title="arXiv paper lookup",
        url="https://arxiv.org/abs/2301.12345",
        source_name="arXiv",
        arxiv_id=test_arxiv_id,
        doi="10.48550/arXiv.2301.12345",
        venue="NeurIPS 2023",
        citation_count=8,
        abstract="Test abstract for arXiv paper.",
        collected_at=now,
    )

    output = tools.handle_paper_by_doi(db_path=db_path, identifier=test_arxiv_id)

    assert "arXiv paper lookup" in output
    assert test_arxiv_id in output
    assert "not found" not in output.lower()
