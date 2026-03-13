from __future__ import annotations

import shutil
from collections import Counter
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any, cast

import networkx as nx
import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader

from .models import CategoryConfig, Paper


DEFAULT_NETWORK_NODE_LIMIT = 80


def _normalize_label(value: object) -> str:
    text = str(value).strip()
    if not text:
        return ""
    return " ".join(text.split())


def _build_cooccurrence_network(
    groups: list[list[object]],
    max_nodes: int = DEFAULT_NETWORK_NODE_LIMIT,
) -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    frequency: Counter[str] = Counter()
    normalized_groups: list[list[str]] = []

    for group in groups:
        unique_names: set[str] = set()
        for raw_name in group:
            normalized = _normalize_label(raw_name)
            if normalized:
                unique_names.add(normalized)
        names = sorted(unique_names)
        if not names:
            continue
        frequency.update(names)
        normalized_groups.append(names)

    top_nodes = {
        name
        for name, _ in sorted(frequency.items(), key=lambda item: (-item[1], item[0]))[:max_nodes]
    }

    node_counts: Counter[str] = Counter()
    edge_counts: Counter[tuple[str, str]] = Counter()
    for names in normalized_groups:
        selected = sorted([name for name in names if name in top_nodes])
        if not selected:
            continue
        node_counts.update(selected)
        if len(selected) < 2:
            continue
        for left, right in combinations(selected, 2):
            edge_counts[(left, right)] += 1

    return dict(node_counts), dict(edge_counts)


def _build_network_html(
    node_counts: dict[str, int],
    edge_counts: dict[tuple[str, str], int],
    include_plotlyjs: str | bool,
) -> str:
    if not node_counts:
        return '<div class="network-empty">Not enough co-occurrence data.</div>'

    graph = cast(Any, nx.Graph())
    for node, frequency in node_counts.items():
        graph.add_node(node, frequency=frequency)

    for (left, right), weight in edge_counts.items():
        if left in node_counts and right in node_counts and left != right:
            graph.add_edge(left, right, weight=weight)

    raw_positions: Any
    if graph.number_of_nodes() == 1:
        raw_positions = nx.circular_layout(graph)
    else:
        raw_positions = nx.spring_layout(graph, seed=42, weight="weight")

    positions: dict[str, tuple[float, float]] = {}
    for node in node_counts:
        point = raw_positions[node]
        positions[node] = (float(point[0]), float(point[1]))

    edge_x: list[float] = []
    edge_y: list[float] = []
    node_degree: Counter[str] = Counter()
    for left, right in cast(list[tuple[str, str]], list(graph.edges())):
        left_pos = positions[left]
        right_pos = positions[right]
        edge_x.extend([left_pos[0], right_pos[0], float("nan")])
        edge_y.extend([left_pos[1], right_pos[1], float("nan")])
        node_degree[left] += 1
        node_degree[right] += 1

    edge_trace: Any = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        hoverinfo="skip",
        line={"width": 1.0, "color": "rgba(148,163,184,0.5)"},
    )

    max_frequency = max(node_counts.values())
    node_x: list[float] = []
    node_y: list[float] = []
    marker_sizes: list[float] = []
    marker_colors: list[int] = []
    hover_text: list[str] = []
    labels: list[str] = []

    ordered_nodes = sorted(node_counts.keys(), key=lambda name: (-node_counts[name], name.lower()))
    for node in ordered_nodes:
        pos = positions[node]
        frequency = node_counts[node]
        degree = node_degree[node]
        node_x.append(pos[0])
        node_y.append(pos[1])
        marker_sizes.append(12.0 + (frequency / max_frequency) * 24.0)
        marker_colors.append(degree)
        labels.append(node)
        hover_text.append(f"{node}<br>Frequency: {frequency}<br>Connections: {degree}")

    node_trace: Any = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        text=labels,
        textposition="top center",
        hoverinfo="text",
        hovertext=hover_text,
        marker={
            "size": marker_sizes,
            "color": marker_colors,
            "colorscale": "Blues",
            "showscale": False,
            "line": {"width": 1.2, "color": "rgba(30,41,59,0.85)"},
            "opacity": 0.94,
        },
        textfont={"size": 10, "color": "#1e293b"},
    )

    fig: Any = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        showlegend=False,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        hovermode="closest",
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis={"showgrid": False, "showticklabels": False, "zeroline": False},
        yaxis={"showgrid": False, "showticklabels": False, "zeroline": False},
    )

    return cast(
        str,
        fig.to_html(
            full_html=False,
            include_plotlyjs=include_plotlyjs,
            config={"displayModeBar": False, "responsive": True},
        ),
    )


