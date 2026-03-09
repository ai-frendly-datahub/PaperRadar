from __future__ import annotations

from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Union, cast

import networkx as nx
import plotly.graph_objects as go
from jinja2 import Template

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
    include_plotlyjs: Union[str, bool],
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
    include_plotlyjs: Union[str, bool],
) -> str:
    groups: list[list[object]] = [
        list(entity_map.keys()) for entity_map in entities_json if entity_map
    ]
    node_counts, edge_counts = _build_cooccurrence_network(groups)
    return _build_network_html(node_counts, edge_counts, include_plotlyjs)


def _build_author_network_html(
    articles: list[Paper],
    include_plotlyjs: Union[str, bool],
) -> str:
    groups: list[list[object]] = [list(paper.authors) for paper in articles if paper.authors]
    node_counts, edge_counts = _build_cooccurrence_network(groups)
    return _build_network_html(node_counts, edge_counts, include_plotlyjs)


REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ category.display_name }} Report</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 20px;
            border-radius: 8px;
            margin-bottom: 30px;
        }
        h1 { font-size: 2.5em; margin-bottom: 10px; }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        .stat-card {
            background: rgba(255,255,255,0.2);
            padding: 15px;
            border-radius: 6px;
            text-align: center;
        }
        .stat-value { font-size: 2em; font-weight: bold; }
        .stat-label { font-size: 0.9em; opacity: 0.9; }
        .papers {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .paper-card {
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .paper-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 4px 16px rgba(0,0,0,0.15);
        }
        .paper-title {
            font-size: 1.2em;
            font-weight: 600;
            margin-bottom: 10px;
            color: #667eea;
        }
        .paper-authors {
            font-size: 0.9em;
            color: #666;
            margin-bottom: 10px;
        }
        .paper-abstract {
            font-size: 0.95em;
            color: #555;
            margin-bottom: 15px;
            line-height: 1.5;
        }
        .paper-meta {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            font-size: 0.85em;
        }
        .badge {
            background: #f0f0f0;
            padding: 4px 8px;
            border-radius: 4px;
            color: #666;
        }
        .badge.venue { background: #e3f2fd; color: #1976d2; }
        .badge.citations { background: #f3e5f5; color: #7b1fa2; }
        .paper-link {
            display: inline-block;
            margin-top: 10px;
            color: #667eea;
            text-decoration: none;
            font-weight: 500;
        }
        .paper-link:hover { text-decoration: underline; }
        .errors {
            background: #ffebee;
            border-left: 4px solid #f44336;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 4px;
        }
        .error-title { color: #c62828; font-weight: 600; margin-bottom: 10px; }
        .error-item { color: #d32f2f; font-size: 0.9em; margin: 5px 0; }
        footer {
            text-align: center;
            color: #999;
            font-size: 0.9em;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
        }
        .charts-section {
            margin: 30px 0;
        }
        .charts-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .chart-card {
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .chart-title {
            font-size: 1.1em;
            font-weight: 600;
            margin-bottom: 15px;
            color: #667eea;
        }
        .chart-wrap {
            position: relative;
            height: 280px;
        }
        .network-wrap {
            min-height: 360px;
        }
        .network-wrap .plotly-graph-div {
            width: 100%;
            height: 360px;
        }
        .network-empty {
            min-height: 360px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #64748b;
            font-size: 0.95em;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{{ category.display_name }}</h1>
            <p>Academic Paper Collection Report</p>
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value">{{ stats.sources }}</div>
                    <div class="stat-label">Sources</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{{ stats.collected }}</div>
                    <div class="stat-label">Collected</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{{ stats.matched }}</div>
                    <div class="stat-label">Matched</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{{ stats.window_days }}d</div>
                    <div class="stat-label">Window</div>
                </div>
            </div>
        </header>

        {% if errors %}
        <div class="errors">
            <div class="error-title">⚠️ Collection Errors ({{ errors|length }})</div>
            {% for error in errors %}
            <div class="error-item">{{ error }}</div>
            {% endfor %}
        </div>
        {% endif %}

        <div class="charts-section">
            <h2 style="margin-bottom: 20px; color: #333;">📊 Visualizations</h2>
            <div class="charts-grid">
                <div class="chart-card">
                    <div class="chart-title">Entity Distribution</div>
                    <div class="chart-wrap">
                        <canvas id="chartEntities"></canvas>
                    </div>
                </div>
                <div class="chart-card">
                    <div class="chart-title">Publication Timeline</div>
                    <div class="chart-wrap">
                        <canvas id="chartTimeline"></canvas>
                    </div>
                </div>
            </div>
            <div class="charts-grid">
                <div class="chart-card">
                    <div class="chart-title">Source Distribution</div>
                    <div class="chart-wrap">
                        <canvas id="chartSources"></canvas>
                    </div>
                </div>
                <div class="chart-card">
                    <div class="chart-title">Venue Distribution</div>
                    <div class="chart-wrap">
                        <canvas id="chartVenues"></canvas>
                    </div>
                </div>
            </div>
            <div class="charts-grid" style="margin-top:12px">
                <div class="chart-card">
                    <div class="chart-title">Data Freshness (collection lag)</div>
                    <div class="chart-wrap"><canvas id="chartFreshness"></canvas></div>
                </div>
                <div class="chart-card">
                    <div class="chart-title">Entity Extraction Rate</div>
                    <div class="chart-wrap"><canvas id="chartEntityRate"></canvas></div>
                </div>
            </div>
            <div class="charts-grid" style="margin-top:12px">
                <div class="chart-card">
                    <div class="chart-title">Source Health</div>
                    <div class="chart-wrap"><canvas id="chartSourceHealth"></canvas></div>
                </div>
            </div>
            <div class="charts-grid" style="margin-top:12px">
                <div class="chart-card">
                    <div class="chart-title">Co-topic Network</div>
                    <div class="network-wrap">{{ co_topic_network_html | safe }}</div>
                </div>
                <div class="chart-card">
                    <div class="chart-title">Co-author Network</div>
                    <div class="network-wrap">{{ co_author_network_html | safe }}</div>
                </div>
            </div>
        </div>

        <h2 style="margin-bottom: 20px; color: #333;">📄 Recent Papers</h2>
        <div class="papers">
            {% for paper in articles %}
            <div class="paper-card">
                <div class="paper-title">{{ paper.title }}</div>
                {% if paper.authors %}
                <div class="paper-authors">
                    {{ paper.authors|join(', ') }}
                </div>
                {% endif %}
                {% if paper.abstract %}
                <div class="paper-abstract">
                    {{ paper.abstract[:200] }}{% if paper.abstract|length > 200 %}...{% endif %}
                </div>
                {% endif %}
                <div class="paper-meta">
                    {% if paper.venue %}
                    <span class="badge venue">{{ paper.venue }}</span>
                    {% endif %}
                    {% if paper.citation_count %}
                    <span class="badge citations">{{ paper.citation_count }} citations</span>
                    {% endif %}
                    <span class="badge">{{ paper.source }}</span>
                </div>
                <a href="{{ paper.link }}" class="paper-link" target="_blank">Read Paper →</a>
            </div>
            {% endfor %}
        </div>

        <footer>
            Generated on {{ generated_at }} | PaperRadar v0.1.0
        </footer>
    </div>

    <script id="articles-data" type="application/json">{{ articles_json|tojson }}</script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
    <script>
      (function () {
        function readJson(id, fallback) {
          const el = document.getElementById(id);
          if (!el) return fallback;
          const txt = (el.textContent || "").trim();
          if (!txt) return fallback;
          try { return JSON.parse(txt); } catch (e) { return fallback; }
        }

        const articles = readJson("articles-data", []);

        function getArticleDate(a) {
          const v = a && (a.published_at || a.published || a.date);
          if (!v) return null;
          const s = String(v);
          const direct = new Date(s);
          if (!isNaN(direct.getTime())) return direct;
          const m = s.match(/^(\\d{4})-(\\d{2})-(\\d{2})/);
          if (m) {
            const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
            if (!isNaN(d.getTime())) return d;
          }
          return null;
        }

        function toDayKey(d) {
          const y = d.getFullYear();
          const m = String(d.getMonth() + 1).padStart(2, "0");
          const day = String(d.getDate()).padStart(2, "0");
          return y + "-" + m + "-" + day;
        }

        function buildTimeline(items) {
          const map = new Map();
          for (const a of items) {
            const d = getArticleDate(a);
            if (!d) continue;
            const k = toDayKey(d);
            map.set(k, (map.get(k) || 0) + 1);
          }
          const keys = Array.from(map.keys()).sort();
          return { labels: keys, values: keys.map(k => map.get(k) || 0) };
        }

        function buildSources(items) {
          const map = new Map();
          for (const a of items) {
            const s = (a && a.source) ? String(a.source) : "unknown";
            const key = s.trim() || "unknown";
            map.set(key, (map.get(key) || 0) + 1);
          }
          const pairs = Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
          const labels = pairs.map(p => p[0]);
          const values = pairs.map(p => p[1]);
          return { labels, values };
        }

        function buildVenues(items) {
          const map = new Map();
          for (const a of items) {
            const v = (a && a.venue) ? String(a.venue).trim() : null;
            if (!v) continue;
            map.set(v, (map.get(v) || 0) + 1);
          }
          const pairs = Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
          const top = pairs.slice(0, 10);
          const rest = pairs.slice(10).reduce((acc, p) => acc + p[1], 0);
          const labels = top.map(p => p[0]);
          const values = top.map(p => p[1]);
          if (rest > 0) { labels.push("other"); values.push(rest); }
          return { labels, values };
        }

        function buildEntities(items) {
          const map = new Map();
          for (const a of items) {
            const ent = a && a.matched_entities;
            if (!ent) continue;
            for (const [name, keywords] of Object.entries(ent)) {
              map.set(name, (map.get(name) || 0) + (Array.isArray(keywords) ? keywords.length : 1));
            }
          }
          const pairs = Array.from(map.entries()).sort((a, b) => b[1] - a[1]).slice(0, 12);
          return { labels: pairs.map(p => p[0]), values: pairs.map(p => p[1]) };
        }

        function palette(n) {
          const base = [
            "rgba(102,126,234,.86)",
            "rgba(118,75,162,.78)",
            "rgba(51,214,197,.86)",
            "rgba(246,200,76,.86)",
            "rgba(120,162,255,.78)",
            "rgba(255,91,110,.74)",
            "rgba(160,118,255,.70)",
            "rgba(95,222,132,.70)"
          ];
          const out = [];
          for (let i = 0; i < n; i++) out.push(base[i % base.length]);
          return out;
        }

        if (!window.Chart) return;

        const timeline = buildTimeline(articles);
        const sources = buildSources(articles);
        const venues = buildVenues(articles);
        const entities = buildEntities(articles);

        const entityCanvas = document.getElementById("chartEntities");
        if (entityCanvas && entities.labels.length) {
          new Chart(entityCanvas.getContext("2d"), {
            type: "bar",
            data: {
              labels: entities.labels,
              datasets: [{
                label: "count",
                data: entities.values,
                backgroundColor: "rgba(102,126,234,.35)",
                borderColor: "rgba(102,126,234,.72)",
                borderWidth: 1.2,
                borderRadius: 8
              }]
            },
            options: {
              plugins: { legend: { display: false } },
              scales: { y: { beginAtZero: true } }
            }
          });
        }

        const timelineCanvas = document.getElementById("chartTimeline");
        if (timelineCanvas && timeline.labels.length) {
          new Chart(timelineCanvas.getContext("2d"), {
            type: "line",
            data: {
              labels: timeline.labels,
              datasets: [{
                label: "papers/day",
                data: timeline.values,
                tension: 0.3,
                fill: true,
                borderColor: "rgba(118,75,162,.84)",
                backgroundColor: "rgba(118,75,162,.15)",
                pointRadius: 3,
                pointBackgroundColor: "rgba(118,75,162,.84)"
              }]
            },
            options: {
              plugins: { legend: { display: false } },
              scales: { y: { beginAtZero: true } }
            }
          });
        }

        const sourcesCanvas = document.getElementById("chartSources");
        if (sourcesCanvas && sources.labels.length) {
          const colors = palette(sources.labels.length);
          new Chart(sourcesCanvas.getContext("2d"), {
            type: "doughnut",
            data: {
              labels: sources.labels,
              datasets: [{
                label: "papers",
                data: sources.values,
                backgroundColor: colors.map(c => c.replace(")", ", .35)").replace("rgba", "rgba")),
                borderColor: colors.map(c => c.replace(")", ", .80)").replace("rgba", "rgba")),
                borderWidth: 1.2
              }]
            },
            options: {
              cutout: "62%",
              plugins: { legend: { position: "bottom" } }
            }
          });
        }

        const venuesCanvas = document.getElementById("chartVenues");
        if (venuesCanvas && venues.labels.length) {
          const colors = palette(venues.labels.length);
          new Chart(venuesCanvas.getContext("2d"), {
            type: "bar",
            data: {
              labels: venues.labels,
              datasets: [{
                label: "papers",
                data: venues.values,
                backgroundColor: "rgba(51,214,197,.35)",
                borderColor: "rgba(51,214,197,.72)",
                borderWidth: 1.2,
                borderRadius: 8
              }]
            },
            options: {
              indexAxis: "y",
              plugins: { legend: { display: false } },
              scales: { x: { beginAtZero: true } }
            }
          });
        }

         // Chart 1: Data Freshness (collection lag in hours)
         function buildFreshness(items) {
           const lagBuckets = { "0-1h": 0, "1-6h": 0, "6-24h": 0, "1-3d": 0, "3-7d": 0, "7d+": 0 };
           const now = new Date();
           for (const a of items) {
             const pubStr = a && (a.published_at || a.published);
             const collStr = a && a.collected_at;
             if (!pubStr || !collStr) continue;
             const pubDate = new Date(String(pubStr));
             const collDate = new Date(String(collStr));
             if (isNaN(pubDate.getTime()) || isNaN(collDate.getTime())) continue;
             const lagMs = collDate.getTime() - pubDate.getTime();
             const lagHours = lagMs / (1000 * 60 * 60);
             if (lagHours < 1) lagBuckets["0-1h"]++;
             else if (lagHours < 6) lagBuckets["1-6h"]++;
             else if (lagHours < 24) lagBuckets["6-24h"]++;
             else if (lagHours < 72) lagBuckets["1-3d"]++;
             else if (lagHours < 168) lagBuckets["3-7d"]++;
             else lagBuckets["7d+"]++;
           }
           return { labels: Object.keys(lagBuckets), values: Object.values(lagBuckets) };
         }

         const freshnessData = buildFreshness(articles);
         const freshnessCanvas = document.getElementById("chartFreshness");
         if (freshnessCanvas && freshnessData.labels.length) {
           new Chart(freshnessCanvas.getContext("2d"), {
             type: "bar",
             data: {
               labels: freshnessData.labels,
               datasets: [{
                 label: "papers",
                 data: freshnessData.values,
                 backgroundColor: "rgba(120,162,255,.35)",
                 borderColor: "rgba(120,162,255,.72)",
                 borderWidth: 1.2,
                 borderRadius: 8
               }]
             },
             options: {
               plugins: { legend: { display: false } },
               scales: { y: { beginAtZero: true } }
             }
           });
         }

         // Chart 2: Entity Extraction Rate (doughnut with center text)
         function buildEntityRate(items) {
           let withEntities = 0, withoutEntities = 0;
           for (const a of items) {
             const ents = a && a.matched_entities;
             if (ents && Object.keys(ents).length > 0) withEntities++;
             else withoutEntities++;
           }
           return { with: withEntities, without: withoutEntities };
         }

         const entityRateData = buildEntityRate(articles);
         const entityRateCanvas = document.getElementById("chartEntityRate");
         if (entityRateCanvas) {
           const total = entityRateData.with + entityRateData.without;
           const pct = total > 0 ? Math.round((entityRateData.with / total) * 100) : 0;
           const plugin = {
             id: "textCenter",
             beforeDatasetsDraw(c) {
               const { width, height } = c.chartArea;
               const x = c.chartArea.left + width / 2;
               const y = c.chartArea.top + height / 2;
               c.ctx.save();
               c.ctx.font = "bold 24px sans-serif";
               c.ctx.fillStyle = "rgba(15,23,42,.8)";
               c.ctx.textAlign = "center";
               c.ctx.textBaseline = "middle";
               c.ctx.fillText(pct + "%", x, y);
               c.ctx.restore();
             }
           };
           new Chart(entityRateCanvas.getContext("2d"), {
             type: "doughnut",
             data: {
               labels: ["With entities", "Without entities"],
               datasets: [{
                 data: [entityRateData.with, entityRateData.without],
                 backgroundColor: ["rgba(95,222,132,.35)", "rgba(255,91,110,.35)"],
                 borderColor: ["rgba(95,222,132,.80)", "rgba(255,91,110,.80)"],
                 borderWidth: 1.2
               }]
             },
             options: {
               cutout: "62%",
               plugins: {
                 legend: { position: "bottom" },
                 tooltip: { enabled: true }
               }
             },
             plugins: [plugin]
           });
         }

         // Chart 3: Source Health (horizontal bar, sorted descending)
         function buildSourceHealth(items) {
           const map = new Map();
           for (const a of items) {
             const s = (a && a.source) ? String(a.source) : "unknown";
             const key = s.trim() || "unknown";
             map.set(key, (map.get(key) || 0) + 1);
           }
           const pairs = Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
           return { labels: pairs.map(p => p[0]), values: pairs.map(p => p[1]) };
         }

         const sourceHealthData = buildSourceHealth(articles);
         const sourceHealthCanvas = document.getElementById("chartSourceHealth");
         if (sourceHealthCanvas && sourceHealthData.labels.length) {
           const colors = palette(sourceHealthData.labels.length);
           new Chart(sourceHealthCanvas.getContext("2d"), {
             type: "bar",
             data: {
               labels: sourceHealthData.labels,
               datasets: [{
                 label: "papers",
                 data: sourceHealthData.values,
                 backgroundColor: colors.map(c => c.replace(")", ", .35)").replace("rgba", "rgba")),
                 borderColor: colors.map(c => c.replace(")", ", .80)").replace("rgba", "rgba")),
                 borderWidth: 1.2,
                 borderRadius: 8
               }]
             },
             options: {
               indexAxis: "y",
               plugins: { legend: { display: false } },
               scales: { x: { beginAtZero: true } }
             }
           });
         }

      })();
    </script>
</body>
</html>
"""


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

    template = Template(REPORT_TEMPLATE)
    html = template.render(
        category=category,
        articles=articles,
        articles_json=articles_json,
        co_topic_network_html=co_topic_network_html,
        co_author_network_html=co_author_network_html,
        stats=stats,
        errors=errors,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    with open(output_path, "w") as f:
        f.write(html)

    return output_path


INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Radar Reports</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 24px; background: #f6f8fb; color: #0f172a; }
    h1 { margin: 0 0 8px 0; }
    .muted { color: #475569; font-size: 13px; margin-bottom: 24px; }
    .reports { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
    .card { background: white; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); transition: box-shadow 0.2s; }
    .card:hover { box-shadow: 0 4px 6px rgba(0,0,0,0.08); }
    a { color: #0f172a; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .empty { text-align: center; color: #64748b; padding: 48px; }
  </style>
</head>
<body>
  <h1>Radar Reports</h1>
  <div class="muted">Generated at {{ generated_at }}</div>

  {% if reports %}
  <div class="reports">
    {% for report in reports %}
    <div class="card">
      <a href="{{ report.filename }}"><strong>{{ report.display_name }}</strong></a>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="empty">No reports available yet.</div>
  {% endif %}
</body>
</html>
"""


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

    template = Template(INDEX_TEMPLATE)
    html = template.render(
        reports=reports,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
    )

    index_path = report_dir / "index.html"
    with open(index_path, "w") as f:
        f.write(html)

    return index_path
