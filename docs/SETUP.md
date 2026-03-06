# PaperRadar Setup Guide

## Prerequisites

- Python 3.11+
- pip or conda
- Git (for version control)
- GitHub account (for GitHub Pages deployment)

## Local Installation

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/PaperRadar.git
cd PaperRadar
```

### 2. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Create Data Directories

```bash
mkdir -p data/raw reports
```

### 5. Verify Installation

```bash
python main.py --category research --per-source-limit 5
```

## Configuration

### 1. Main Configuration (config/config.yaml)

```yaml
database_path: data/papers.duckdb
report_dir: reports
raw_data_dir: data/raw
search_db_path: data/search_index.db
```

Customize paths as needed for your environment.

### 2. Category Configuration (config/categories/research.yaml)

Edit sources and entities:

```yaml
category_name: research
display_name: AI/ML Research Papers

sources:
  - name: arXiv
    type: arxiv
    url: "http://export.arxiv.org/api/query?search_query=cat:cs.AI"
  # Add/remove sources as needed

entities:
  - name: Research Areas
    display_name: Research Areas
    keywords: [machine learning, deep learning, ...]
  # Customize keywords for your domain
```

### 3. Environment Variables (Optional)

Create `.env` file (copy from `.env.example`):

```bash
cp .env.example .env
```

Edit `.env` for optional API keys:

```bash
SEMANTIC_SCHOLAR_API_KEY=your_api_key_here
CROSSREF_EMAIL=your-email@example.com
```

## API Key Registration (Optional)

### Semantic Scholar

1. Visit https://www.semanticscholar.org/product/api
2. Request API access
3. Add key to `.env`:
   ```
   SEMANTIC_SCHOLAR_API_KEY=your_key
   ```

### CrossRef

1. No key required, but email recommended
2. Add to `.env`:
   ```
   CROSSREF_EMAIL=your-email@example.com
   ```

### PubMed

1. No key required
2. Email recommended in User-Agent

## GitHub Setup

### 1. Create GitHub Repository

```bash
git init
git add .
git commit -m "Initial commit: PaperRadar setup"
git branch -M main
git remote add origin https://github.com/yourusername/PaperRadar.git
git push -u origin main
```

### 2. Enable GitHub Pages

1. Go to repository Settings
2. Navigate to Pages
3. Select "Deploy from a branch"
4. Choose `gh-pages` branch
5. Save

### 3. Configure GitHub Actions

The workflow file `.github/workflows/paper-crawler.yml` is already configured.

To enable:
1. Go to Actions tab
2. Enable workflows
3. Workflow will run on schedule (every 6 hours)

## Development Setup

### Install Dev Dependencies

```bash
pip install -r requirements-dev.txt
```

### Code Formatting

```bash
black paperradar tests main.py
```

### Linting

```bash
ruff check paperradar tests main.py
```

### Type Checking

```bash
mypy paperradar main.py
```

### Run Tests

```bash
pytest tests/
pytest --cov=paperradar --cov-report=html
```

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'paperradar'"

**Solution**: Ensure you're in the project root directory and have installed dependencies:
```bash
pip install -r requirements.txt
```

### Issue: "DuckDB file locked"

**Solution**: Ensure no other processes are accessing the database:
```bash
lsof data/papers.duckdb  # Check open files
```

### Issue: "API rate limit exceeded"

**Solution**: Reduce `--per-source-limit` or increase timeout:
```bash
python main.py --category research --per-source-limit 10 --timeout 30
```

### Issue: "No papers collected"

**Solution**: Check source URLs in `config/categories/research.yaml`:
```bash
# Test individual source
curl "http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=5"
```

### Issue: "Report not generated"

**Solution**: Check `reports/` directory exists:
```bash
mkdir -p reports
```

## Performance Tuning

### Increase Collection Speed

```bash
python main.py --category research --per-source-limit 100 --timeout 30
```

### Reduce Memory Usage

```bash
python main.py --category research --per-source-limit 10
```

### Optimize Database

```bash
# Vacuum DuckDB
python -c "import duckdb; duckdb.connect('data/papers.duckdb').execute('VACUUM')"
```

## Deployment

### Docker (Optional)

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "main.py", "--category", "research"]
```

Build and run:

```bash
docker build -t paperradar .
docker run -v $(pwd)/data:/app/data paperradar
```

### Cloud Deployment

#### AWS Lambda

1. Package code with dependencies
2. Set handler to `main.run`
3. Configure CloudWatch Events for scheduling

#### Google Cloud Functions

1. Deploy with `main.py` as entry point
2. Configure Cloud Scheduler for cron jobs

#### Heroku

```bash
heroku create paperradar
git push heroku main
```

## Monitoring

### Check Collection Status

```bash
# View latest report
open reports/research_report.html

# Check database size
ls -lh data/papers.duckdb

# View raw data
ls -la data/raw/
```

### View Logs

```bash
# GitHub Actions logs
# Go to Actions tab in GitHub

# Local logs
tail -f logs/paperradar.log  # If logging configured
```

## Backup and Recovery

### Backup Database

```bash
cp data/papers.duckdb data/papers.duckdb.backup
```

### Restore Database

```bash
cp data/papers.duckdb.backup data/papers.duckdb
```

### Export Data

```bash
# Export to CSV
python -c "
import duckdb
conn = duckdb.connect('data/papers.duckdb')
conn.execute('COPY papers TO \"papers.csv\" (FORMAT CSV, HEADER)')
"
```

## Next Steps

1. Customize `config/categories/research.yaml` for your domain
2. Run initial collection: `python main.py --category research`
3. Review generated report in `reports/`
4. Set up GitHub Actions for automated collection
5. Monitor and adjust entity keywords based on results

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review AGENTS.md for architecture details
3. Check COLLECTORS.md for API documentation
4. Open GitHub issue with error details
