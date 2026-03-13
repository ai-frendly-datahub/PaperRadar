from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from .models import Paper


class RadarStorage:
    """DuckDB storage for papers."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                paper_id VARCHAR PRIMARY KEY,
                title VARCHAR NOT NULL,
                authors VARCHAR[],
                abstract VARCHAR,
                url VARCHAR,
                pdf_url VARCHAR,
                arxiv_id VARCHAR,
                doi VARCHAR,
                venue VARCHAR,
                publication_date DATE,
                citation_count INTEGER,
                categories VARCHAR[],
                keywords VARCHAR[],
                collected_at TIMESTAMP,
                source_name VARCHAR,
                category VARCHAR
            )
        """)

    def upsert_papers(self, papers: list[Paper]) -> None:
        """Upsert papers into database."""
        for paper in papers:
            paper_id = paper.doi or paper.arxiv_id or paper.link

            self.conn.execute(
                """
                INSERT INTO papers (
                    paper_id, title, authors, abstract, url, pdf_url,
                    arxiv_id, doi, venue, publication_date, citation_count,
                    categories, keywords, collected_at, source_name, category
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (paper_id) DO UPDATE SET
                    citation_count = EXCLUDED.citation_count,
                    collected_at = EXCLUDED.collected_at
            """,
                [
                    paper_id,
                    paper.title,
                    paper.authors,
                    paper.abstract,
                    paper.link,
                    paper.pdf_url,
                    paper.arxiv_id,
                    paper.doi,
                    paper.venue,
                    paper.published.date() if paper.published else None,
                    paper.citation_count,
                    paper.categories,
                    paper.keywords,
                    datetime.now(UTC),
                    paper.source,
                    paper.category,
                ],
            )

        self.conn.commit()

    def recent_papers(self, category: str, days: int = 7) -> list[tuple[object, ...]]:
        """Get recent papers."""
        cutoff = datetime.now(UTC) - timedelta(days=days)

        result = self.conn.execute(
            """
            SELECT * FROM papers
            WHERE category = ? AND collected_at >= ?
            ORDER BY collected_at DESC
        """,
            [category, cutoff],
        ).fetchall()

        return result

    def delete_older_than(self, days: int) -> int:
        """Delete papers older than N days."""
        cutoff = datetime.now(UTC) - timedelta(days=days)

        self.conn.execute(
            """
            DELETE FROM papers WHERE collected_at < ?
        """,
            [cutoff],
        )

        self.conn.commit()
        return 0

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()

    def create_daily_snapshot(self, snapshot_dir: str | None = None) -> Path | None:
        from .date_storage import snapshot_database

        snapshot_root = Path(snapshot_dir) if snapshot_dir else self.db_path.parent / "daily"
        return snapshot_database(self.db_path, snapshot_root=snapshot_root)

    def cleanup_old_snapshots(self, snapshot_dir: str | None = None, keep_days: int = 90) -> int:
        from .date_storage import cleanup_date_directories

        snapshot_root = Path(snapshot_dir) if snapshot_dir else self.db_path.parent / "daily"
        return cleanup_date_directories(snapshot_root, keep_days=keep_days)
