from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from .models import Article


def _json_default(value: object) -> str:
    """Serialize datetime/date values (e.g. nested in ontology) as ISO 8601 strings."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


class RawLogger:
    def __init__(self, raw_dir: Path):
        self.raw_dir: Path = raw_dir

    def log(
        self,
        articles: Iterable[Article],
        *,
        source_name: str,
        run_id: str | None = None,
    ) -> Path:
        now = datetime.now(UTC)
        date_dir = self.raw_dir / now.date().isoformat()
        safe_source_name = source_name.replace("/", "_").replace("\\", "_")

        if run_id is not None:
            output_path = date_dir / f"{safe_source_name}_{run_id}.jsonl"
        else:
            output_path = date_dir / f"{safe_source_name}.jsonl"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        existing_links: set[str] = set()
        if run_id is not None and output_path.exists():
            try:
                with output_path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if line.strip():
                            record = json.loads(line)
                            existing_links.add(record.get("link", ""))
            except (OSError, json.JSONDecodeError):
                pass

        with output_path.open("a", encoding="utf-8") as handle:
            for article in articles:
                if run_id is not None and article.link in existing_links:
                    continue

                record = {
                    "title": article.title,
                    "link": article.link,
                    "summary": article.summary,
                    "published": article.published.isoformat() if article.published else None,
                    "source": article.source,
                    "category": article.category,
                    "matched_entities": article.matched_entities,
                    "logged_at": now.isoformat(),
                }
                ontology = getattr(article, "ontology", None)
                if ontology:
                    record["ontology"] = ontology
                _ = handle.write(json.dumps(record, ensure_ascii=False, default=_json_default))
                _ = handle.write("\n")
                if run_id is not None:
                    existing_links.add(article.link)

        return output_path

    def log_skip(
        self,
        *,
        source_name: str,
        required_env: str | Sequence[str],
    ) -> Path:
        """Record a keyless skip. The file stores environment variable names only."""
        if isinstance(required_env, str):
            env_names = [required_env]
        else:
            env_names = [str(name) for name in required_env]
        cleaned: list[str] = []
        for name in env_names:
            candidate = name.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", candidate):
                raise ValueError("required_env must be an environment variable name")
            cleaned.append(candidate)
        if not cleaned:
            raise ValueError("required_env must be an environment variable name")

        now = datetime.now(UTC)
        date_dir = self.raw_dir / now.date().isoformat()
        date_dir.mkdir(parents=True, exist_ok=True)
        safe_source_name = source_name.replace("/", "_").replace("\\", "_")
        output_path = date_dir / f"{safe_source_name}.skip.json"
        payload = {
            "record_type": "skip",
            "source_id": source_name,
            "status": "skipped_missing_env",
            "required_env": cleaned if len(cleaned) > 1 else cleaned[0],
            "skip_reason": ", ".join(f"{name} not set" for name in cleaned),
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return output_path
