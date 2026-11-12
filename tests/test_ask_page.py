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


def test_session_limit():
    assert ask_limits.session_allows(ask_limits.PER_SESSION - 1)
    assert not ask_limits.session_allows(ask_limits.PER_SESSION)


def test_page_renders_without_touching_the_database_or_the_model(monkeypatch):
    monkeypatch.setenv("ASK_MODEL", "oracle")
    at = AppTest.from_file(str(ROOT / "dashboard/ask_page.py"), default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Ask the data"
    assert len(at.button) >= 4 and at.text_area[0].max_chars == 300
