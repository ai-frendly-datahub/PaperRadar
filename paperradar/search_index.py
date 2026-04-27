from __future__ import annotations

import sqlite3
from pathlib import Path


class SearchIndex:
    """SQLite FTS5 search index for papers."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize FTS5 table."""
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
                paper_id UNINDEXED,
                title,
                abstract,
                authors
            )
        """)
        self.conn.commit()

    def upsert(self, paper_id: str, title: str, abstract: str, authors: str = "") -> None:
        """Add or update paper in search index."""
        self.conn.execute(
            """
            DELETE FROM papers_fts WHERE paper_id = ?
        """,
            [paper_id],
        )

        self.conn.execute(
            """
            INSERT INTO papers_fts (paper_id, title, abstract, authors)
            VALUES (?, ?, ?, ?)
        """,
            [paper_id, title, abstract, authors],
        )

        self.conn.commit()

    def search(self, query: str, limit: int = 50) -> list[tuple]:
        """Search papers."""
        result = self.conn.execute(
            """
            SELECT paper_id, title FROM papers_fts
            WHERE papers_fts MATCH ?
            LIMIT ?
        """,
            [query, limit],
        ).fetchall()

        return result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()
