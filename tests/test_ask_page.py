"""Tests for the 'Ask the data' page: usage limits and a render smoke test (DL-026)."""
import datetime as dt
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
import ask_limits  # noqa: E402


def test_daily_cap_counts_per_day_and_resets_at_midnight():
    day = [dt.date(2026, 11, 12)]
    cap = ask_limits.DailyCap(limit=2, today=lambda: day[0])
    assert cap.try_take() and cap.try_take()
    assert not cap.try_take()
    assert cap.used_today == 2
    day[0] = dt.date(2026, 11, 13)
    assert cap.used_today == 0 and cap.try_take()


def test_session_limit_is_5_for_visitors_and_higher_for_the_owner():
    assert ask_limits.session_limit(owner=False) == 5
    assert ask_limits.session_limit(owner=True) > 5
    assert ask_limits.session_allows(4, 5) and not ask_limits.session_allows(5, 5)


def test_owner_key_must_be_configured_and_match():
    assert ask_limits.is_owner("s3cret-key", "s3cret-key")
    assert not ask_limits.is_owner("wrong", "s3cret-key")
    assert not ask_limits.is_owner("", "s3cret-key")
    assert not ask_limits.is_owner("anything", None)     # no key configured: nobody is owner
    assert not ask_limits.is_owner(None, None)


def test_page_renders_without_touching_the_database_or_the_model(monkeypatch):
    monkeypatch.setenv("ASK_MODEL", "oracle")
    at = AppTest.from_file(str(ROOT / "dashboard/ask_page.py"), default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Ask the data"
    assert len(at.button) >= 4 and at.text_area[0].max_chars == 300


def test_owner_key_in_the_link_raises_the_limit_and_is_removed_from_the_url(monkeypatch):
    monkeypatch.setenv("ASK_MODEL", "oracle")
    monkeypatch.setenv("ASK_OWNER_KEY", "s3cret-key")
    at = AppTest.from_file(str(ROOT / "dashboard/ask_page.py"), default_timeout=30)
    at.query_params["key"] = "s3cret-key"
    at.run()
    assert at.session_state.owner is True
    assert "key" not in at.query_params
    assert any("of 50 questions left" in c.value for c in at.caption)


def test_wrong_owner_key_gives_the_visitor_limit(monkeypatch):
    monkeypatch.setenv("ASK_MODEL", "oracle")
    monkeypatch.setenv("ASK_OWNER_KEY", "s3cret-key")
    at = AppTest.from_file(str(ROOT / "dashboard/ask_page.py"), default_timeout=30)
    at.query_params["key"] = "guess"
    at.run()
    assert at.session_state.owner is False
    assert any("of 5 questions left" in c.value for c in at.caption)
