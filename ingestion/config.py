"""Runtime configuration loaded from environment variables / a `.env` file.

Company- and product-specific values (which term to search for, which App
Store storefront, which Apple entity type) never live in source code — per
CLAUDE.md ("Do not hard-code MacPaw into the data models. Make the pipeline
configurable for other companies."). Copy `.env.example` to `.env` and fill
in your own values; `.env` is gitignored and never committed.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE)  # no-op if the file doesn't exist; real env vars still apply

_REQUIRED_VARS = ("APP_STORE_SEARCH_TERM", "APP_STORE_COUNTRY", "APP_STORE_ENTITY", "APP_STORE_LIMIT")


@dataclass(frozen=True)
class SearchConfig:
    """Search defaults for one company/target, read from the environment."""

    term: str
    country: str
    entity: str
    limit: int


def load_search_config() -> SearchConfig:
    """Read search defaults (term, country, entity, limit) from the environment.

    Raises:
        RuntimeError: If any required variable is missing/empty, or if
            APP_STORE_LIMIT isn't an integer. Copy `.env.example` to `.env`
            and fill it in to fix this.
    """
    values = {name: os.environ.get(name) for name in _REQUIRED_VARS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            f"{', '.join(missing)}. Copy .env.example to .env and fill them in."
        )

    try:
        limit = int(values["APP_STORE_LIMIT"])
    except ValueError as exc:
        raise RuntimeError(
            f"APP_STORE_LIMIT must be an integer, got: {values['APP_STORE_LIMIT']!r}"
        ) from exc

    return SearchConfig(
        term=values["APP_STORE_SEARCH_TERM"],
        country=values["APP_STORE_COUNTRY"],
        entity=values["APP_STORE_ENTITY"],
        limit=limit,
    )
