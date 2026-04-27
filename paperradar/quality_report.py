from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import CategoryConfig, Source


DEFAULT_EVENT_MODELS = [
    "paper_release",
    "citation_snapshot",
    "code_repository",
    "benchmark_result",
]
SUMMARY_LABELS = [
    "Paper ID",
    "arXiv",
    "DOI",
    "Repository",
    "Repo",
    "GitHub repository",
    "Citation count",
    "Citations",
    "Benchmark",
    "Benchmark name",
    "Metric",
    "Metric name",
    "Metric value",
    "Score",
    "Dataset",
]


def build_quality_report(
    *,
    category: CategoryConfig,
    articles: Iterable[Any],
    errors: Iterable[str] | None = None,
    quality_config: Mapping[str, object] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = _as_utc(generated_at or datetime.now(UTC))
    article_rows = list(articles)
    error_rows = [str(error) for error in (errors or [])]
    quality = _dict(quality_config or {}, "data_quality")
    event_model_config = _dict(quality, "event_models")
    tracked_models = _tracked_event_models(quality)

    events = _build_events(
        articles=article_rows,
        sources=category.sources,
        tracked_models=tracked_models,
        event_model_config=event_model_config,
    )
    source_rows = [
        _build_source_row(
            source=source,
            articles=article_rows,
            events=events,
            errors=error_rows,
            quality=quality,
            tracked_models=tracked_models,
            generated_at=generated,
        )
        for source in category.sources
    ]

    status_counts = Counter(str(row["status"]) for row in source_rows)
    event_counts = Counter(str(row["event_model"]) for row in events)
    summary: dict[str, Any] = {
        "total_sources": len(source_rows),
        "enabled_sources": sum(1 for row in source_rows if row["enabled"]),
        "tracked_sources": sum(1 for row in source_rows if row["tracked"]),
        "fresh_sources": status_counts.get("fresh", 0),
        "stale_sources": status_counts.get("stale", 0),
        "missing_sources": status_counts.get("missing", 0),
        "missing_event_sources": status_counts.get("missing_event", 0),
        "unknown_event_date_sources": status_counts.get("unknown_event_date", 0),
        "not_tracked_sources": status_counts.get("not_tracked", 0),
        "skipped_disabled_sources": status_counts.get("skipped_disabled", 0),
        "collection_error_count": len(error_rows),
    }
    for event_model in tracked_models:
        summary[f"{event_model}_events"] = event_counts.get(event_model, 0)
    summary.update(_event_quality_summary(events, source_rows, quality_config or {}, tracked_models))
    daily_review_items = _daily_review_items(events, source_rows, quality_config or {}, tracked_models)
    summary["daily_review_item_count"] = len(daily_review_items)

    return {
        "category": category.category_name,
        "generated_at": generated.isoformat(),
        "scope_note": (
            f"{category.display_name} quality report is generated from repo-local "
            "category data_quality metadata and recent stored articles. Operational "
            "backlog sources remain separate until dedicated source-level fields are collected."
        ),
        "summary": summary,
        "sources": source_rows,
        "events": events,
        "daily_review_items": daily_review_items,
        "source_backlog": (quality_config or {}).get("source_backlog", {}),
        "errors": error_rows,
    }


def write_quality_report(
    report: Mapping[str, object],
    *,
    output_dir: Path,
    category_name: str,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _parse_datetime(str(report.get("generated_at") or "")) or datetime.now(UTC)
    date_stamp = _as_utc(generated_at).strftime("%Y%m%d")
    latest_path = output_dir / f"{category_name}_quality.json"
    dated_path = output_dir / f"{category_name}_{date_stamp}_quality.json"
    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    latest_path.write_text(encoded + "\n", encoding="utf-8")
    dated_path.write_text(encoded + "\n", encoding="utf-8")
    return {"latest": latest_path, "dated": dated_path}


def _build_events(
    *,
    articles: list[Any],
    sources: list[Source],
    tracked_models: list[str],
    event_model_config: Mapping[str, object],
) -> list[dict[str, Any]]:
    source_map = {source.name: source for source in sources}
    rows: list[dict[str, Any]] = []
    for article in articles:
        source = source_map.get(_article_source(article))
        if source is None:
            continue
        event_model = _source_event_model(source, tracked_models)
        if event_model not in tracked_models:
            continue
        event_at = _event_datetime(article, event_model=event_model)
        rows.append(
            _event_row(
                article=article,
                source=source,
                event_model=event_model,
                event_at=event_at,
                event_model_config=event_model_config,
            )
        )
    return rows


def _event_row(
    *,
    article: Any,
    source: Source,
    event_model: str,
    event_at: datetime | None,
    event_model_config: Mapping[str, object],
) -> dict[str, Any]:
    paper_id = _paper_id(article)
    arxiv_id = _arxiv_id(article)
    doi = _doi(article)
    repository = _repository(article, source)
    repo_host, repo_owner, repo_name = _repository_parts(repository)
    citation_count = _citation_count(article)
    benchmark_name = _benchmark_name(article)
    metric_name = _metric_name(article)
    metric_value = _metric_value(article)
    row: dict[str, Any] = {
        "source": source.name,
        "source_type": source.type,
        "trust_tier": source.trust_tier,
        "producer_role": source.producer_role,
        "event_model": event_model,
        "title": _article_title(article),
        "url": _article_link(article),
        "source_url": _article_link(article) or source.url,
        "event_at": event_at.isoformat() if event_at else None,
        "event_key": _event_key(article, source, event_model, event_at),
        "paper_id": paper_id,
        "arxiv_id": arxiv_id,
        "doi": doi,
        "normalized_title": _normalized_title(article),
        "repository": repository,
        "repository_host": repo_host,
        "repository_owner": repo_owner,
        "repository_name": repo_name,
        "citation_count": citation_count,
        "benchmark_name": benchmark_name,
        "metric_name": metric_name,
        "metric_value": metric_value,
        "dataset": _dataset(article),
        "venue": _article_field(article, "venue"),
        "matched_entities": _article_entities(article),
        "required_field_proxy": _required_field_proxy(
            article=article,
            source=source,
            event_model=event_model,
            event_model_config=event_model_config,
        ),
    }
    canonical_key, canonical_status = _canonical_key(row)
    row["canonical_key"] = canonical_key
    row["canonical_key_status"] = canonical_status
    row["required_field_gaps"] = _required_field_gaps(
        event_model=event_model,
        row=row,
        event_model_config=event_model_config,
    )
    return row


def _build_source_row(
    *,
    source: Source,
    articles: list[Any],
    events: list[dict[str, Any]],
    errors: list[str],
    quality: Mapping[str, object],
    tracked_models: list[str],
    generated_at: datetime,
) -> dict[str, Any]:
    source_articles = [article for article in articles if _article_source(article) == source.name]
    event_model = _source_event_model(source, tracked_models)
    source_events = [
        row
        for row in events
        if row["source"] == source.name and row["event_model"] == event_model
    ]
    latest_event = _latest_event(source_events)
    latest_event_at = (
        _parse_datetime(str(latest_event.get("event_at") or "")) if latest_event else None
    )
    sla_days = _source_sla_days(source, event_model, _dict(quality, "freshness_sla"))
    age_days = _age_days(generated_at, latest_event_at) if latest_event_at else None
    source_errors = [error for error in errors if error.startswith(f"{source.name}:")]

    status = _source_status(
        source=source,
        tracked=event_model in tracked_models,
        article_count=len(source_articles),
        event_count=len(source_events),
        latest_event_at=latest_event_at,
        sla_days=sla_days,
        age_days=age_days,
    )

    return {
        "source": source.name,
        "source_type": source.type,
        "enabled": source.enabled,
        "trust_tier": source.trust_tier,
        "content_type": source.content_type,
        "collection_tier": source.collection_tier,
        "producer_role": source.producer_role,
        "info_purpose": source.info_purpose,
        "tracked": event_model in tracked_models,
        "event_model": event_model,
        "freshness_sla_days": sla_days,
        "status": status,
        "article_count": len(source_articles),
        "event_count": len(source_events),
        "latest_event_at": latest_event_at.isoformat() if latest_event_at else None,
        "age_days": round(age_days, 2) if age_days is not None else None,
        "latest_title": str(latest_event.get("title", "")) if latest_event else "",
        "latest_url": str(latest_event.get("url", "")) if latest_event else "",
        "latest_required_field_proxy": (
            latest_event.get("required_field_proxy", {}) if latest_event else {}
        ),
        "latest_canonical_key": str(latest_event.get("canonical_key", "")) if latest_event else "",
        "latest_required_field_gaps": latest_event.get("required_field_gaps", []) if latest_event else [],
        "skip_reason": str(source.config.get("skip_reason", "")),
        "reenable_gate": str(source.config.get("reenable_gate", "")),
        "errors": source_errors,
    }


def _tracked_event_models(quality: Mapping[str, object]) -> list[str]:
    outputs = _dict(quality, "quality_outputs")
    raw = outputs.get("tracked_event_models")
    if isinstance(raw, list):
        values = [str(value).strip() for value in raw if str(value).strip()]
        if values:
            return values
    event_models = _dict(quality, "event_models")
    if event_models:
        return list(event_models.keys())
    return list(DEFAULT_EVENT_MODELS)


def _source_event_model(source: Source, tracked_models: list[str]) -> str:
    raw = source.config.get("event_model")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()

    for value in source.info_purpose:
        if value in tracked_models:
            return value

    text = " ".join(
        [
            source.name,
            source.type,
            source.content_type,
            source.collection_tier,
            source.producer_role,
            " ".join(source.info_purpose),
            " ".join(str(value) for value in source.config.values()),
        ]
    ).lower()
    type_value = source.type.lower()

    model_rules = [
        ("benchmark", "benchmark_result"),
        ("leaderboard", "benchmark_result"),
        ("citation", "citation_snapshot"),
        ("repository", "code_repository"),
        ("github", "code_repository"),
        ("code", "code_repository"),
        ("preprint", "paper_release"),
        ("academic", "paper_release"),
        ("research", "paper_release"),
        ("transaction", "transaction_record"),
        ("price", "transaction_record"),
        ("presale", "presale_competition"),
        ("competition", "presale_competition"),
        ("listing", "listing_inventory"),
        ("inventory", "listing_inventory"),
        ("permit", "permit_completion"),
        ("completion", "permit_completion"),
        ("reservation", "reservation_slot"),
        ("slot", "reservation_slot"),
        ("ticket", "ticket_price"),
        ("weather", "weather_context"),
    ]
    if type_value == "api" and "wait_time_snapshot" in tracked_models:
        return "wait_time_snapshot"
    for token, event_model in model_rules:
        if token in text and event_model in tracked_models:
            return event_model
    return ""


def _source_sla_days(
    source: Source,
    event_model: str,
    freshness_sla: Mapping[str, object],
) -> float | None:
    raw_source_sla = source.config.get("freshness_sla_days")
    parsed_source_sla = _as_float(raw_source_sla)
    if parsed_source_sla is not None:
        return parsed_source_sla

    for key in (f"{event_model}_days", f"{event_model}_day"):
        parsed_days = _as_float(freshness_sla.get(key))
        if parsed_days is not None:
            return parsed_days
    for key in (f"{event_model}_hours", f"{event_model}_hour"):
        parsed_hours = _as_float(freshness_sla.get(key))
        if parsed_hours is not None:
            return parsed_hours / 24.0
    return None


def _source_status(
    *,
    source: Source,
    tracked: bool,
    article_count: int,
    event_count: int,
    latest_event_at: datetime | None,
    sla_days: float | None,
    age_days: float | None,
) -> str:
    if not source.enabled:
        return "skipped_disabled"
    if not tracked:
        return "not_tracked"
    if article_count == 0:
        return "missing"
    if event_count == 0:
        return "missing_event"
    if latest_event_at is None or age_days is None:
        return "unknown_event_date"
    if sla_days is not None and age_days > sla_days:
        return "stale"
    return "fresh"


def _event_quality_summary(
    events: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    quality_config: Mapping[str, object],
    tracked_models: list[str],
) -> dict[str, int]:
    backlog = _source_backlog_items(quality_config)
    return {
        "research_signal_event_count": len(events),
        "paper_canonical_key_present_count": sum(
            1
            for row in events
            if row.get("event_model") in {"paper_release", "citation_snapshot"}
            and str(row.get("canonical_key", "")).startswith("paper:")
        ),
        "repository_canonical_key_present_count": sum(
            1
            for row in events
            if row.get("event_model") == "code_repository"
            and str(row.get("canonical_key", "")).startswith("repository:")
        ),
        "benchmark_canonical_key_present_count": sum(
            1
            for row in events
            if row.get("event_model") == "benchmark_result"
            and str(row.get("canonical_key", "")).startswith("benchmark:")
        ),
        "title_proxy_key_count": sum(
            1 for row in events if row.get("canonical_key_status") == "title_proxy"
        ),
        "missing_canonical_key_count": sum(
            1 for row in events if row.get("canonical_key_status") == "missing"
        ),
        "citation_count_present_count": sum(
            1 for row in events if row.get("citation_count") is not None
        ),
        "code_repository_present_count": sum(
            1 for row in events if str(row.get("repository") or "")
        ),
        "benchmark_metric_present_count": sum(
            1
            for row in events
            if row.get("benchmark_name") and row.get("metric_name") and row.get("metric_value")
        ),
        "event_required_field_gap_count": sum(
            len(row.get("required_field_gaps", []))
            for row in events
            if isinstance(row.get("required_field_gaps"), list)
        ),
        "tracked_source_gap_count": sum(
            1
            for row in source_rows
            if row.get("tracked")
            and row.get("status") in {"missing", "missing_event", "unknown_event_date", "stale"}
        ),
        "missing_event_model_count": sum(
            1
            for event_model in tracked_models
            if not any(row.get("event_model") == event_model for row in events)
        ),
        "source_backlog_candidate_count": len(backlog),
    }


def _daily_review_items(
    events: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    quality_config: Mapping[str, object],
    tracked_models: list[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in events:
        gaps = row.get("required_field_gaps")
        if isinstance(gaps, list) and gaps:
            items.append(
                {
                    "reason": "missing_required_fields",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "title": row.get("title"),
                    "event_key": row.get("event_key"),
                    "required_field_gaps": gaps,
                }
            )
        if row.get("canonical_key_status") == "missing":
            items.append(
                {
                    "reason": "missing_canonical_key",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "title": row.get("title"),
                    "event_key": row.get("event_key"),
                }
            )
        elif row.get("canonical_key_status") == "title_proxy":
            items.append(
                {
                    "reason": "title_proxy_canonical_key",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "title": row.get("title"),
                    "event_key": row.get("event_key"),
                    "canonical_key": row.get("canonical_key"),
                }
            )

    for row in source_rows:
        if row.get("tracked") and row.get("status") in {
            "missing",
            "missing_event",
            "unknown_event_date",
            "stale",
        }:
            items.append(
                {
                    "reason": f"source_{row.get('status')}",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "latest_title": row.get("latest_title"),
                    "age_days": row.get("age_days"),
                }
            )

    for event_model in tracked_models:
        if not any(row.get("event_model") == event_model for row in events):
            items.append({"reason": "missing_event_model", "event_model": event_model})

    for backlog_item in _source_backlog_items(quality_config):
        items.append(
            {
                "reason": "source_backlog_pending",
                "event_model": backlog_item.get("signal_type", ""),
                "source": backlog_item.get("name", ""),
                "activation_gate": backlog_item.get("activation_gate", ""),
            }
        )
    return items[:50]


def _source_backlog_items(quality_config: Mapping[str, object]) -> list[Mapping[str, Any]]:
    backlog = _dict(quality_config, "source_backlog")
    candidates = backlog.get("operational_candidates")
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, Mapping)]


def _required_field_proxy(
    *,
    article: Any,
    source: Source,
    event_model: str,
    event_model_config: Mapping[str, object],
) -> dict[str, bool]:
    event_config = _dict(event_model_config, event_model)
    raw_fields = event_config.get("required_fields")
    if not isinstance(raw_fields, list):
        return {}
    return {
        str(field): _has_required_field(article, source, str(field))
        for field in raw_fields
        if str(field).strip()
    }


def _has_required_field(article: Any, source: Source, field: str) -> bool:
    normalized = field.lower()
    title = _article_title(article)
    link = _article_link(article)
    summary = _article_summary(article)
    text = f"{title} {summary} {link}".lower()
    entities = _article_entities(article)
    entity_values = " ".join(
        str(value).lower()
        for values in entities.values()
        for value in (values if isinstance(values, list) else [values])
    )

    if normalized in {"source", "source_name"}:
        return bool(source.name)
    if normalized in {"source_url", "evidence_url"}:
        return bool(link or source.url)
    if normalized in {"title", "normalized_title"}:
        return bool(title)
    if normalized in {"paper_id", "project_id", "facility_id", "attraction_id", "service_id"}:
        return bool(link or title)
    if normalized in {"repository", "host", "owner", "repo"}:
        return bool(_repository(article, source))
    if normalized in {"arxiv_id", "doi"}:
        return bool(_arxiv_id(article) if normalized == "arxiv_id" else _doi(article))
    if normalized in {"citation_count"}:
        return _citation_count(article) is not None
    if normalized in {"benchmark_name"}:
        return bool(_benchmark_name(article))
    if normalized in {"metric_name"}:
        return bool(_metric_name(article))
    if normalized in {"metric_value"}:
        return _metric_value(article) is not None
    if normalized in {"metric_value", "wait_minutes", "price", "transaction_price"}:
        return bool(re.search(r"\d", text))
    if normalized in {"currency"}:
        return any(token in text for token in ("usd", "krw", "$", "원"))
    if normalized in {"region_code", "complex_name", "property_type"}:
        return bool(entity_values or title)
    if normalized.endswith("_date") or normalized.endswith("_time") or normalized == "observed_at":
        return _event_datetime(article) is not None
    return normalized in text or normalized in entity_values


def _required_field_gaps(
    *,
    event_model: str,
    row: Mapping[str, Any],
    event_model_config: Mapping[str, object],
) -> list[str]:
    event_config = _dict(event_model_config, event_model)
    raw_fields = event_config.get("required_fields")
    if not isinstance(raw_fields, list):
        return []
    proxy = row.get("required_field_proxy")
    proxy_values = proxy if isinstance(proxy, Mapping) else {}
    return [
        str(field)
        for field in raw_fields
        if str(field).strip() and not _field_present(str(field), row, proxy_values)
    ]


def _field_present(field: str, row: Mapping[str, Any], proxy: Mapping[str, object]) -> bool:
    if proxy.get(field) is True:
        return True
    normalized = field.lower()
    aliases = {
        "paper_id": ("paper_id", "arxiv_id", "doi", "normalized_title"),
        "title": ("title",),
        "source": ("source",),
        "source_url": ("source_url", "url"),
        "citation_count": ("citation_count",),
        "repository": ("repository",),
        "benchmark_name": ("benchmark_name",),
        "metric_name": ("metric_name",),
        "metric_value": ("metric_value",),
    }.get(normalized, (normalized,))
    return any(_truthy(row.get(alias)) for alias in aliases)


def _canonical_key(row: Mapping[str, Any]) -> tuple[str, str]:
    event_model = str(row.get("event_model") or "")
    paper_key = _paper_key_from_row(row)
    repository = str(row.get("repository") or "")
    repo_host = str(row.get("repository_host") or "")
    repo_owner = str(row.get("repository_owner") or "")
    repo_name = str(row.get("repository_name") or "")
    benchmark_name = str(row.get("benchmark_name") or "")
    metric_name = str(row.get("metric_name") or "")
    metric_value = row.get("metric_value")

    if event_model in {"paper_release", "citation_snapshot"}:
        if paper_key:
            status = "complete" if paper_key.startswith(("doi:", "arxiv:")) else "title_proxy"
            return f"paper:{paper_key}", status
        return "", "missing"

    if event_model == "code_repository":
        if repository and repo_host and repo_owner and repo_name:
            suffix = f":paper:{_slug(paper_key)}" if paper_key else ""
            return f"repository:{_slug(repo_host)}:{_slug(repo_owner)}:{_slug(repo_name)}{suffix}", "complete"
        if paper_key:
            return f"paper:{paper_key}", "title_proxy"
        return "", "missing"

    if event_model == "benchmark_result":
        if paper_key and benchmark_name and metric_name and metric_value is not None:
            return (
                f"benchmark:{_slug(paper_key)}:{_slug(benchmark_name)}:"
                f"{_slug(metric_name)}:{_slug(metric_value)}"
            ), "complete"
        if paper_key:
            return f"paper:{paper_key}", "title_proxy"
        return "", "missing"

    return (f"paper:{paper_key}", "complete") if paper_key else ("", "missing")


def _paper_key_from_row(row: Mapping[str, Any]) -> str:
    doi = str(row.get("doi") or "")
    if doi:
        return f"doi:{_slug(doi)}"
    arxiv_id = str(row.get("arxiv_id") or "")
    if arxiv_id:
        return f"arxiv:{_slug(arxiv_id)}"
    normalized_title = str(row.get("normalized_title") or "")
    if normalized_title:
        return f"title:{normalized_title}"
    return ""


def _paper_id(article: Any) -> str:
    return _first_non_empty(_doi(article), _arxiv_id(article), _article_link(article), _normalized_title(article))


def _arxiv_id(article: Any) -> str:
    explicit = _first_non_empty(_article_field(article, "arxiv_id"), _summary_value(article, "arXiv"))
    if explicit:
        return _clean_arxiv_id(explicit)
    match = re.search(
        r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)",
        _article_link(article),
        flags=re.IGNORECASE,
    )
    return _clean_arxiv_id(match.group(1)) if match else ""


def _doi(article: Any) -> str:
    explicit = _first_non_empty(_article_field(article, "doi"), _summary_value(article, "DOI"))
    if explicit:
        return _clean_doi(explicit)
    match = re.search(
        r"(?:doi\.org/|doi:\s*)(10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
        f"{_article_link(article)} {_article_summary(article)}",
        flags=re.IGNORECASE,
    )
    return _clean_doi(match.group(1)) if match else ""


def _repository(article: Any, source: Source) -> str:
    configured = _first_non_empty(
        source.config.get("repository"),
        source.config.get("canonical_repository"),
        source.config.get("github_repository"),
    )
    if configured:
        return _clean_repository(configured)
    labeled = _summary_value(article, "Repository", "Repo", "GitHub repository")
    if labeled:
        return _clean_repository(labeled)
    text = f"{_article_title(article)} {_article_summary(article)} {_article_link(article)}"
    match = re.search(
        r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return _clean_repository(f"github.com/{match.group(1)}/{match.group(2)}")
    return ""


def _repository_parts(repository: str) -> tuple[str, str, str]:
    if not repository:
        return "", "", ""
    value = repository.strip()
    if "/" in value and not value.startswith(("http://", "https://")):
        value = f"https://{value}" if "." in value.split("/", 1)[0] else f"https://github.com/{value}"
    parsed = urlparse(value)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return parsed.netloc.lower(), "", ""
    return parsed.netloc.lower(), parts[0], parts[1].removesuffix(".git")


def _citation_count(article: Any) -> int | None:
    value = getattr(article, "citation_count", None)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return _int_value(_summary_value(article, "Citation count", "Citations"))


def _benchmark_name(article: Any) -> str:
    labeled = _summary_value(article, "Benchmark", "Benchmark name")
    if labeled:
        return labeled
    title = _article_title(article)
    if "benchmark" in title.lower():
        return title
    return ""


def _metric_name(article: Any) -> str:
    return _summary_value(article, "Metric", "Metric name", "Score")


def _metric_value(article: Any) -> str | None:
    return _summary_value(article, "Metric value", "Score") or None


def _dataset(article: Any) -> str:
    return _summary_value(article, "Dataset")


def _event_key(article: Any, source: Source, event_model: str, event_at: datetime | None) -> str:
    date_text = _as_utc(event_at).strftime("%Y-%m-%d") if event_at else "undated"
    basis = _paper_id(article) or _article_link(article) or f"{source.name}:{_article_title(article)}"
    return f"{event_model}:{_slug(source.name)}:{_digest(basis)}:{date_text}"


def _normalized_title(article: Any) -> str:
    return _slug(_article_title(article))[:96]


def _article_field(article: Any, field: str) -> str:
    value = getattr(article, field, "")
    if value is None:
        return ""
    return str(value).strip()


def _summary_value(article: Any, *labels: str) -> str:
    text = " ".join(f"{_article_title(article)} {_article_summary(article)}".split())
    for label in labels:
        match = re.search(rf"\b{re.escape(label)}\s*[:=]\s*", text, flags=re.IGNORECASE)
        if not match:
            continue
        start = match.end()
        end = len(text)
        for next_label in SUMMARY_LABELS:
            next_match = re.search(
                rf"\b{re.escape(next_label)}\s*[:=]\s*",
                text[start:],
                flags=re.IGNORECASE,
            )
            if next_match:
                end = min(end, start + next_match.start())
        return text[start:end].strip(" \t\r\n.;,")
    return ""


def _clean_arxiv_id(value: str) -> str:
    cleaned = value.strip().removeprefix("arXiv:").removeprefix("arxiv:").removesuffix(".pdf")
    match = re.search(
        r"([0-9]{4}\.[0-9]{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).removesuffix(".pdf")
    return cleaned.strip(" .;,")


def _clean_doi(value: str) -> str:
    return value.strip().removeprefix("doi:").removeprefix("https://doi.org/").strip(" .;,").lower()


def _clean_repository(value: str) -> str:
    cleaned = value.strip().strip("`'\" ")
    cleaned = re.sub(r"[).,;]+$", "", cleaned).removesuffix(".git")
    parsed = urlparse(cleaned if "://" in cleaned else f"https://{cleaned}")
    if parsed.netloc:
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2:
            return f"{parsed.netloc.lower()}/{parts[0]}/{parts[1].removesuffix('.git')}"
    return cleaned


def _int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        match = re.search(r"\d[\d,]*", value)
        if match:
            return int(match.group(0).replace(",", ""))
    return None


def _truthy(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | tuple | set | dict):
        return bool(value)
    return True


def _first_non_empty(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _slug(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text).strip("-")
    if text:
        return text
    return f"u-{_digest(str(value))}"


def _digest(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _latest_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    dated: list[tuple[datetime, dict[str, Any]]] = []
    undated: list[dict[str, Any]] = []
    for row in events:
        parsed = _parse_datetime(str(row.get("event_at") or ""))
        if parsed is None:
            undated.append(row)
        else:
            dated.append((parsed, row))
    if dated:
        return max(dated, key=lambda row: row[0])[1]
    return undated[0] if undated else None


def _event_datetime(article: Any, *, event_model: str = "") -> datetime | None:
    published = getattr(article, "published", None)
    collected = getattr(article, "collected_at", None)
    if event_model == "citation_snapshot" and isinstance(collected, datetime):
        value = collected
    else:
        value = published if isinstance(published, datetime) else collected
    return _as_utc(value) if isinstance(value, datetime) else None


def _article_source(article: Any) -> str:
    return str(getattr(article, "source", "") or "")


def _article_title(article: Any) -> str:
    return str(getattr(article, "title", "") or "")


def _article_link(article: Any) -> str:
    return str(getattr(article, "link", "") or "")


def _article_summary(article: Any) -> str:
    return str(getattr(article, "summary", "") or getattr(article, "abstract", "") or "")


def _article_entities(article: Any) -> dict[str, Any]:
    raw = getattr(article, "matched_entities", {})
    return raw if isinstance(raw, dict) else {}


def _dict(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    raw = value.get(key)
    if isinstance(raw, Mapping):
        return {str(k): v for k, v in raw.items()}
    return {}


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_datetime(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _age_days(generated_at: datetime, event_at: datetime) -> float:
    return max(0.0, (_as_utc(generated_at) - _as_utc(event_at)).total_seconds() / 86400)
