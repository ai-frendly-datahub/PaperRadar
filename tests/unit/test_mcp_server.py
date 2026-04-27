from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest


def _init_articles_db(db_path: Path, *, title: str = "Snapshot paper") -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE articles (
                id BIGINT PRIMARY KEY,
                category TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL UNIQUE,
                summary TEXT,
                published TIMESTAMP,
                collected_at TIMESTAMP NOT NULL,
                entities_json TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO articles (id, category, source, title, link, summary, published, collected_at, entities_json)
            VALUES (1, 'research', 'Test Source', ?, 'https://example.com/paper', 'summary', NULL, ?, '{}')
            """,
            [title, datetime.now(UTC).replace(tzinfo=None)],
        )
    finally:
        conn.close()


def _init_empty_health_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE crawl_health (source TEXT, status TEXT)")
    finally:
        conn.close()


@pytest.mark.unit
def test_mcp_db_path_falls_back_to_latest_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from paperradar.mcp_server import server

    db_path = tmp_path / "data" / "papers.duckdb"
    older = tmp_path / "data" / "snapshots" / "2026-04-09" / "papers.duckdb"
    newer = tmp_path / "data" / "snapshots" / "2026-04-10" / "papers.duckdb"
    _init_empty_health_db(db_path)
    _init_articles_db(older, title="Older paper")
    _init_articles_db(newer, title="Newer paper")

    monkeypatch.delenv("RADAR_DB_PATH", raising=False)
    monkeypatch.setattr(server, "load_settings", lambda: SimpleNamespace(database_path=db_path))

    assert server._db_path() == newer


@pytest.mark.unit
def test_mcp_tools_read_article_table_snapshot(tmp_path: Path) -> None:
    from paperradar.mcp_server.tools import (
        handle_paper_by_doi,
        handle_recent_papers,
        handle_stats,
    )

    db_path = tmp_path / "papers.duckdb"
    _init_articles_db(db_path)

    recent = handle_recent_papers(db_path=db_path, days=7, limit=5)
    stats = handle_stats(db_path=db_path)
    detail = handle_paper_by_doi(db_path=db_path, identifier="https://example.com/paper")

    assert "Snapshot paper" in recent
    assert "Test Source: 1" in stats
    assert "Paper: Snapshot paper" in detail
