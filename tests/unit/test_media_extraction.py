"""Audio and video pure-function tests (T10/T11)."""

from __future__ import annotations

from intel_agent.contracts.documents import Locator
from intel_agent.extraction.audio import offset_locator
from intel_agent.extraction.video import sample_times


def test_segment_time_is_mapped_to_original_audio():
    result = offset_locator(Locator(start_ms=500, end_ms=1500), 30_000)
    assert (result.start_ms, result.end_ms) == (30_500, 31_500)


def test_sampling_is_bounded_and_uses_original_time():
    assert sample_times(12_000, 5_000, 720) == [0, 5_000, 10_000]
    assert sample_times(12_000, 5_000, 2) == [0, 5_000]
