from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from html import escape
from itertools import combinations
from pathlib import Path
from typing import Any

from radar_core.ontology import build_summary_ontology_metadata
from radar_core.report_utils import (
    generate_index_html as _core_generate_index_html,
)
from radar_core.report_utils import (
    generate_report as _core_generate_report,
)

from .models import Article, CategoryConfig


def _network_chart(chart_id: str, title: str, edge_counts: Counter[tuple[str, str]]) -> dict[str, str] | None:
    if not edge_counts:
        return None

    nodes = sorted({node for edge in edge_counts for node in edge})
    if len(nodes) < 2:
        return None

    try:
        import plotly.graph_objects as go
        import plotly.io as pio

        radius = 1.0
        positions = {
            node: (
                radius * math.cos((2 * math.pi * index) / len(nodes)),
                radius * math.sin((2 * math.pi * index) / len(nodes)),
            )
            for index, node in enumerate(nodes)
        }

        edge_x: list[float | None] = []
        edge_y: list[float | None] = []
        for left, right in edge_counts:
            x0, y0 = positions[left]
            x1, y1 = positions[right]
            edge_x.extend([x0, x1, None])
            edge_y.extend([y0, y1, None])

        node_x = [positions[node][0] for node in nodes]
        node_y = [positions[node][1] for node in nodes]
        node_weights = [
            sum(weight for edge, weight in edge_counts.items() if node in edge) for node in nodes
        ]

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=edge_x,
                y=edge_y,
                mode="lines",
                line={"width": 1.5, "color": "rgba(150,190,255,0.35)"},
                hoverinfo="skip",
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=node_x,
                y=node_y,
                mode="markers+text",
                text=nodes,
                textposition="top center",
                marker={
                    "size": [max(18, min(48, 14 + weight * 5)) for weight in node_weights],
                    "color": node_weights,
                    "colorscale": "Tealgrn",
                    "line": {"width": 1, "color": "rgba(233,238,251,0.7)"},
                },
                hovertemplate="%{text}<extra></extra>",
                showlegend=False,
            )
        )
        fig.update_layout(
            height=420,
            margin={"l": 20, "r": 20, "t": 24, "b": 20},
            paper_bgcolor="rgba(10,14,23,0)",
            plot_bgcolor="rgba(14,22,42,0.5)",
            font={"color": "#e9eefb"},
            xaxis={"visible": False},
            yaxis={"visible": False},
        )
        return {
            "id": chart_id,
            "title": title,
            "config_json": pio.to_html(fig, full_html=False, include_plotlyjs="cdn"),
        }
    except Exception:
        return {
            "id": chart_id,
            "title": title,
            "config_json": '<div class="plotly-fallback">plotly network chart unavailable</div>',
        }


def _paper_network_charts(articles: Iterable[Article]) -> list[dict[str, str]]:
    topic_edges: Counter[tuple[str, str]] = Counter()
    author_edges: Counter[tuple[str, str]] = Counter()

    for article in articles:
        matched_entities: Any = getattr(article, "matched_entities", {}) or {}
        if isinstance(matched_entities, dict):
            topics = sorted(str(name) for name in matched_entities if str(name))
            topic_edges.update(tuple(pair) for pair in combinations(topics[:24], 2))

        authors_raw: Any = getattr(article, "authors", []) or []
        if isinstance(authors_raw, list):
            authors = sorted(str(author) for author in authors_raw if str(author))
            author_edges.update(tuple(pair) for pair in combinations(authors[:24], 2))

    charts: list[dict[str, str]] = []
    co_topic = _network_chart("co_topic_network", "Co-topic Network", topic_edges)
    if co_topic is not None:
        charts.append(co_topic)
    co_author = _network_chart("co_author_network", "Co-author Network", author_edges)
    if co_author is not None:
        charts.append(co_author)
    return charts


def generate_report(
    *,
    category: CategoryConfig,
    articles: Iterable[Article],
    output_path: Path,
    stats: dict[str, int],
    errors: list[str] | None = None,
    store=None,
    quality_report: Mapping[str, Any] | None = None,
) -> Path:
    """Generate HTML report (delegates to radar-core)."""
    articles_list = list(articles)
    plugin_charts = []

    # --- Universal plugins (entity heatmap + source reliability) ---
    try:
        from radar_core.plugins.entity_heatmap import get_chart_config as _heatmap_config

        _heatmap = _heatmap_config(articles=articles_list)
        if _heatmap is not None:
            plugin_charts.append(_heatmap)
    except Exception:
        pass
    try:
        from radar_core.plugins.source_reliability import get_chart_config as _reliability_config

        _reliability = _reliability_config(store=store)
        if _reliability is not None:
            plugin_charts.append(_reliability)
    except Exception:
        pass
    plugin_charts.extend(_paper_network_charts(articles_list))

    report_path = _core_generate_report(
        category=category,
        articles=articles_list,
        output_path=output_path,
        stats=stats,
        errors=errors,
        plugin_charts=plugin_charts if plugin_charts else None,
        ontology_metadata=build_summary_ontology_metadata(
            "PaperRadar",
            category_name=category.category_name,
            search_from=Path(__file__).resolve(),
        ),
    )
    if quality_report:
        for quality_report_path in _quality_panel_report_paths(
            report_path,
            category.category_name,
        ):
            _inject_paper_quality_panel(quality_report_path, quality_report)
    return report_path


