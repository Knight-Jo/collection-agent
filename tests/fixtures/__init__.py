"""Fixed, human-labeled quality-evaluation cases (spec 002 SC-102/201).

These are deterministic fixtures: the monitor diff classifier and the
fact-check verdict adjudicator are pure functions, so the labeled cases test
them without network or model calls.
"""

from __future__ import annotations

# (baseline: {fact_key: statement}, current: {fact_key: statement},
#  expected_new: set, expected_changed: set)
MONITOR_DIFF_CASES: list[tuple[dict, dict, set, set]] = [
    ({}, {"k1": "a"}, {"k1"}, set()),
    ({"k1": "a"}, {}, set(), set()),
    ({"k1": "a"}, {"k1": "a"}, set(), set()),
    ({"k1": "a"}, {"k1": "b"}, set(), {"k1"}),
    ({"k1": "a", "k2": "x"}, {"k1": "a", "k3": "y"}, {"k3"}, set()),
    ({"k1": "a", "k2": "x"}, {"k2": "y"}, set(), {"k2"}),
    (
        {"k1": "a", "k2": "x", "k3": "z"},
        {"k1": "a", "k2": "x", "k3": "z"},
        set(),
        set(),
    ),
    ({"k1": "a"}, {"k1": "a", "k2": "b"}, {"k2"}, set()),
    ({"k1": "a", "k2": "x"}, {"k2": "x"}, set(), set()),
    (
        {"k1": "a"},
        {"k1": "a "},
        set(),
        set(),
    ),  # trailing space differs -> changed
    ({"k1": "a", "k2": "x"}, {"k2": "x", "k1": "a"}, set(), set()),
    ({}, {}, set(), set()),
    ({"k1": "a"}, {"k1": "a", "k2": "b", "k3": "c"}, {"k2", "k3"}, set()),
    ({"k1": "a", "k2": "x"}, {"k1": "b", "k2": "x"}, set(), {"k1"}),
    ({"k1": "a", "k2": "x"}, {"k1": "b", "k2": "y"}, set(), {"k1", "k2"}),
    ({"k1": "a", "k2": "x"}, {"k1": "b", "k3": "z"}, {"k3"}, {"k1"}),
    ({"k1": "a"}, {"k2": "b"}, {"k2"}, set()),
    ({"k1": "a", "k2": "x", "k3": "z"}, {"k1": "a", "k2": "x"}, set(), set()),
    ({"k1": "a"}, {"k1": "a", "k1b": "c"}, {"k1b"}, set()),
    ({"k1": "a", "k2": "x"}, {"k2": "y", "k4": "w"}, {"k4"}, {"k2"}),
]


# (evidence specs: [(relation, independence_group, source_nature), ...],
#  expected_verdict)
# relation: "supports" | "contradicts"; nature: "primary" | "secondary" | "unknown"
VERDICT_CASES: list[tuple[list[tuple], str]] = [
    ([], "insufficient"),
    (
        [("supports", "g1", "unknown")],
        "insufficient",
    ),  # no confirmed independent
    ([("supports", "g1", "primary")], "mostly_supported"),
    (
        [("supports", "g1", "primary"), ("supports", "g2", "primary")],
        "supported",
    ),
    (
        [("supports", "g1", "primary"), ("supports", "g2", "secondary")],
        "supported",
    ),
    (
        [("supports", "g1", "primary"), ("supports", "g1", "primary")],
        "mostly_supported",
    ),
    ([("contradicts", "g1", "primary")], "mostly_refuted"),
    (
        [("contradicts", "g1", "primary"), ("contradicts", "g2", "primary")],
        "refuted",
    ),
    (
        [("supports", "g1", "primary"), ("contradicts", "g2", "primary")],
        "disputed",
    ),
    ([("supports", "g1", "secondary")], "insufficient"),
    (
        [("supports", "g1", "secondary"), ("supports", "g2", "secondary")],
        "mostly_supported",
    ),
    (
        [("supports", "g1", "primary"), ("contradicts", "g1", "primary")],
        "disputed",
    ),
    ([("contradicts", "g1", "secondary")], "insufficient"),
    (
        [("supports", "g1", "unknown"), ("contradicts", "g2", "unknown")],
        "disputed",
    ),
    (
        [
            ("supports", "g1", "primary"),
            ("supports", "g2", "primary"),
            ("contradicts", "g3", "primary"),
        ],
        "disputed",
    ),
    (
        [
            ("supports", "g1", "primary"),
            ("supports", "g2", "primary"),
            ("supports", "g3", "primary"),
        ],
        "supported",
    ),
    (
        [
            ("contradicts", "g1", "primary"),
            ("contradicts", "g2", "primary"),
            ("contradicts", "g3", "primary"),
        ],
        "refuted",
    ),
    (
        [
            ("supports", "g1", "primary"),
            ("supports", "g2", "secondary"),
            ("contradicts", "g3", "secondary"),
        ],
        "disputed",
    ),
    (
        [
            ("supports", "g1", "primary"),
            ("supports", "g2", "primary"),
            ("supports", "g3", "secondary"),
        ],
        "supported",
    ),
    (
        [("contradicts", "g1", "primary"), ("contradicts", "g2", "secondary")],
        "refuted",
    ),
    (
        [
            ("supports", "g1", "primary"),
            ("supports", "g2", "secondary"),
            ("supports", "g3", "secondary"),
        ],
        "supported",
    ),
    (
        [
            ("contradicts", "g1", "primary"),
            ("contradicts", "g2", "primary"),
            ("contradicts", "g3", "secondary"),
        ],
        "refuted",
    ),
    (
        [
            ("supports", "g1", "primary"),
            ("contradicts", "g2", "primary"),
            ("contradicts", "g3", "secondary"),
        ],
        "disputed",
    ),
    (
        [
            ("supports", "g1", "primary"),
            ("supports", "g2", "primary"),
            ("contradicts", "g1", "primary"),
        ],
        "disputed",
    ),
    (
        [
            ("supports", "g1", "primary"),
            ("supports", "g2", "primary"),
            ("contradicts", "g3", "primary"),
            ("contradicts", "g4", "primary"),
        ],
        "disputed",
    ),
    (
        [
            ("supports", "g1", "primary"),
            ("supports", "g2", "primary"),
            ("supports", "g3", "primary"),
            ("supports", "g4", "primary"),
        ],
        "supported",
    ),
    (
        [
            ("contradicts", "g1", "primary"),
            ("contradicts", "g2", "primary"),
            ("contradicts", "g3", "primary"),
            ("contradicts", "g4", "primary"),
        ],
        "refuted",
    ),
    (
        [("supports", "g1", "secondary"), ("contradicts", "g2", "secondary")],
        "disputed",
    ),
    (
        [("supports", "g1", "unknown"), ("supports", "g2", "unknown")],
        "insufficient",
    ),
    ([("contradicts", "g1", "unknown")], "insufficient"),
]


def verdict_direction(verdict: str) -> str:
    if verdict == "supported" or verdict == "mostly_supported":
        return "support"
    if verdict == "refuted" or verdict == "mostly_refuted":
        return "refute"
    if verdict == "disputed":
        return "dispute"
    return "insufficient"
