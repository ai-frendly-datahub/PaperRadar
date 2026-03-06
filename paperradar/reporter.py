from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Template


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
</body>
</html>
"""


def generate_report(
    category,
    articles: list,
    output_path: Path,
    stats: dict,
    errors: list[str],
) -> Path:
    """Generate HTML report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    template = Template(REPORT_TEMPLATE)
    html = template.render(
        category=category,
        articles=articles,
        stats=stats,
        errors=errors,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    
    with open(output_path, "w") as f:
        f.write(html)
    
    return output_path
