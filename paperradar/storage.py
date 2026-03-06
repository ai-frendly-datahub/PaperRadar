from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb


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
    
    def upsert_papers(self, papers: list) -> None:
        """Upsert papers into database."""
        for paper in papers:
            paper_id = paper.doi or paper.arxiv_id or paper.link
            
            self.conn.execute("""
                INSERT INTO papers (
                    paper_id, title, authors, abstract, url, pdf_url,
                    arxiv_id, doi, venue, publication_date, citation_count,
                    categories, keywords, collected_at, source_name, category
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (paper_id) DO UPDATE SET
                    citation_count = EXCLUDED.citation_count,
                    collected_at = EXCLUDED.collected_at
            """, [
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
                datetime.now(timezone.utc),
                paper.source,
                paper.category,
            ])
        
        self.conn.commit()
    
    def recent_papers(self, category: str, days: int = 7) -> list:
        """Get recent papers."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        result = self.conn.execute("""
            SELECT * FROM papers
            WHERE category = ? AND collected_at >= ?
            ORDER BY collected_at DESC
        """, [category, cutoff]).fetchall()
        
        return result
    
    def delete_older_than(self, days: int) -> int:
        """Delete papers older than N days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        self.conn.execute("""
            DELETE FROM papers WHERE collected_at < ?
        """, [cutoff])
        
        self.conn.commit()
        return 0
    
    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
