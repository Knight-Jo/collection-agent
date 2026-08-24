"""Renderer tests for scripts/analyze_conversation.py."""

import json

from scripts.analyze_conversation import _pretty_json


def test_pretty_json_indents_dict():
    assert _pretty_json({"a": 1}) == '{\n  "a": 1\n}'


def test_pretty_json_unwraps_nested_stringified_json():
    nested = json.dumps(
        {"topic": "x", "criteria": json.dumps({"min_sources": 2})}
    )
    out = _pretty_json(nested)
    assert '"min_sources": 2' in out
    assert '\\"' not in out


def test_pretty_json_passthrough_for_plain_text_and_none():
    assert _pretty_json("不是 JSON") == "不是 JSON"
    assert _pretty_json(None) == ""
