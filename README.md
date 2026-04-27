# PaperRadar

**🌐 Live Report**: https://ai-frendly-datahub.github.io/PaperRadar/


Academic paper and research-signal collection platform. Current configuration mixes arXiv RSS/API, AI lab blogs, research aggregators, citation feeds, and benchmark/implementation sources for entity extraction, search, and HTML reporting.

## Features

- **Research Source Mix**: arXiv, AI labs, benchmark feeds, citation/impact sources, newsletters
- **Entity Extraction**: Automatic tagging of research areas, authors, institutions, venues, techniques
- **Full-Text Search**: SQLite FTS5 for fast paper searching
- **DuckDB Storage**: Efficient paper database with retention policies
- **HTML Reports**: Beautiful, responsive academic paper reports
- **GitHub Pages**: Automatic deployment of reports
- **Scheduled Collection**: Every 6 hours via GitHub Actions

## Quick Start

### Installation

```bash
git clone https://github.com/yourusername/PaperRadar.git
cd PaperRadar
pip install -r requirements.txt
```

### Usage

```bash
# Collect papers from all sources
python main.py --category research --recent-days 7 --keep-days 90

# Custom options
python main.py \
  --category research \
  --per-source-limit 50 \
  --recent-days 14 \
  --timeout 20 \
  --keep-days 180
```

### Configuration

Edit `config/categories/research.yaml` to customize:
- Paper sources and queries
- Entity definitions (research areas, authors, venues, etc.)
- Collection parameters

## Project Structure

```
PaperRadar/
├── paperradar/              # Main package
│   ├── collector.py         # RSS + paper source collectors
│   ├── analyzer.py          # Entity extraction
│   ├── reporter.py          # HTML report generation
│   ├── storage.py           # DuckDB storage
│   ├── search_index.py      # FTS5 search
│   ├── models.py            # Data models
│   ├── config_loader.py     # YAML configuration
│   ├── logger.py            # Structured logging
│   ├── raw_logger.py        # JSONL raw data logging
│   └── nl_query.py          # Natural language query parsing
├── config/
│   ├── config.yaml          # Main configuration
│   └── categories/
│       └── research.yaml    # AI/ML research category
├── data/                    # DuckDB, search index, raw JSONL
├── reports/                 # Generated HTML reports
├── tests/
│   ├── unit/               # Unit tests (80%+ coverage)
│   └── integration/        # Integration tests
├── main.py                 # CLI entry point
└── .github/workflows/      # GitHub Actions
```

## Paper Sources

| Source Group | Examples | Role |
|-------------|----------|------|
| Official research feeds | arXiv RSS, arXiv API | Preprint intake |
| Lab / platform blogs | OpenAI, DeepMind, Hugging Face | Model release and implementation signals |
| Aggregators | Papers With Code, Semantic Scholar AI | Benchmark, citation, discovery |
| API-based impact feeds | OpenAlex | Citation and impact tracking |

## Data Schema

Papers are stored in DuckDB with the following schema:

```sql
CREATE TABLE papers (
  paper_id VARCHAR PRIMARY KEY,
  title VARCHAR NOT NULL,
  authors VARCHAR[],
  abstract VARCHAR,
  url VARCHAR,
  pdf_url VARCHAR,
  arxiv_id VARCHAR,
  doi VARCHAR,
  venue VARCHAR,
  publication_date DATE,
  citation_count INTEGER,
  categories VARCHAR[],
  keywords VARCHAR[],
  collected_at TIMESTAMP,
  source_name VARCHAR,
  category VARCHAR
);
```

## Entity Extraction

Automatically tags papers with:
- **Research Areas**: Machine Learning, NLP, Computer Vision, etc.
- **Key Researchers**: Hinton, LeCun, Bengio, etc.
- **Institutions**: Stanford, MIT, Google Brain, OpenAI, etc.
- **Venues**: NeurIPS, ICML, ICLR, ACL, CVPR, etc.
- **Techniques**: Transformer, BERT, GPT, Diffusion, etc.

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=paperradar --cov-report=html

# Run only unit tests
pytest tests/unit -m unit

# Run without network tests
pytest -m "not network"
```

## Development

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Format code
black paperradar tests main.py

# Lint
ruff check paperradar tests main.py

# Type check
mypy paperradar main.py
```

## GitHub Actions

Automatically runs every 6 hours:
1. Collects papers from all sources
2. Extracts entities and stores in DuckDB
3. Generates HTML report
4. Deploys to GitHub Pages
5. Backs up database as artifact

## API Keys (Optional)

Some sources support optional API keys for higher rate limits:

```bash
# .env file
SEMANTIC_SCHOLAR_API_KEY=your_key_here
CROSSREF_EMAIL=your-email@example.com
```

## Performance

- **Collection**: ~500-1000 papers/day across all sources
- **Storage**: DuckDB with automatic retention (default 90 days)
- **Search**: SQLite FTS5 for instant full-text search
- **Reports**: Generated in <5 seconds

## License

MIT

## Contributing

Contributions welcome! Please:
1. Write tests first (TDD)
2. Maintain 80%+ coverage
3. Follow Black/Ruff style
4. Add documentation

## Support

For issues, questions, or suggestions, please open a GitHub issue.

<!-- DATAHUB-OPS-AUDIT:START -->
## DataHub Operations

- CI/CD workflows: `paper-crawler.yml`, `pr-checks.yml`, `radar-crawler.yml`.
- GitHub Pages visualization: `reports/index.html` (valid HTML); https://ai-frendly-datahub.github.io/PaperRadar/.
- Latest remote Pages check: HTTP 200, HTML.
- Local workspace audit: 55 Python files parsed, 0 syntax errors.
- Re-run audit from the workspace root: `python scripts/audit_ci_pages_readme.py --syntax-check --write`.
- Latest audit report: `_workspace/2026-04-14_github_ci_pages_readme_audit.md`.
- Latest Pages URL report: `_workspace/2026-04-14_github_pages_url_check.md`.
<!-- DATAHUB-OPS-AUDIT:END -->
