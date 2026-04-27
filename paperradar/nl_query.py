from __future__ import annotations

from radar_core.nl_query import ParsedQuery, parse_query


class NLQueryParser:
    """Parse natural language queries for papers."""

    def __init__(self):
        self.keywords = {
            "recent": ["recent", "latest", "new"],
            "citations": ["cited", "citations", "popular"],
            "author": ["by", "author", "from"],
            "venue": ["in", "venue", "conference", "journal"],
        }

    def parse(self, query: str) -> dict:
        """Parse natural language query."""
        query_lower = query.lower()

        result = {
            "text": query,
            "filters": {},
        }

        for filter_type, keywords in self.keywords.items():
            for keyword in keywords:
                if keyword in query_lower:
                    result["filters"][filter_type] = True

        return result
