import pytest

from ingestion.config import load_search_config


REQUIRED_VARS = ("APP_STORE_SEARCH_TERM", "APP_STORE_COUNTRY", "APP_STORE_ENTITY")


def _clear_env(monkeypatch):
    for name in REQUIRED_VARS:
        monkeypatch.delenv(name, raising=False)


def test_load_search_config_reads_from_environment(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("APP_STORE_SEARCH_TERM", "example-app")
    monkeypatch.setenv("APP_STORE_COUNTRY", "DE")
    monkeypatch.setenv("APP_STORE_ENTITY", "exampleEntityType")

    config = load_search_config()

    assert config.term == "example-app"
    assert config.country == "DE"
    assert config.entity == "exampleEntityType"


def test_load_search_config_raises_when_missing(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("APP_STORE_SEARCH_TERM", "example-app")
    # APP_STORE_COUNTRY and APP_STORE_ENTITY intentionally left unset.

    with pytest.raises(RuntimeError):
        load_search_config()


def test_load_search_config_raises_when_all_missing(monkeypatch):
    _clear_env(monkeypatch)

    with pytest.raises(RuntimeError):
        load_search_config()
