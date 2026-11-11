"""Answer one question: model -> checker -> read-only database (DL-026).

    answer(question, conn, client, model) -> Answer

The model replies with {"status", "sql", "reason"}. Its SQL goes through the
query checker (nlq/guard.py) and runs read-only (nlq/db.py). If the checker
rejects the query or the database returns an error, the reason goes back to the
model once (guardrail 4); then it stops.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from nlq.db import run_readonly
from nlq.guard import check
from nlq.prompt import OUTPUT_SCHEMA, system_prompt

MAX_QUESTION_CHARS = 300
MAX_ATTEMPTS = 2           # first try + one retry
MAX_TOKENS = 4000          # room for adaptive thinking plus a short JSON reply

# USD per million tokens: input, output, cache write (5 min), cache read.
# Checked 2026-11-11 on platform.claude.com (Haiku 5.5: prompts up to 100K tokens).
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.10),
}


@dataclass
class Answer:
    question: str
    status: str = "error"          # answered | refused | blocked | error | too_long
    reason: str = ""
    sql: str | None = None         # the checked SQL that ran
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    attempts: int = 0
    model_sql: list = field(default_factory=list)       # every query the model wrote
    rejections: list = field(default_factory=list)      # checker or database errors fed back
    unsafe_sql_written: bool = False                    # the checker rejected a model query
    usage: dict = field(default_factory=lambda: {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0})
    seconds: float = 0.0

    def cost_usd(self, model: str) -> float | None:
        if model not in PRICES:
            return None
        p_in, p_out, p_cw, p_cr = PRICES[model]
        u = self.usage
        return (u["input"] * p_in + u["output"] * p_out
                + u["cache_write"] * p_cw + u["cache_read"] * p_cr) / 1e6


def _parse(text: str) -> dict:
    """The model's JSON reply; tolerant of stray text around it."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError(f"no JSON object in reply: {text[:200]!r}")
        return json.loads(m.group(0))


class ModelCaller:
    """Calls the Messages API with the cached system prompt and JSON output."""

    def __init__(self, client, model: str, effort: str | None = None):
        self.client, self.model, self.effort = client, model, effort
        self.use_json_schema = True

    def __call__(self, messages: list) -> tuple[dict, object]:
        kwargs = dict(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}],
            messages=messages,
        )
        output_config = {}
        if self.effort:
            output_config["effort"] = self.effort
        if self.use_json_schema:
            output_config["format"] = {"type": "json_schema", "schema": OUTPUT_SCHEMA}
        if output_config:
            kwargs["output_config"] = output_config
        try:
            resp = self.client.messages.create(**kwargs)
        except Exception as e:   # model or account without structured outputs: ask in text instead
            if self.use_json_schema and "format" in str(e).lower():
                self.use_json_schema = False
                return self(messages)
            raise
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return _parse(text), resp


def _add_usage(answer: Answer, resp) -> None:
    u = resp.usage
    answer.usage["input"] += u.input_tokens or 0
    answer.usage["output"] += u.output_tokens or 0
    answer.usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
    answer.usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0


def _assistant_turn(resp) -> dict:
    blocks = [b.model_dump() if hasattr(b, "model_dump") else b for b in resp.content]
    return {"role": "assistant", "content": blocks}


def answer(question: str, conn, call: ModelCaller) -> Answer:
    start = time.monotonic()
    a = Answer(question=question)
    q = " ".join(question.split())
    if not q:
        a.status, a.reason = "refused", "Please type a question."
        return a
    if len(q) > MAX_QUESTION_CHARS:
        a.status, a.reason = "too_long", f"Please keep questions under {MAX_QUESTION_CHARS} characters."
        return a

    messages = [{"role": "user", "content": f"<question>{q}</question>"}]
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            a.attempts = attempt
            reply, resp = call(messages)
            _add_usage(a, resp)
            a.reason = str(reply.get("reason", ""))
            if reply.get("status") != "sql":
                a.status = "refused"
                return a

            sql = str(reply.get("sql", ""))
            a.model_sql.append(sql)
            guarded = check(sql)
            if not guarded.ok:
                a.unsafe_sql_written = True
                problem = f"The query checker rejected it: {guarded.reason}"
            else:
                try:
                    a.columns, a.rows = run_readonly(conn, guarded.sql)
                    a.sql, a.status = guarded.sql, "answered"
                    return a
                except Exception as e:   # database error: feed back its first line
                    problem = f"The database returned an error: {str(e).strip().splitlines()[0][:300]}"
            a.rejections.append(problem)
            messages += [_assistant_turn(resp),
                         {"role": "user", "content": f"{problem}\nReply again with a corrected query, or refuse."}]
        a.status = "blocked"
        a.reason = "I couldn't write a query that passed the checks for this question."
        return a
    except Exception as e:
        a.status, a.reason = "error", f"{type(e).__name__}: {str(e)[:200]}"
        return a
    finally:
        a.seconds = time.monotonic() - start
