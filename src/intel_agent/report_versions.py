"""Draft and publication lifecycle for task research reports."""

from __future__ import annotations

from pathlib import Path

from .models import ActionRequest, IntelError, ReportVersion, new_id
from .report import render_verified_report
from .state_store import StateStore
from .storage import sha256, workspace_path


class ReportPublisher:
    """Render committed facts into immutable draft report versions."""

    def __init__(self, cwd: Path, *, store: StateStore | None = None) -> None:
        self.cwd = cwd
        self.store = store or StateStore(cwd)

    def create_draft(self, task_id: str) -> ReportVersion:
        """Create a hash-bound draft without replacing the legacy report."""
        report_id = new_id("report")
        relative_path = f"output/report-versions/{report_id}.md"
        result = render_verified_report(
            self.cwd,
            task_id,
            allowed_fact_ids=self.store.committed_asset_ids(task_id, "fact"),
            output_path=relative_path,
        )
        if not result.get("ok"):
            errors = result.get("errors", [])
            message = errors[0]["message"] if errors else "报告生成失败"
            raise IntelError("REPORT_FAILED", str(message))
        path = workspace_path(self.cwd, relative_path)
        report = self.store.create_report_draft(
            task_id,
            relative_path,
            sha256(path.read_bytes()),
            report_id=report_id,
        )
        return report

    def publish(
        self,
        report_id: str,
        *,
        publish_stale: bool = False,
        expected_current_state_version: int | None = None,
    ) -> ReportVersion:
        """Publish a verified draft, atomically superseding the prior version."""
        report = self.store.get_report(report_id)
        path = workspace_path(self.cwd, report.content_path)
        if (
            not path.exists()
            or sha256(path.read_bytes()) != report.content_sha256
        ):
            raise IntelError("REPORT_TAMPERED", "报告草稿缺失或哈希不匹配")
        published = self.store.publish_report(
            report_id,
            publish_stale=publish_stale,
            expected_current_state_version=expected_current_state_version,
        )
        return published

    async def run(self, action: ActionRequest) -> ActionRequest:
        """Execute a queued report action for ConversationRuntime."""
        try:
            self.store.transition_action(action.id, "executing")
            report = self.create_draft(action.task_id)
            return self.store.transition_action(
                action.id,
                "succeeded",
                created_report_version_id=report.id,
            )
        except Exception as error:
            current = self.store.get_action(action.id)
            if current.status == "executing":
                return self.store.transition_action(
                    action.id, "failed", error=str(error)
                )
            return current
