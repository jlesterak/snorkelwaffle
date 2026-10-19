"""Startup warnings for half-set config (found on a deploy where rescans silently never ran)."""

from snorkelwaffle.config import Env


def test_abs_url_without_token_warns():
    assert any("ABS_TOKEN" in w for w in Env(abs_url="http://abs:13378").warnings())


def test_token_without_url_warns():
    assert any("ABS_URL is not" in w for w in Env(abs_token="t").warnings())


def test_both_or_neither_is_quiet():
    assert Env().warnings() == []
    assert Env(abs_url="http://abs:13378", abs_token="t").warnings() == []