def _quality_panel_report_paths(report_path: Path, category_name: str) -> list[Path]:
    paths = [report_path]
    pattern = re.compile(rf"^{re.escape(category_name)}_\d{{8}}\.html$")
    dated_reports = [
        path
        for path in report_path.parent.glob(f"{category_name}_*.html")
        if pattern.match(path.name)
    ]
    dated_reports.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    if dated_reports and dated_reports[0] not in paths:
        paths.append(dated_reports[0])
    return paths


def _inject_paper_quality_panel(
    report_path: Path,
    quality_report: Mapping[str, Any],
) -> None:
    panel = _render_paper_quality_panel(quality_report)
    html = report_path.read_text(encoding="utf-8")
    if 'id="paper-quality"' in html:
        return
    marker = '<section id="entities"'
    if marker in html:
        html = html.replace(marker, f"{panel}\n\n      {marker}", 1)
    else:
        html = html.replace("</main>", f"{panel}\n    </main>", 1)
    report_path.write_text(html, encoding="utf-8")


def _render_paper_quality_panel(quality_report: Mapping[str, Any]) -> str:
    summary = _mapping(quality_report.get("summary"))
    events = _list_of_mappings(quality_report.get("events"))[:8]
    review_items = _list_of_mappings(quality_report.get("daily_review_items"))[:8]
    chips = [
        ("events", summary.get("research_signal_event_count", 0)),
        ("paper keys", summary.get("paper_canonical_key_present_count", 0)),
        ("repo keys", summary.get("repository_canonical_key_present_count", 0)),
        ("bench keys", summary.get("benchmark_canonical_key_present_count", 0)),
        ("field gaps", summary.get("event_required_field_gap_count", 0)),
        ("review", summary.get("daily_review_item_count", 0)),
    ]
    chip_html = "\n          ".join(
        f'<span class="chip brand"><strong>{escape(label)}</strong> {escape(str(value))}</span>'
        for label, value in chips
    )
    return f"""      <section id="paper-quality" class="section" aria-label="Paper quality">
        <div class="section-hd">
          <div>
            <p class="eyebrow">Quality</p>
            <h2>Paper Quality</h2>
          </div>
          <div class="right mono">{escape(str(quality_report.get("generated_at", "")))}</div>
        </div>
        <div class="chips">
          {chip_html}
        </div>
        <div class="grid two">
          <div class="panel">
            <p class="panel-title">Research Signals</p>
            {_render_quality_events(events)}
          </div>
          <div class="panel">
            <p class="panel-title">Daily Review</p>
            {_render_quality_review(review_items)}
          </div>
        </div>
      </section>"""


def _render_quality_events(events: list[Mapping[str, Any]]) -> str:
    if not events:
        return '<p class="muted">No research signal events observed.</p>'
    rows = []
    for event in events:
        rows.append(
            "<tr>"
            f"<td>{escape(str(event.get('event_model') or ''))}</td>"
            f"<td>{escape(str(event.get('source') or ''))}</td>"
            f"<td>{escape(str(event.get('canonical_key') or ''))}</td>"
            f"<td>{escape(str(event.get('citation_count') if event.get('citation_count') is not None else ''))}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Model</th><th>Source</th><th>Canonical key</th><th>Citations</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _render_quality_review(items: list[Mapping[str, Any]]) -> str:
    if not items:
        return '<p class="muted">No review items.</p>'
    rows = []
    for item in items:
        gaps = item.get("required_field_gaps")
        if isinstance(gaps, list):
            detail = ", ".join(str(gap) for gap in gaps)
        else:
            detail = str(
                item.get("activation_gate")
                or item.get("canonical_key")
                or item.get("latest_title")
                or item.get("title")
                or ""
            )
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('reason') or ''))}</td>"
            f"<td>{escape(str(item.get('event_model') or ''))}</td>"
            f"<td>{escape(str(item.get('source') or ''))}</td>"
            f"<td>{escape(detail)}</td>"
            "</tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Reason</th><th>Model</th><th>Source</th><th>Detail</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def generate_index_html(
    report_dir: Path,
    summaries_dir: Path | None = None,
) -> Path:
    """Generate index.html (delegates to radar-core)."""
    radar_name = "Paper Radar"
    return _core_generate_index_html(report_dir, radar_name)
