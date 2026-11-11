"""Tests for the model's instructions and worked examples (DL-026)."""
import re
from pathlib import Path

import yaml

from nlq.guard import ALLOWED_TABLES, check
from nlq.prompt import EXAMPLES_YML, MARTS_YML, prompt_hash, system_prompt

ROOT = Path(__file__).resolve().parents[1]
ACCURACY = yaml.safe_load((ROOT / "nlq/evals/accuracy.yaml").read_text(encoding="utf-8"))["questions"]
ATTACKS = yaml.safe_load((ROOT / "nlq/evals/attacks.yaml").read_text(encoding="utf-8"))["questions"]
EXAMPLES = yaml.safe_load(EXAMPLES_YML.read_text(encoding="utf-8"))["examples"]


def _normal(text):
    return re.sub(r"\W+", " ", text.lower()).strip()


def test_prompt_describes_every_allowed_table_and_every_documented_column():
    prompt = system_prompt()
    marts = yaml.safe_load(MARTS_YML.read_text(encoding="utf-8"))["models"]
    assert {m["name"] for m in marts} == set(ALLOWED_TABLES)
    for m in marts:
        assert f"### marts.{m['name']}" in prompt
        for col in m["columns"]:
            assert col.get("description"), f"{m['name']}.{col['name']} has no description"
            assert f"- {col['name']}:" in prompt


def test_no_evaluation_question_is_shown_to_the_model():
    prompt = _normal(system_prompt())
    for q in ACCURACY + ATTACKS:
        assert _normal(q["question"]) not in prompt, q["id"]


def test_example_queries_pass_the_checker():
    for e in EXAMPLES:
        if e["status"] == "sql":
            assert check(e["sql"]).ok, e["question"]
        else:
            assert e["sql"] == ""


def test_prompt_hash_is_stable_and_short():
    assert prompt_hash() == prompt_hash()
    assert re.fullmatch(r"[0-9a-f]{12}", prompt_hash())
