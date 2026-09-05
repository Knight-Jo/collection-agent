"""Real audio/video ASR transcription (spec A13/A14)."""

from __future__ import annotations

from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"


async def _transcribe(harness, name: str):
    path = SAMPLES / name
    resource = await harness.resource_store.import_file(path)
    profile_id = harness.extraction.profile_for(resource.media_type)
    return await harness.extraction.extract(resource, profile_id)


@pytest.mark.real_backend
@pytest.mark.parametrize("name", ["samples_test_mp3.mp3", "videoplayback.m4a"])
async def test_audio_transcription_produces_timestamped_blocks(harness, name):
    if not (SAMPLES / name).exists():
        pytest.skip(f"sample not present: {name}")
    result = await _transcribe(harness, name)
    assert result.status == "success"
    assert result.blocks
    for block in result.blocks:
        assert block.origin_method == "asr"
        assert block.locator.start_ms is not None
        assert block.locator.end_ms is not None
        assert block.locator.start_ms < block.locator.end_ms
    text = " ".join(b.text for b in result.blocks)
    assert "特朗普" in text


@pytest.mark.real_backend
async def test_video_without_subtitle_uses_asr(harness):
    name = "videoplayback.mp4"
    if not (SAMPLES / name).exists():
        pytest.skip("sample not present")
    result = await _transcribe(harness, name)
    assert result.status == "success"
    assert result.blocks
    assert any(b.origin_method == "asr" for b in result.blocks)
    text = " ".join(b.text for b in result.blocks)
    assert "特朗普" in text
