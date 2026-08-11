# App Store Product Intelligence

Analytics engineering project built on public Apple App Store data,
providing information for spcified company and relevant competitors
across different countries.


## Architecture

```
Apple iTunes Search API
        |
        v
Python ingestion
        |
        v
BigQuery raw layer
        |
        v
dbt transformations
        |
        v
Analytics marts
        |
        v
Product / market intelligence
```


## Project layout

```
ingestion/
  itunes_client.py   # iTunes Search API client
  config.py           # loads search config (term/country/entity) from .env
tests/
  test_itunes_client.py
  test_config.py
.env.example           # template — copy to .env and fill in your own values
```

## Setup

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # then edit .env with your own search term/country/entity
```

`.env` is gitignored and never committed — see [Configuration](#configuration).

## Configuration

Which company/app to search for, which App Store country, and which Apple
entity type are configuration, not code — per [CLAUDE.md](CLAUDE.md)
("Do not hard-code MacPaw into the data models. Make the pipeline
configurable for other companies."). None of these have defaults baked
into the client or checked into the repo.

Set them in `.env` (copied from `.env.example`):

```bash
APP_STORE_SEARCH_TERM=your-company-or-app-name
APP_STORE_COUNTRY=US
APP_STORE_ENTITY=your-entity-type   # see Apple's iTunes Search API docs
```

Then load them via `ingestion.config`:

```python
from ingestion.config import load_search_config
from ingestion.itunes_client import ITunesSearchClient

config = load_search_config()  # raises RuntimeError if .env isn't set up
client = ITunesSearchClient()
data = client.search(term=config.term, entity=config.entity, country=config.country)
```

### `ITunesSearchClient.search` parameters

| Parameter | Description | Default |
|---|---|---|
| `term` | Search text, e.g. an app or company name | required |
| `entity` | Apple entity type to search (keyword-only) | required |
| `country` | Two-letter App Store storefront code (`US`, `DE`, `UA`, ...) | `"US"` |
| `limit` | Max number of results (Apple accepts 1-200) | `50` |
| `offset` | Number of results to skip, for pagination | `0` |

Raises `ValueError` for invalid arguments, and one of:

- `ITunesResponseError` — HTTP 200 but the payload is an API-level error
  (Apple returns `{"errorMessage": ...}` with a 200 status for bad params)
  or doesn't match the expected `resultCount`/`results` shape.
- `ITunesRateLimitError` — still rate-limited (HTTP 403/429) after all retries.
- `ITunesSearchError` — base class for the above, and also raised directly
  for network errors or non-retryable/exhausted HTTP errors.

### Retries

Network errors, rate limiting (403/429), and 5xx responses are retried
automatically with exponential backoff (honoring the `Retry-After` header
when present). Other 4xx errors and malformed 200 payloads are not
retried, since retrying an identical bad request just repeats the same
result. Configurable via the `max_retries` and `backoff_factor` constructor
arguments (defaults: 3 retries, 0.5s base backoff).

## Testing

```bash
python3 -m pytest -q
```

Tests use a fake HTTP session, so they run offline and don't hit the
real Apple API.

## Principles

- Use real data only — never invent business data.
- Preserve raw API responses where practical.
- Every collected record must have a `snapshot_date`.
- Keep ingestion separate from dbt transformations.

See [CLAUDE.md](CLAUDE.md) for full project goals and development rules.
