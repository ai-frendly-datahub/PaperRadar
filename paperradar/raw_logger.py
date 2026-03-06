from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class RawLogger:
    """Log raw paper data to JSONL."""
    
    def __init__(self, raw_data_dir: Path) -> None:
        self.raw_data_dir = raw_data_dir
    
    def log(self, papers: list, source_name: str) -> Path:
        """Log papers to JSONL file."""
        today = datetime.now().strftime("%Y-%m-%d")
        log_dir = self.raw_data_dir / today
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f"{source_name}.jsonl"
        
        with open(log_file, "a") as f:
            for paper in papers:
                record = {
                    "title": paper.title,
                    "link": paper.link,
                    "abstract": paper.abstract,
                    "authors": paper.authors,
                    "source": paper.source,
                    "arxiv_id": paper.arxiv_id,
                    "doi": paper.doi,
                    "venue": paper.venue,
                    "citation_count": paper.citation_count,
                    "timestamp": datetime.now().isoformat(),
                }
                f.write(json.dumps(record) + "\n")
        
        return log_file
