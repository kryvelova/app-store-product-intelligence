"""Runtime configuration loaded from environment variables / a `.env` file.

Company- and product-specific values (which term to search for, which App
Store storefront, which Apple entity type) never live in source code — per
CLAUDE.md ("Do not hard-code MacPaw into the data models. Make the pipeline
configurable for other companies."). Copy `.env.example` to `.env` and fill
in your own values; `.env` is gitignored and never committed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE)  # no-op if the file doesn't exist; real env vars still apply

_REQUIRED_VARS = ("APP_STORE_SEARCH_TERM", "APP_STORE_COUNTRY", "APP_STORE_ENTITY")


@dataclass(frozen=True)
class SearchConfig:
    """Search defaults for one company/target, read from the environment."""

    term: str
    country: str
    entity: str


def load_search_config() -> SearchConfig:
    """Read search defaults (term, country, entity) from the environment.

    Raises:
        RuntimeError: If any required variable is missing or empty. Copy
            `.env.example` to `.env` and fill it in to fix this.
    """
    values = {name: os.environ.get(name) for name in _REQUIRED_VARS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            f"{', '.join(missing)}. Copy .env.example to .env and fill them in."
        )

    return SearchConfig(
        term=values["APP_STORE_SEARCH_TERM"],
        country=values["APP_STORE_COUNTRY"],
        entity=values["APP_STORE_ENTITY"],
    )
