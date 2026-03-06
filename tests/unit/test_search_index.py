from __future__ import annotations

import tempfile
from pathlib import Path

from paperradar.search_index import SearchIndex


def test_search_index_upsert():
    """Test search index upsert."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "search.db"
        
        with SearchIndex(db_path) as idx:
            idx.upsert(
                "paper1",
                "Deep Learning Fundamentals",
                "This paper covers deep learning basics",
                "John Doe",
            )
            
            results = idx.search("deep learning")
            assert len(results) > 0


def test_search_index_multiple():
    """Test multiple papers in search index."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "search.db"
        
        with SearchIndex(db_path) as idx:
            idx.upsert("p1", "Transformers", "About transformers", "Author 1")
            idx.upsert("p2", "BERT Models", "About BERT", "Author 2")
            
            results = idx.search("transformers")
            assert len(results) >= 1
