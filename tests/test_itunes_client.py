import requests

import pytest

from ingestion.itunes_client import (
    ITunesRateLimitError,
    ITunesResponseError,
    ITunesSearchClient,
    ITunesSearchError,
)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json_data


class QueueSession:
    """Stand-in for requests.Session that returns queued responses/exceptions in order.

    Each item in `queue` is either a FakeResponse to return or an Exception
    instance to raise, letting tests simulate a sequence of attempts (e.g.
    "fail once, then succeed") without any real network or sleeping.
    """

    def __init__(self, queue):
        self.queue = list(queue)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if not self.queue:
            raise AssertionError("QueueSession.get called more times than responses were queued")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(queue, **kwargs):
    sleeps = []
    session = QueueSession(queue)
    kwargs.setdefault("max_retries", 3)
    kwargs.setdefault("backoff_factor", 0.5)
    client = ITunesSearchClient(session=session, sleep_func=sleeps.append, **kwargs)
    return client, session, sleeps


# Deliberately generic/nonsense placeholders: the client is generic and must
# not care what term/entity strings mean, so tests avoid any real company or
# Apple entity name (see CLAUDE.md: don't hard-code a company into the code).
EXAMPLE_TERM = "example-app"
EXAMPLE_ENTITY = "exampleEntityType"
VALID_PAYLOAD = {"resultCount": 1, "results": [{"trackName": "Example App"}]}


# --- Basic argument validation -----------------------------------------------


@pytest.mark.parametrize("term", ["", None])
def test_search_raises_on_empty_term(term):
    client, _, _ = make_client([])
    with pytest.raises(ValueError):
        client.search(term=term, entity=EXAMPLE_ENTITY)


def test_search_raises_on_invalid_limit():
    client, _, _ = make_client([])
    with pytest.raises(ValueError):
        client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY, limit=0)


def test_search_raises_on_invalid_offset():
    client, _, _ = make_client([])
    with pytest.raises(ValueError):
        client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY, offset=-1)


def test_search_requires_entity_to_be_passed_explicitly():
    # entity has no default: what to search for is configuration (see
    # ingestion.config), not something a generic client should assume.
    client, _, _ = make_client([])
    with pytest.raises(TypeError):
        client.search(term=EXAMPLE_TERM)


def test_search_passes_expected_params():
    client, session, _ = make_client([FakeResponse(json_data=VALID_PAYLOAD)])

    client.search(term=EXAMPLE_TERM, country="DE", entity=EXAMPLE_ENTITY, limit=25, offset=5)

    assert session.calls[0]["params"] == {
        "term": EXAMPLE_TERM,
        "country": "DE",
        "entity": EXAMPLE_ENTITY,
        "limit": 25,
        "offset": 5,
    }


def test_search_uses_default_country_and_pagination():
    client, session, _ = make_client([FakeResponse(json_data=VALID_PAYLOAD)])

    client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)

    params = session.calls[0]["params"]
    assert params["country"] == "US"
    assert params["limit"] == 50
    assert params["offset"] == 0


# --- Successful response -----------------------------------------------------


def test_search_returns_parsed_json_on_success():
    client, session, sleeps = make_client([FakeResponse(json_data=VALID_PAYLOAD)])

    result = client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)

    assert result == VALID_PAYLOAD
    assert len(session.calls) == 1
    assert sleeps == []


# --- HTTP error (non-retryable) ----------------------------------------------


def test_search_raises_immediately_on_non_retryable_http_error():
    client, session, sleeps = make_client([FakeResponse(status_code=400, text="Bad Request")])

    with pytest.raises(ITunesSearchError):
        client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)

    # 400 is a client error, not a rate limit or transient server error:
    # no point retrying an identical malformed request.
    assert len(session.calls) == 1
    assert sleeps == []


# --- HTTP 200 with an API-level error / malformed response -------------------


def test_search_raises_on_200_with_api_error_message():
    client, session, sleeps = make_client(
        [FakeResponse(status_code=200, json_data={"errorMessage": "Invalid value(s) for key(s): [entity]"})]
    )

    with pytest.raises(ITunesResponseError):
        client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)

    # Not a transient failure — retrying would return the same error.
    assert len(session.calls) == 1
    assert sleeps == []


