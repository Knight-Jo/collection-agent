"""Read red-team rounds persisted by earlier releases."""

from pathlib import Path

from .models import ChallengeRound, IntelError
from .storage import intel_path, read_json


def list_challenge_rounds(
    cwd: Path, task_id: str | None = None
) -> list[ChallengeRound]:
    """Return validated historical challenge rounds."""
    if not intel_path(cwd, "challenges.json").exists():
        return []
    store = read_json(cwd, "challenges.json")
    if not isinstance(store, dict) or not isinstance(store.get("items"), list):
        raise IntelError("STORAGE_CORRUPT", "challenges.json 缺少 items")
    rounds = [ChallengeRound.model_validate(item) for item in store["items"]]
    return (
        [item for item in rounds if item.task_id == task_id]
        if task_id
        else rounds
    )
