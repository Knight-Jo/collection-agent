"""Draft and publication lifecycle for task research reports."""

from __future__ import annotations

from pathlib import Path

from .models import (
    ActionRequest,
    IntelError,
    ReportVersion,
    new_id,
)
from .report import render_verified_report
from .state_store import StateStore
from .storage import sha256, workspace_path, write_file_atomic
from .task import load_task


class ReportPublisher:
    """Render committed facts into immutable draft report versions."""

    def __init__(self, cwd: Path, *, store: StateStore | None = None) -> None:
        self.cwd = cwd
        self.store = store or StateStore(cwd)

    def report_ready(self, task_id: str) -> bool:
        """Whether committed state contains the verified report inputs."""
        return all(
            self.store.committed_asset_ids(task_id, asset_type)
            for asset_type in ("fact", "evidence", "review", "coverage")
        )

    def create_draft(self, task_id: str) -> ReportVersion:
        """Return the current report or create a hash-bound draft."""
        if not self.report_ready(task_id):
            raise IntelError(
                "REPORT_NOT_READY",
                "已提交研究状态缺少事实、证据、审核或覆盖评估",
            )
        state_version = self.store.committed_state_version(task_id)
        snapshot = self.store.committed_snapshot(task_id, state_version)
        for existing in reversed(self.store.list_reports(task_id)):
            if (
                existing.status in {"draft", "published"}
                and existing.based_on_committed_state_version == state_version
            ):
                return self.read(existing.id)[0]
        report_id = new_id("report")
        relative_path = f"output/report-versions/{report_id}.md"
        legacy = load_task(self.cwd, task_id).outputs.report
        if legacy is not None:
            source = workspace_path(self.cwd, legacy.path)
            if source.is_file():
                content = source.read_bytes()
                if sha256(content) == legacy.content_sha256:
                    write_file_atomic(self.cwd, relative_path, content)
                    return self.store.create_report_draft(
                        task_id,
                        relative_path,
                        legacy.content_sha256,
                        report_id=report_id,
                        expected_current_state_version=state_version,
                        expected_snapshot_fingerprint=snapshot.fingerprint,
                        publication_origin="legacy_migration",
                    )
        result = render_verified_report(
            self.cwd,
            task_id,
            allowed_fact_ids={
                item.logical_id
                for item in snapshot.asset_manifest
                if item.asset_type == "fact"
            }
            if snapshot.asset_manifest
            else self.store.committed_asset_ids(task_id, "fact"),
            output_path=relative_path,
            snapshot=snapshot,
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
            expected_current_state_version=state_version,
            expected_snapshot_fingerprint=snapshot.fingerprint,
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
        report, _content = self.read(report_id)
        published = self.store.publish_report(
            report_id,
            publish_stale=publish_stale,
            expected_current_state_version=expected_current_state_version,
        )
        return published

    def read(self, report_id: str) -> tuple[ReportVersion, str]:
        """Read one report version after path and hash verification."""
        report = self.store.get_report(report_id)
        path = workspace_path(self.cwd, report.content_path)
        if (
            not path.is_file()
            or sha256(path.read_bytes()) != report.content_sha256
        ):
            raise IntelError("REPORT_TAMPERED", "报告文件缺失或哈希不匹配")
        return report, path.read_text(encoding="utf-8")

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
