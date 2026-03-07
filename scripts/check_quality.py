#!/usr/bin/env python3
"""Run DuckDB data quality checks."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from paperradar.common.quality_checks import run_all_checks


def main() -> None:
    db_path = PROJECT_ROOT / "data" / "papers.duckdb"
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    with duckdb.connect(str(db_path), read_only=True) as con:
        run_all_checks(
            con,
            table_name="papers",
            null_conditions={
                "title": "title IS NULL OR title = ''",
                "url": "url IS NULL OR url = ''",
                "abstract": "abstract IS NULL OR abstract = ''",
                "publication_date": "publication_date IS NULL",
            },
            text_columns=["title", "abstract"],
            url_column="url",
            date_column="publication_date",
        )


if __name__ == "__main__":
    main()
