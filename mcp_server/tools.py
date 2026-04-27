from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import duckdb

from paperradar.nl_query import parse_query
from paperradar.search_index import SearchIndex


_ALLOWED_SQL = re.compile(r"^\s*(SELECT|WITH|EXPLAIN)\b", re.IGNORECASE)


def _format_rows(columns: list[str], rows: list[tuple[object, ...]]) -> str:
    if not rows:
        return "No rows returned."
    text_rows = [tuple("" if value is None else str(value) for value in row) for row in rows]
    widths = [len(name) for name in columns]
    for row in text_rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    header = " | ".join(col.ljust(widths[idx]) for idx, col in enumerate(columns))
    divider = "-+-".join("-" * widths[idx] for idx in range(len(columns)))
    body = [
        " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(row)) for row in text_rows
    ]
    return "\n".join([header, divider, *body])


def _filter_links_by_days(*, db_path: Path, links: list[str], days: int) -> set[str]:
    if not links:
        return set()
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    placeholders = ", ".join("?" for _ in links)
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = cast(
            list[tuple[str]],
            conn.execute(
                f"""
                SELECT link
                FROM articles
                WHERE collected_at >= ? AND link IN ({placeholders})
                """,
                [cutoff, *links],
            ).fetchall(),
        )
    finally:
        conn.close()
    return {str(row[0]) for row in rows}


def handle_search(*, search_db_path: Path, db_path: Path, query: str, limit: int = 20) -> str:
    parsed = parse_query(query)
    effective_limit = parsed.limit if parsed.limit is not None else limit
    if effective_limit <= 0:
        return "No results found."
    search_text = parsed.search_text or query.strip()
    if not search_text:
        return "No results found."

    with SearchIndex(search_db_path) as idx:
        rows = idx.search(search_text, limit=effective_limit)

    results = [(str(row[0]), str(row[1])) for row in rows]
    if parsed.days is not None:
        allowed_links = _filter_links_by_days(
            db_path=db_path,
            links=[link for link, _title in results],
            days=parsed.days,
        )
        results = [(link, title) for link, title in results if link in allowed_links]

    if not results:
        return "No results found."

    lines = [f"Found {len(results)} result(s):"]
    for link, title in results:
        lines.append(f"- {title}")
        lines.append(f"  Link: {link}")
    return "\n".join(lines)


def handle_recent_updates(*, db_path: Path, days: int = 7, limit: int = 20) -> str:
    if limit <= 0:
        return "No recent updates found."

    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = cast(
            list[tuple[str, str, str, datetime]],
            conn.execute(
                """
                SELECT title, source, link, collected_at
                FROM articles
                WHERE collected_at >= ?
                ORDER BY collected_at DESC
                LIMIT ?
                """,
                [cutoff, limit],
            ).fetchall(),
        )
    finally:
        conn.close()

    if not rows:
        return "No recent updates found."

    lines = [f"Recent updates ({len(rows)}):"]
    for title, source, link, collected_at in rows:
        lines.append(f"- {title} | {source} | {collected_at} | {link}")
    return "\n".join(lines)


def handle_sql(*, db_path: Path, query: str) -> str:
    if not _ALLOWED_SQL.match(query):
        return "Error: Only SELECT/WITH/EXPLAIN queries are allowed."

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        cursor = conn.execute(query)
        rows = cursor.fetchall()
        description = cursor.description
        columns = [str(desc[0]) for desc in description] if description else ["result"]
        return _format_rows(columns, rows)
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"
    finally:
        conn.close()


def handle_top_trends(*, db_path: Path, days: int = 7, limit: int = 10) -> str:
    if limit <= 0:
        return "No trend data available."

    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT entities_json
            FROM articles
            WHERE collected_at >= ?
            """,
            [cutoff],
        ).fetchall()
        entity_rows = cast(list[tuple[str | None]], rows)
    finally:
        conn.close()

    counts: Counter[str] = Counter()
    for row in entity_rows:
        raw_entities = row[0]
        if not raw_entities:
            continue
        try:
            data = cast(dict[str, object], json.loads(str(raw_entities)))
        except json.JSONDecodeError:
            continue
        for entity_name, matched in data.items():
            if isinstance(matched, list):
                counts[entity_name] += len(cast(list[object], matched))

    if not counts:
        return "No trend data available."

    lines = ["Top trends:"]
    for entity_name, count in counts.most_common(limit):
        lines.append(f"- {entity_name}: {count}")
    return "\n".join(lines)


def handle_price_watch(*, threshold: float = 0.0) -> str:
    _ = threshold
    return "Not available in template project"