def test_search_raises_on_200_with_missing_expected_fields():
    client, _, _ = make_client([FakeResponse(status_code=200, json_data={"unexpected": "shape"})])

    with pytest.raises(ITunesResponseError):
        client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)


def test_search_raises_on_200_with_invalid_json():
    bad_response = FakeResponse(status_code=200, text="not json")
    bad_response.json = lambda: (_ for _ in ()).throw(ValueError("no JSON object"))
    client, _, _ = make_client([bad_response])

    with pytest.raises(ITunesResponseError):
        client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)


# --- Rate-limit response -------------------------------------------------------


def test_search_retries_on_rate_limit_and_honors_retry_after_header():
    client, session, sleeps = make_client(
        [
            FakeResponse(status_code=429, text="Too Many Requests", headers={"Retry-After": "2"}),
            FakeResponse(json_data=VALID_PAYLOAD),
        ]
    )

    result = client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)

    assert result == VALID_PAYLOAD
    assert len(session.calls) == 2
    # Retry-After was honored instead of the computed exponential backoff.
    assert sleeps == [2.0]


def test_search_retries_on_403_rate_limit_without_retry_after():
    client, session, sleeps = make_client(
        [
            FakeResponse(status_code=403, text="Forbidden"),
            FakeResponse(json_data=VALID_PAYLOAD),
        ]
    )

    result = client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)

    assert result == VALID_PAYLOAD
    assert len(session.calls) == 2
    assert sleeps == [0.5]  # backoff_factor * 2**0


# --- Retry behaviour (transient network + server errors) ---------------------


def test_search_retries_on_transient_network_error_then_succeeds():
    client, session, sleeps = make_client(
        [requests.ConnectionError("boom"), FakeResponse(json_data=VALID_PAYLOAD)]
    )

    result = client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)

    assert result == VALID_PAYLOAD
    assert len(session.calls) == 2
    assert sleeps == [0.5]


def test_search_retries_with_exponential_backoff_across_multiple_failures():
    client, session, sleeps = make_client(
        [
            FakeResponse(status_code=503, text="Service Unavailable"),
            FakeResponse(status_code=503, text="Service Unavailable"),
            FakeResponse(json_data=VALID_PAYLOAD),
        ],
        backoff_factor=0.5,
        max_retries=3,
    )

    result = client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)

    assert result == VALID_PAYLOAD
    assert len(session.calls) == 3
    # backoff_factor * 2**0, backoff_factor * 2**1
    assert sleeps == [0.5, 1.0]


# --- Exhausted retries ---------------------------------------------------------


def test_search_raises_rate_limit_error_after_exhausting_retries():
    client, session, sleeps = make_client(
        [
            FakeResponse(status_code=429, text="Too Many Requests"),
            FakeResponse(status_code=429, text="Too Many Requests"),
            FakeResponse(status_code=429, text="Too Many Requests"),
        ],
        max_retries=2,
    )

    with pytest.raises(ITunesRateLimitError):
        client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)

    # Initial attempt + 2 retries = 3 calls, with a sleep between each.
    assert len(session.calls) == 3
    assert sleeps == [0.5, 1.0]


def test_search_raises_search_error_after_exhausting_retries_on_server_error():
    client, session, sleeps = make_client(
        [
            FakeResponse(status_code=503, text="Service Unavailable"),
            FakeResponse(status_code=503, text="Service Unavailable"),
        ],
        max_retries=1,
    )

    with pytest.raises(ITunesSearchError) as exc_info:
        client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)

    # A plain server error, not a rate limit, so it should not be reported
    # as ITunesRateLimitError even though it went through the same retry path.
    assert not isinstance(exc_info.value, ITunesRateLimitError)
    assert len(session.calls) == 2
    assert sleeps == [0.5]


def test_search_raises_after_exhausting_retries_on_network_errors():
    client, session, sleeps = make_client(
        [requests.Timeout("timed out"), requests.Timeout("timed out")],
        max_retries=1,
    )

    with pytest.raises(ITunesSearchError):
        client.search(term=EXAMPLE_TERM, entity=EXAMPLE_ENTITY)

    assert len(session.calls) == 2
    assert sleeps == [0.5]
