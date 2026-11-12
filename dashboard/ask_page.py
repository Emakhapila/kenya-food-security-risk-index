"""'Ask the data' page (DL-026): plain-English questions answered by guarded SQL.

The question goes to a language model, which writes one SQL query; the query
checker (nlq/guard.py) checks it and it runs read-only (nlq/db.py). Visitors see
the answer table, the reason and the exact SQL that ran.

Secrets: the read-only database login (as for the risk page) and
ANTHROPIC_API_KEY. ASK_MODEL picks the model (default claude-haiku-5-5);
ASK_MODEL=oracle answers only the evaluation questions, for local testing
without an API key.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import streamlit as st

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import ask_limits  # noqa: E402
import data        # noqa: E402

from nlq.answer import MAX_QUESTION_CHARS, ModelCaller, answer  # noqa: E402

REPO = "https://github.com/Emakhapila/kenya-food-security-risk-index"
MODEL = os.environ.get("ASK_MODEL", "claude-haiku-5-5")
EXAMPLES = [
    "Which counties have been drier than usual in each of the last 3 complete months?",
    "What is the 3-month maize price forecast for each county?",
    "How has Turkana's risk index changed over the last 12 complete months?",
    "Which counties had 30% or more of people in IPC Phase 3 or worse in the latest analysis?",
]


def secret(name: str) -> str | None:
    """An environment variable, else a Streamlit secret, else None."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        return st.secrets[name]
    except Exception:
        return None


@st.cache_resource
def daily_cap() -> ask_limits.DailyCap:
    return ask_limits.DailyCap()


@st.cache_resource
def model_caller() -> ModelCaller:
    if MODEL == "oracle":
        from nlq.evaluate import OracleClient, load_sets
        caller = ModelCaller(OracleClient(*load_sets()), MODEL)
        caller.use_json_schema = False
        return caller
    import anthropic
    key = secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return ModelCaller(anthropic.Anthropic(api_key=key), MODEL)


@st.cache_resource
def login_is_read_only() -> bool:
    """Refuse to serve questions over a login that can change data (DL-012)."""
    import psycopg
    from nlq.db import can_write
    with psycopg.connect(data.database_url(), autocommit=True) as conn:
        return not can_write(conn)


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=500)
def cached_answer(question: str) -> dict:
    """Same question within 6 hours: same answer, no new model call."""
    import psycopg
    with psycopg.connect(data.database_url(), autocommit=True) as conn:
        a = answer(question, conn, model_caller())
    result = asdict(a)
    result["cost_usd"] = a.cost_usd(MODEL)
    print(json.dumps({"ask": question, "status": a.status, "attempts": a.attempts,
                      "unsafe_sql_written": a.unsafe_sql_written,
                      "cost_usd": result["cost_usd"], "seconds": round(a.seconds, 1)}))
    return result


def show(result: dict) -> None:
    status = result["status"]
    if status == "answered":
        rows = result["rows"]
        if rows:
            st.dataframe(pd.DataFrame(rows, columns=result["columns"]), hide_index=True, width="stretch")
        else:
            st.info("The query ran, but no rows matched.")
        if result["reason"]:
            st.markdown(result["reason"])
        with st.expander("The SQL that ran"):
            st.code(result["sql"], language="sql")
            st.caption("Checked before running: one read-only query on the published tables, "
                       "at most 500 rows, 5-second limit.")
    elif status == "refused":
        st.info(result["reason"] or "This data can't answer that question.")
    elif status == "too_long":
        st.warning(result["reason"])
    elif status == "blocked":
        st.warning("I couldn't write a query that passed the safety checks for this question. "
                   "Try rephrasing it, or ask about one table at a time.")
    else:
        st.error("Something went wrong answering that question. Please try again later.")


st.title("Ask the data")
st.markdown(
    "Ask a question about the risk index, rainfall and vegetation, maize prices or IPC "
    "assessments in plain English. An AI model (Claude Haiku 5.5) writes one SQL query; "
    "the query is checked and run **read-only**, and you see the answer **and the exact "
    "SQL**, so you can check it."
)
st.caption(
    "Tested before release on 30 held-back questions (DL-026): 86% answered correctly "
    "(89% after fixing a bug that testing found), and all 15 attack and out-of-scope "
    "questions blocked. It can still be wrong: check the SQL for anything that matters. "
    "Please don't type personal information."
)

if "asked" not in st.session_state:
    st.session_state.asked = 0
if "owner" not in st.session_state:
    st.session_state.owner = False
if "key" in st.query_params:   # owner link: check once, then remove the key from the address bar
    st.session_state.owner = ask_limits.is_owner(st.query_params["key"], secret("ASK_OWNER_KEY"))
    del st.query_params["key"]
limit = ask_limits.session_limit(st.session_state.owner)
if "question" not in st.session_state:
    st.session_state.question = ""

st.write("Try one:")
cols = st.columns(2)
for i, example in enumerate(EXAMPLES):
    if cols[i % 2].button(example, key=f"ex{i}", width="stretch"):
        st.session_state.question = example

with st.form("ask"):
    question = st.text_area("Your question", key="question", max_chars=MAX_QUESTION_CHARS,
                            height=80, placeholder="e.g. Which counties were strongly unusual last month?")
    submitted = st.form_submit_button("Ask", type="primary")

if submitted and question.strip():
    q = " ".join(question.split())
    if not ask_limits.session_allows(st.session_state.asked, limit):
        st.warning(f"You've reached the limit of {limit} questions for this visit. "
                   "Please come back later.")
    elif not st.session_state.owner and not daily_cap().try_take():
        st.warning("Today's question limit for this free demo has been reached. Please try again tomorrow.")
    else:
        try:
            if not login_is_read_only():
                st.error("This page is switched off: its database login is not read-only.")
                st.stop()
            st.session_state.asked += 1
            with st.spinner("Writing and checking a query…"):
                show(cached_answer(q))
        except Exception:
            traceback.print_exc()
            st.error("Something went wrong answering that question. Please try again later.")

left = max(0, limit - st.session_state.asked)
st.caption(f"{left} of {limit} questions left this visit."
           + (" (owner)" if st.session_state.owner else ""))

st.divider()
st.caption(
    f"How it works and how it was tested: [decision DL-026]({REPO}/blob/main/docs/decisions.md) · "
    f"[code]({REPO}/tree/main/nlq). Your question is sent to Anthropic's API to write the query; "
    "the result rows are not."
)
