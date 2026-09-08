"""Junk-chunk heuristics tested against samples from a real 253-artifact run.

The junk fixtures below are verbatim chunk texts observed in the
Russia-Ukraine research task, where link-list chunks crowded the evidence
block; the prose fixtures are body chunks from the same run that must pass.
"""

from __future__ import annotations

from intel_agent.indexing.quality import (
    is_junk_chunk,
    is_navigation_list,
    prose_residue,
    strip_links,
)

JUNK_SAMPLES = [
    # citation backlink soup from a Wikipedia references section
    '49. **[^](#cite_ref-49)**[> "Naftali Bennett"\n\n'
    "](https://twitter.com/naftalibennett/status/1622571824008642566)"
    "> . *> Twitter > . R",
    # numbered retrieved-lines list
    "247. ↑\"Zelensky presents 'victory plan' to Ukrainian parliament\". "
    "bbc.com. 16 October 2024. Retrieved 20 October 2024.",
    # navigation box: every line a bullet link
    "* [Zarichne](https://en.wikipedia.org/wiki/Zarichne_barracks_airstrike)"
    "\n* [Mykolaiv strikes](https://en.wikipedia.org/wiki/Mykolaiv_strikes)"
    "\n* [Siege of Mariupol](https://en.wikipedia.org/wiki/Siege_of_Mariupol)"
    "\n* [Battle of Bakhmut](https://en.wikipedia.org/wiki/Battle_of_Bakhmut)",
    # external-link dump
    "](https://web.archive.org/web/20220321191930/https://www.trtworld.com/"
    "magazine/what-could-a-ukraine-russia-peace-agreement-look-like-55615)"
    "> from the original on 21 March 2022.",
    # tiny fragment
    "Retrieved 15 March",
]

PROSE_SAMPLES = [
    "A spokesperson for Zelenskyy said the talks had addressed Donbas and "
    "the fate of the Russian-controlled Zaporizhzhia Nuclear Power Plant, "
    "both sticking points in the negotiations.",
    "The meeting on 17 February took place in the afternoon, after the US "
    "delegation met with an Iranian delegation, also in Geneva, to discuss "
    "Iran's nuclear programme.",
    # prose with two inline links stays prose
    "据 [路透社](https://reuters.com/a) 报道，双方在白俄罗斯边境举行了新一轮会谈，"
    "谈判重点围绕停火安排与战俘交换展开；详见 [报道原文](https://example.com/b)。"
    "谈判代表表示，双方同意继续维持人道主义走廊的临时安排。",
]


def test_junk_samples_are_rejected():
    for sample in JUNK_SAMPLES:
        assert is_junk_chunk(sample), sample[:50]


def test_prose_samples_survive():
    for sample in PROSE_SAMPLES:
        assert not is_junk_chunk(sample), sample[:50]


def test_prose_residue_bounds():
    assert prose_residue("") == 0
    assert prose_residue("plain text without any links here") == 28
    dense = "[a](https://x.com/1) [b](https://x.com/2) [c](https://x.com/3)"
    assert prose_residue(dense) == 0  # only the labels survive, all one-char
    assert "http" not in strip_links("see https://x.com/a now")


def test_navigation_list_detection():
    assert is_navigation_list(
        "* [a](https://x.com/a)\n* [b](https://x.com/b)\n"
        "* [c](https://x.com/c)\n* [d](https://x.com/d)"
    )
    assert not is_navigation_list(
        "正文段落一。\n正文段落二。\n正文段落三。\n正文段落四。"
    )
