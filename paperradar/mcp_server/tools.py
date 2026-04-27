from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import duckdb

from ..search_index import SearchIndex


_ALLOWED_SQL = re.compile(r"^\s*(SELECT|WITH|EXPLAIN)\b", re.IGNORECASE)


def _record_table(conn: duckdb.DuckDBPyConnection) -> str:
    tables = {str(row[0]) for row in conn.execute("SHOW TABLES").fetchall()}
    if "papers" in tables:
        row = conn.execute("SELECT COUNT(*) FROM papers").fetchone()
        if row and int(row[0]) > 0:
            return "papers"
        if "articles" not in tables:
            return "papers"
    if "articles" in tables:
        return "articles"
    return "papers"


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


def handle_search(*, search_db_path: Path, db_path: Path, query: str, limit: int = 20) -> str:
    search_text = query.strip()
    if not search_text or limit <= 0:
        return "No results found."

    with SearchIndex(search_db_path) as idx:
        fts_results = idx.search(search_text, limit=limit)

    if not fts_results:
        return "No results found."

    paper_ids = [str(row[0]) for row in fts_results]
    placeholders = ", ".join("?" for _ in paper_ids)
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        if _record_table(conn) == "papers":
            rows = conn.execute(
                f"""
                SELECT paper_id, title, url, source_name, arxiv_id, doi
                FROM papers
                WHERE paper_id IN ({placeholders})
                """,
                paper_ids,
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT link AS paper_id, title, link AS url, source AS source_name,
                       NULL AS arxiv_id, NULL AS doi
                FROM articles
                WHERE link IN ({placeholders})
                """,
                paper_ids,
            ).fetchall()
    finally:
        conn.close()

    if not rows:
        lines = [f"Found {len(fts_results)} result(s):"]
        for paper_id, title in fts_results:
            lines.append(f"- {title}")
            lines.append(f"  ID: {paper_id}")
        return "\n".join(lines)

    lines = [f"Found {len(rows)} result(s):"]
    for row in rows:
        paper_id, title, url, source, arxiv_id, doi = row
        id_str = ""
        if arxiv_id:
            id_str = f" [arXiv:{arxiv_id}]"
        elif doi:
            id_str = f" [DOI:{doi}]"
        lines.append(f"- {title}{id_str}")
        lines.append(f"  Source: {source} | Link: {url}")
    return "\n".join(lines)


def handle_recent_papers(*, db_path: Path, days: int = 7, limit: int = 20) -> str:
    if limit <= 0:
        return "No recent papers found."

    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        if _record_table(conn) == "papers":
            cursor = conn.execute(
                """
                SELECT title, source_name, url, arxiv_id, doi, venue, citation_count, collected_at
                FROM papers
                WHERE collected_at >= ?
                ORDER BY collected_at DESC
                LIMIT ?
                """,
                [cutoff, limit],
            )
        else:
            cursor = conn.execute(
                """
                SELECT title, source, link, NULL AS arxiv_id, NULL AS doi, NULL AS venue,
                       NULL AS citation_count, collected_at
                FROM articles
                WHERE collected_at >= ?
                ORDER BY collected_at DESC
                LIMIT ?
                """,
                [cutoff, limit],
            )
        rows = cast(
            list[tuple[str, str, str, str | None, str | None, str | None, int | None, datetime]],
            cursor.fetchall(),
        )
    finally:
        conn.close()

    if not rows:
        return "No recent papers found."

    lines = [f"Recent papers ({len(rows)}):"]
    for row in rows:
        title, source, url, arxiv_id, doi, venue, citations, collected_at = row
        id_str = ""
        if arxiv_id:
            id_str = f" [arXiv:{arxiv_id}]"
        elif doi:
            id_str = f" [DOI:{doi}]"
        venue_str = f" ({venue})" if venue else ""
        cite_str = f" [{citations} citations]" if citations else ""
        lines.append(f"- {title}{id_str}{venue_str}{cite_str}")
        lines.append(f"  Source: {source} | {collected_at}")
        lines.append(f"  Link: {url}")
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


def handle_stats(*, db_path: Path) -> str:
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        if _record_table(conn) == "papers":
            rows = conn.execute(
                """
                SELECT source_name, COUNT(*) AS paper_count
                FROM papers
                GROUP BY source_name
                ORDER BY paper_count DESC
                """,
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()
        else:
            rows = conn.execute(
                """
                SELECT source AS source_name, COUNT(*) AS paper_count
                FROM articles
                GROUP BY source
                ORDER BY paper_count DESC
                """,
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()
    finally:
        conn.close()

    if not rows:
        return "No papers in database."

    total_count = total[0] if total else 0
    lines = [f"Paper statistics (total: {total_count}):"]
    lines.append("")
    lines.append("By source:")
    for source_name, count in rows:
        lines.append(f"  - {source_name}: {count}")
    return "\n".join(lines)


def handle_paper_by_doi(*, db_path: Path, identifier: str) -> str:
    if not identifier.strip():
        return "Error: Please provide a DOI or arXiv ID."

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        if _record_table(conn) == "papers":
            rows = conn.execute(
                """
                SELECT title, url, arxiv_id, doi, venue, citation_count,
                       source_name, publication_date, abstract
                FROM papers
                WHERE doi = ? OR arxiv_id = ? OR url = ?
                LIMIT 1
                """,
                [identifier.strip(), identifier.strip(), identifier.strip()],
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT title, link AS url, NULL AS arxiv_id, NULL AS doi, NULL AS venue,
                       NULL AS citation_count, source AS source_name, published AS publication_date,
                       summary AS abstract
                FROM articles
                WHERE link = ?
                LIMIT 1
                """,
                [identifier.strip()],
            ).fetchall()
    finally:
        conn.close()

    if not rows:
        return f"No paper found for identifier: {identifier}"

    row = rows[0]
    title, url, arxiv_id, doi, venue, citations, source, pub_date, abstract = row

    lines = [f"Paper: {title}"]
    if doi:
        lines.append(f"  DOI: {doi}")
    if arxiv_id:
        lines.append(f"  arXiv ID: {arxiv_id}")
    lines.append(f"  URL: {url}")
    if venue:
        lines.append(f"  Venue: {venue}")
    if citations is not None:
        lines.append(f"  Citations: {citations}")
    lines.append(f"  Source: {source}")
    if pub_date:
        lines.append(f"  Published: {pub_date}")
    if abstract:
        snippet = abstract[:300] + "..." if len(str(abstract)) > 300 else abstract
        lines.append(f"  Abstract: {snippet}")
    return "\n".join(lines)
