"""Read-only library aggregation across research, monitor, fact-check, media."""

from __future__ import annotations


class Library:
    """Composes per-business read summaries for the library surface."""

    def __init__(
        self,
        conversation_service,
        monitoring_service,
        factcheck_service,
        media_service,
    ) -> None:
        self.conversations = conversation_service
        self.monitoring = monitoring_service
        self.factcheck = factcheck_service
        self.media = media_service

    def summary(self) -> dict:
        return {
            "research": self.conversations.library_research(),
            "monitors": self._monitors(),
            "factChecks": self._fact_checks(),
            "media": self._media(),
        }

    def _monitors(self) -> list[dict]:
        return [
            self.monitoring.get(m.monitor_id).model_dump(mode="json")
            for m in self.monitoring.list()
        ]

    def _fact_checks(self) -> list[dict]:
        return [
            self.factcheck.get(fc.fact_check_id).model_dump(mode="json")
            for fc in self.factcheck.list()
        ]

    def _media(self) -> list[dict]:
        return [
            self.media.get(m.media_job_id).model_dump(mode="json")
            for m in self.media.list()
        ]
