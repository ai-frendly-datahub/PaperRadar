# Paper Collectors Documentation

## Overview

PaperRadar includes 7 paper source collectors, each with specific API documentation and rate limits.

## 1. arXiv Collector

**API**: https://arxiv.org/api/

**Rate Limit**: 3 requests/second

**Authentication**: None required

**Query Format**:
```
http://export.arxiv.org/api/query?search_query=QUERY&start=0&max_results=N
```

**Supported Queries**:
- `cat:cs.AI` - AI category
- `cat:cs.CL` - Computational Linguistics
- `cat:cs.LG` - Machine Learning
- `all:transformer` - Keyword search
- `au:Hinton` - Author search

**Parsed Fields**:
- title
- authors (list)
- abstract
- arxiv_id
- pdf_url
- published_date

**Example**:
```python
url = "http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=30"
```

## 2. Semantic Scholar Collector

**API**: https://api.semanticscholar.org/

**Rate Limit**: 100 requests/5 minutes (free tier)

**Authentication**: Optional API key for higher limits

**Endpoint**:
```
https://api.semanticscholar.org/graph/v1/paper/search
```

**Query Parameters**:
- `query` - Search term
- `limit` - Results per page (max 100)
- `fields` - Comma-separated fields to return

**Parsed Fields**:
- title
- authors (list with names)
- abstract
- venue (conference/journal)
- citationCount
- url

**Example**:
```python
url = "https://api.semanticscholar.org/graph/v1/paper/search?query=machine learning&limit=30&fields=title,authors,abstract,venue,citationCount"
```

## 3. PubMed Collector

**API**: https://www.ncbi.nlm.nih.gov/books/NBK25499/

**Rate Limit**: Unlimited (3 requests/second recommended)

**Authentication**: None required (email recommended)

**Endpoints**:
- Search: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi`
- Fetch: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi`

**Query Parameters**:
- `db=pubmed` - Database
- `term` - Search query
- `retmax` - Max results
- `rettype=json` - JSON format

**Parsed Fields**:
- title
- authors (list)
- abstract
- journal
- PMID
- publication_date

**Example**:
```python
search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=machine learning&retmax=30&rettype=json"
```

## 4. bioRxiv Collector

**API**: https://www.biorxiv.org/

**Rate Limit**: Free, no authentication

**Endpoint**:
```
https://api.biorxiv.org/details/biorxiv/YYYY-MM-DD/YYYY-MM-DD/0/N
```

**Parsed Fields**:
- title
- authors (semicolon-separated)
- abstract
- DOI
- publication_date

**Example**:
```python
url = "https://api.biorxiv.org/details/biorxiv/2024-01-01/2024-12-31/0/100"
```

## 5. OpenAlex Collector

**API**: https://docs.openalex.org/

**Rate Limit**: 10 requests/second (polite pool)

**Authentication**: None required

**Endpoint**:
```
https://api.openalex.org/works
```

**Query Parameters**:
- `search` - Search term
- `per-page` - Results per page
- `sort` - Sort order (e.g., `publication_date:desc`)

**Parsed Fields**:
- title
- authors (list with display names)
- abstract_inverted_index
- DOI
- concepts
- citationCount

**Example**:
```python
url = "https://api.openalex.org/works?search=machine learning&per-page=30&sort=publication_date:desc"
```

## 6. CrossRef Collector

**API**: https://www.crossref.org/documentation/retrieve-metadata/rest-api/

**Rate Limit**: Free, polite pool (10 requests/second)

**Authentication**: None required (email recommended)

**Endpoint**:
```
https://api.crossref.org/works
```

**Query Parameters**:
- `query` - Search term
- `rows` - Results per page
- `sort` - Sort order
- `order` - asc/desc

**Parsed Fields**:
- title
- authors (list)
- DOI
- URL
- journal
- publication_date

**Example**:
```python
url = "https://api.crossref.org/works?query=machine learning&rows=30&sort=published&order=desc"
```

## 7. SSRN Collector

**API**: https://papers.ssrn.com/

**Rate Limit**: Scraping-based (be respectful)

**Authentication**: None required

**Note**: SSRN requires web scraping. Current implementation is a stub.

**Parsed Fields**:
- title
- authors
- abstract
- downloads
- publication_date

## Rate Limiting Best Practices

1. **Respect rate limits** - Use `@retry` decorator with exponential backoff
2. **Add delays** - Space requests appropriately
3. **Identify yourself** - Include email in User-Agent or request headers
4. **Cache results** - Store raw data in JSONL for replay
5. **Monitor errors** - Log and report collection failures

## Error Handling

All collectors implement:
- Timeout enforcement (default 15 seconds)
- Retry logic with exponential backoff
- Graceful error handling (doesn't crash pipeline)
- Error reporting in HTML report

## Configuration

Edit `config/categories/research.yaml` to customize:

```yaml
sources:
  - name: arXiv
    type: arxiv
    url: "http://export.arxiv.org/api/query?search_query=cat:cs.AI"
```

## Testing Collectors

```python
from paperradar.collector import collect_sources
from paperradar.models import Source

source = Source(
    name="arXiv",
    type="arxiv",
    url="http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=5"
)

papers, errors = collect_sources([source], category="research", limit_per_source=5)
print(f"Collected {len(papers)} papers")
if errors:
    print(f"Errors: {errors}")
```

## Future Collectors

Potential additions:
- IEEE Xplore
- ACM Digital Library
- DBLP Computer Science Bibliography
- Google Scholar (via unofficial API)
- ResearchGate
- Academia.edu