def _build_topic_network_html(
    entities_json: list[dict[str, list[str]]],
    include_plotlyjs: str | bool,
) -> str:
    groups: list[list[object]] = [
        list(entity_map.keys()) for entity_map in entities_json if entity_map
    ]
    node_counts, edge_counts = _build_cooccurrence_network(groups)
    return _build_network_html(node_counts, edge_counts, include_plotlyjs)


def _build_author_network_html(
    articles: list[Paper],
    include_plotlyjs: str | bool,
) -> str:
    groups: list[list[object]] = [list(paper.authors) for paper in articles if paper.authors]
    node_counts, edge_counts = _build_cooccurrence_network(groups)
    return _build_network_html(node_counts, edge_counts, include_plotlyjs)


_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _get_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=False,
    )


def _copy_static_assets(report_dir: Path) -> None:
    src = _TEMPLATE_DIR / "static"
    dst = report_dir / "static"
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        _ = shutil.copytree(str(src), str(dst))


def generate_report(
    category: CategoryConfig,
    articles: list[Paper],
    output_path: Path,
    stats: dict[str, int],
    errors: list[str],
) -> Path:
    """Generate HTML report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    articles_json: list[dict[str, Any]] = []
    entities_json: list[dict[str, list[str]]] = []
    for paper in articles:
        matched_entities = paper.matched_entities or {}
        paper_data: dict[str, Any] = {
            "title": paper.title,
            "link": paper.link,
            "source": paper.source,
            "published": paper.published.isoformat() if paper.published else None,
            "published_at": paper.published.isoformat() if paper.published else None,
            "abstract": paper.abstract,
            "authors": paper.authors,
            "venue": paper.venue,
            "matched_entities": matched_entities,
            "collected_at": paper.collected_at.isoformat()
            if hasattr(paper, "collected_at") and paper.collected_at
            else None,
        }
        articles_json.append(paper_data)
        entities_json.append(matched_entities)

    co_topic_network_html = _build_topic_network_html(entities_json, include_plotlyjs="cdn")
    co_author_network_html = _build_author_network_html(articles, include_plotlyjs="cdn")

    template = _get_jinja_env().get_template("report.html")
    html = template.render(
        category=category,
        articles=articles,
        articles_json=articles_json,
        co_topic_network_html=co_topic_network_html,
        co_author_network_html=co_author_network_html,
        stats=stats,
        errors=errors,
        generated_at=datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S"),
    )

    _ = output_path.write_text(html, encoding="utf-8")

    now_ts = datetime.now(UTC)
    date_stamp = now_ts.strftime("%Y%m%d")
    dated_name = f"{category.category_name}_{date_stamp}.html"
    dated_path = output_path.parent / dated_name
    _ = dated_path.write_text(html, encoding="utf-8")

    _copy_static_assets(output_path.parent)

    return output_path


def generate_index_html(report_dir: Path) -> Path:
    """Generate an index.html that lists all available report files."""
    report_dir.mkdir(parents=True, exist_ok=True)

    html_files = sorted(
        [f for f in report_dir.glob("*.html") if f.name != "index.html"],
        key=lambda p: p.name,
    )

    reports: list[dict[str, str]] = []
    for html_file in html_files:
        name = html_file.stem
        display_name = name.replace("_report", "").replace("_", " ").title()
        reports.append({"filename": html_file.name, "display_name": display_name})

    template = _get_jinja_env().get_template("index.html")
    html = template.render(
        reports=reports,
        generated_at=datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )

    index_path = report_dir / "index.html"
    _ = index_path.write_text(html, encoding="utf-8")
    return index_path
