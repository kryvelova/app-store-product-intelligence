"""First real-data ingestion experiment: fetch one page of app search
results from Apple's iTunes Search API and save the raw response to disk.

This is a deliberately minimal, one-off exploratory script — not the
scheduled pipeline. There's no pagination, no retries, and no BigQuery
write. Search parameters (term/country/entity/limit) come from the
environment via ingestion.config, never hardcoded — see .env.example.

Usage:
    python3 -m ingestion.fetch_apps
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ingestion.config import load_search_config

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
TIMEOUT_SECONDS = 10

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def fetch_apps(term: str, country: str, entity: str, limit: int) -> bytes:
    """Call the iTunes Search API and return the raw response body.

    Raises:
        RuntimeError: If the request fails (network error or non-200 status).
    """
    params = {"term": term, "country": country, "entity": entity, "limit": limit}
    url = f"{ITUNES_SEARCH_URL}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"iTunes Search API returned HTTP {exc.code}: {body[:200]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request to iTunes Search API failed: {exc.reason}") from exc


def _slugify(value: str) -> str:
    """Turn a config value into a safe filename fragment."""
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")


def main() -> None:
    config = load_search_config()

    raw_body = fetch_apps(
        term=config.term, country=config.country, entity=config.entity, limit=config.limit
    )

    # Validate it's actually JSON before writing anything, but save the raw
    # bytes as-is so the file matches Apple's response exactly.
    try:
        data = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"iTunes Search API returned invalid JSON: {exc}") from exc

    filename = f"{_slugify(config.term)}_{_slugify(config.country)}_{_slugify(config.entity)}.json"
    output_path = DATA_DIR / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(raw_body)

    print(f"Saved {data.get('resultCount', '?')} result(s) to {output_path}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
