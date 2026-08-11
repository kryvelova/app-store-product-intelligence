import pytest

from ingestion.config import load_search_config


REQUIRED_VARS = ("APP_STORE_SEARCH_TERM", "APP_STORE_COUNTRY", "APP_STORE_ENTITY", "APP_STORE_LIMIT")


def _clear_env(monkeypatch):
    for name in REQUIRED_VARS:
        monkeypatch.delenv(name, raising=False)


def _set_valid_env(monkeypatch, **overrides):
    values = {
        "APP_STORE_SEARCH_TERM": "example-app",
        "APP_STORE_COUNTRY": "DE",
        "APP_STORE_ENTITY": "exampleEntityType",
        "APP_STORE_LIMIT": "10",
        **overrides,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_load_search_config_reads_from_environment(monkeypatch):
    _clear_env(monkeypatch)
    _set_valid_env(monkeypatch)

    config = load_search_config()

    assert config.term == "example-app"
    assert config.country == "DE"
    assert config.entity == "exampleEntityType"
    assert config.limit == 10


def test_load_search_config_raises_when_missing(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("APP_STORE_SEARCH_TERM", "example-app")
    # APP_STORE_COUNTRY, APP_STORE_ENTITY, APP_STORE_LIMIT intentionally left unset.

    with pytest.raises(RuntimeError):
        load_search_config()


def test_load_search_config_raises_when_all_missing(monkeypatch):
    _clear_env(monkeypatch)

    with pytest.raises(RuntimeError):
        load_search_config()


def test_load_search_config_raises_on_non_integer_limit(monkeypatch):
    _clear_env(monkeypatch)
    _set_valid_env(monkeypatch, APP_STORE_LIMIT="not-a-number")

    with pytest.raises(RuntimeError):
        load_search_config()
