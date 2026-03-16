from __future__ import annotations

from radar_core.storage import RadarStorage as _RadarStorage
from radar_core.exceptions import StorageError


class RadarStorage(_RadarStorage):
    def upsert_papers(self, papers):
        return self.upsert_articles(papers)

    def recent_papers(self, category, days=7):
        return self.recent_articles(category, days=days)


__all__ = ["RadarStorage", "StorageError"]
