"""Minimal client for Apple's iTunes Search API.

Docs: https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/index.html

This module only talks to the API and returns parsed JSON. It intentionally
does not persist data anywhere (no BigQuery, no files) — that is handled by
downstream ingestion code.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import requests

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
DEFAULT_TIMEOUT_SECONDS = 10

# How many extra attempts to make after the first one fails, and how long to
# wait before each retry: delay = backoff_factor * (2 ** attempt_index).
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.5

# Apple doesn't publish a formal rate-limit response, but 403 is what it
# returns in practice once a client is throttled; 429 is included for
# spec-compliant proxies/CDNs in front of it. 5xx are ordinary transient
# server errors. All of these are worth retrying; other 4xx (bad params,
# not found, ...) are not — retrying an identical malformed request just
# gets the same result.
RATE_LIMIT_STATUS_CODES = frozenset({403, 429})
RETRYABLE_STATUS_CODES = RATE_LIMIT_STATUS_CODES | frozenset({500, 502, 503, 504})


class ITunesSearchError(RuntimeError):
    """Base error for anything that goes wrong calling the iTunes Search API."""


class ITunesRateLimitError(ITunesSearchError):
    """Raised when the API is still rate-limiting us after all retries are exhausted."""


class ITunesResponseError(ITunesSearchError):
    """Raised when the API returns HTTP 200 but the payload is an error or malformed.

    Apple's Search API sometimes answers with HTTP 200 and a body like
    ``{"errorMessage": "..."}`` for bad params (e.g. an invalid entity or
    country code), rather than a non-200 status. A 200 status is therefore
    not sufficient to treat the call as successful — the payload itself has
    to be validated.
    """


class ITunesSearchClient:
    """Thin wrapper around Apple's iTunes Search API.

    Neither the search term nor the Apple entity type has a built-in default
    here — both describe *what* to search for, which is configuration, not
    something this generic client should assume. See `ingestion.config` for
    loading those from a `.env` file.

    Example:
        from ingestion.config import load_search_config

        config = load_search_config()  # reads term/country/entity from .env
        client = ITunesSearchClient()
        data = client.search(term=config.term, entity=config.entity, country=config.country)
    """

    def __init__(
        self,
        base_url: str = ITUNES_SEARCH_URL,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        session: Optional[requests.Session] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
        sleep_func: Any = time.sleep,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._sleep = sleep_func

    def search(
        self,
        term: str,
        *,
        entity: str,
        country: str = "US",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Query the iTunes Search API and return the parsed JSON response.

        Retries transient failures (network errors, rate limiting, 5xx)
        with exponential backoff, honoring the ``Retry-After`` header when
        the API sends one.

        Args:
            term: Search text, e.g. an app or company name. No default —
                this is company/product config, not something a generic
                client should assume; see `ingestion.config`.
            entity: Apple entity type to search (see Apple's iTunes Search
                API docs for valid values per media type). No default, for
                the same reason as `term`. Keyword-only so it can never be
                confused positionally with `country`.
            country: Two-letter App Store storefront code (e.g. "US", "DE", "UA").
            limit: Max number of results to return (Apple accepts 1-200).
            offset: Number of results to skip, for pagination.

        Returns:
            The parsed JSON response as a dict (includes "resultCount" and "results").

        Raises:
            ValueError: If arguments are invalid.
            ITunesRateLimitError: If the API is still rate-limiting after all retries.
            ITunesResponseError: If HTTP 200 comes back with an API-level error
                or a payload that doesn't match the expected shape.
            ITunesSearchError: For any other request failure (network error or
                non-retryable/exhausted HTTP error).
        """
        if not term:
            raise ValueError("term must not be empty")
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        params = {
            "term": term,
            "country": country,
            "entity": entity,
            "limit": limit,
            "offset": offset,
        }

        last_error: Optional[BaseException] = None

        for attempt in range(self.max_retries + 1):
            is_last_attempt = attempt == self.max_retries

            try:
                response = self.session.get(self.base_url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                if is_last_attempt:
                    raise ITunesSearchError(
                        f"Request to iTunes Search API failed after {attempt + 1} attempt(s): {exc}"
                    ) from exc
                self._wait_before_retry(attempt, retry_after=None)
                continue

            if response.status_code == 200:
                return self._parse_and_validate(response)

            if response.status_code not in RETRYABLE_STATUS_CODES:
                raise ITunesSearchError(
                    f"iTunes Search API returned status {response.status_code}: {response.text[:200]}"
                )

            last_error = ITunesSearchError(
                f"iTunes Search API returned status {response.status_code}: {response.text[:200]}"
            )
            if is_last_attempt:
                if response.status_code in RATE_LIMIT_STATUS_CODES:
                    raise ITunesRateLimitError(
                        f"iTunes Search API rate-limited the client after {attempt + 1} attempt(s) "
                        f"(status {response.status_code})"
                    ) from last_error
                raise last_error

            self._wait_before_retry(attempt, retry_after=self._parse_retry_after(response))

        # Unreachable in practice: the loop above always returns or raises.
        raise ITunesSearchError(f"iTunes Search API request failed: {last_error}")

    def _wait_before_retry(self, attempt: int, retry_after: Optional[float]) -> None:
        delay = retry_after if retry_after is not None else self.backoff_factor * (2**attempt)
        if delay > 0:
            self._sleep(delay)

    @staticmethod
    def _parse_retry_after(response: Any) -> Optional[float]:
        value = getattr(response, "headers", {}).get("Retry-After")
        if not value:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_and_validate(response: Any) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ITunesResponseError(f"iTunes Search API returned invalid JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise ITunesResponseError(
                f"iTunes Search API returned an unexpected payload type: {type(data).__name__}"
            )

        if "errorMessage" in data:
            raise ITunesResponseError(f"iTunes Search API returned an error: {data['errorMessage']}")

        if not isinstance(data.get("resultCount"), int) or not isinstance(data.get("results"), list):
            raise ITunesResponseError(
                "iTunes Search API response is missing the expected 'resultCount'/'results' "
                f"fields: {str(data)[:200]}"
            )

        return data
