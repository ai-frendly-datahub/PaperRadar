from __future__ import annotations

from pathlib import Path

import duckdb

from radar_core.exceptions import StorageError
from radar_core.storage import RadarStorage as _RadarStorage

from .date_storage import cleanup_date_directories, snapshot_database


class RadarStorage(_RadarStorage):
    def create_daily_snapshot(self, snapshot_dir: str | None = None):
        snapshot_root = Path(snapshot_dir) if snapshot_dir else self.db_path.parent / "daily"
        _ = self.conn.execute("CHECKPOINT")
        self.conn.close()
        try:
            return snapshot_database(self.db_path, snapshot_root=snapshot_root)
        finally:
            self.conn = duckdb.connect(str(self.db_path))
            self._ensure_tables()

    def cleanup_old_snapshots(self, keep_days: int) -> int:
        return cleanup_date_directories(self.db_path.parent / "daily", keep_days=keep_days)

    def upsert_papers(self, papers):
        return self.upsert_articles(papers)

    def recent_papers(self, category, days=7):
        return [
            (
                paper.link,
                paper.title,
                paper.summary,
                paper.published,
                paper.source,
                paper.category,
            )
            for paper in self.recent_articles(category, days=days)
        ]


__all__ = ["RadarStorage", "StorageError"]
