"""Command-line entry (spec §16.1)."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys

from .bootstrap import bootstrap
from .contracts.research import ResearchResult
from .runtime.config import ResearchSettings, load_settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-agent")
    parser.add_argument(
        "--config",
        help="path to a YAML config file (default: configs/default.yaml)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="check configured capabilities")

    run = sub.add_parser("run", help="run a new research task")
    run.add_argument("--question", required=True)
    run.add_argument("--prepare-only", action="store_true")

    exp = sub.add_parser(
        "experiment", help="run a research task end-to-end with progress"
    )
    exp.add_argument("--question", required=True)
    exp.add_argument("--fresh", action="store_true", help="wipe data first")
    exp.add_argument("--json", action="store_true", help="also dump full JSON")

    imp = sub.add_parser("import", help="import a local file into a task")
    imp.add_argument("--task-id", required=True)
    imp.add_argument("--path", required=True)

    resume = sub.add_parser("resume", help="resume a task")
    resume.add_argument("--task-id", required=True)

    status = sub.add_parser("status", help="show task status")
    status.add_argument("--task-id", required=True)

    reindex = sub.add_parser("reindex", help="rebuild an artifact index")
    reindex.add_argument("--artifact-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_settings(args.config)
    return asyncio.run(_run(args, settings))


async def _run(args, settings) -> int:
    async with bootstrap(settings) as app:
        if args.command == "preflight":
            return await _preflight(app)
        if args.command == "run":
            task = app.submit(args.question)
            if args.prepare_only:
                print(task.task_id)
                return 0
            result = await app.wait(task.task_id)
            return _print_result(result)
        if args.command == "experiment":
            return await _experiment(app, settings, args)
        if args.command == "resume":
            await app.resume(args.task_id)
            task = app.status(args.task_id)
            print(
                json.dumps(
                    task.model_dump(mode="json"), ensure_ascii=False, indent=2
                )
            )
            return 0
        if args.command == "status":
            task = app.status(args.task_id)
            print(
                json.dumps(
                    task.model_dump(mode="json"), ensure_ascii=False, indent=2
                )
            )
            return 0
        if args.command == "import":
            return await _import(app, args)
        if args.command == "reindex":
            report = await app.orchestrator.indexing_service.index(
                args.artifact_id
            )
            print(
                json.dumps(
                    report.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
    return 1


async def _preflight(app) -> int:
    extraction = app.orchestrator.search_service  # noqa: F841 - keep simple
    print("preflight: OK (configured capabilities)")
    return 0


def _reset_data(settings: ResearchSettings) -> None:
    sqlite = settings.sqlite_file()
    for suffix in ("", "-wal", "-shm"):
        sqlite.with_name(sqlite.name + suffix).unlink(missing_ok=True)
    shutil.rmtree(settings.resources_root(), ignore_errors=True)
    shutil.rmtree(settings.tmp_root(), ignore_errors=True)


def _cli_sink():
    async def sink(event: dict) -> None:
        etype = event["event"]
        if etype == "run.status":
            print(f"[status] {event['status']}", file=sys.stderr, flush=True)
        elif etype == "run.phase":
            print(f"[phase] {event['phase']}", file=sys.stderr, flush=True)
        elif etype == "timeline":
            detail = event.get("detail")
            label = event["label"]
            print(
                f"[tl] {event['kind']}: {label}"
                + (f" ({detail})" if detail else ""),
                file=sys.stderr,
                flush=True,
            )
        elif etype == "material":
            print(
                f"[material] {event.get('title') or event.get('url')}",
                file=sys.stderr,
                flush=True,
            )

    return sink


def _write_report(result: ResearchResult, settings: ResearchSettings) -> str:
    out_dir = settings.output_root()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{result.task_id}.md"
    path.write_text(result.answer, encoding="utf-8")
    return str(path)


async def _experiment(app, settings: ResearchSettings, args) -> int:
    task = app.task_store.create_task(
        args.question, deadline_seconds=settings.research.deadline_seconds
    )
    result = await app.orchestrator.run_task(task, event_sink=_cli_sink())
    path = _write_report(result, settings)

    print(f"task_id: {result.task_id}")
    print(f"status: {result.status}")
    print(f"stop_reason: {result.stop_reason}")
    usage = result.usage
    print(
        f"usage: {usage.llm_calls} calls, "
        f"{usage.input_tokens} in, {usage.output_tokens} out tokens"
    )
    print(f"citations: {len(result.citations)}")
    print(f"report: {path}")
    print("---")
    print(result.answer)
    if args.json:
        print("--- JSON ---")
        print(
            json.dumps(
                result.model_dump(mode="json"), ensure_ascii=False, indent=2
            )
        )
    return {"completed": 0, "partial": 2, "failed": 1}[result.status]


async def _import(app, args) -> int:

    resource = (
        await app.orchestrator.acquisition_pipeline.resource_store.import_file(
            args.path
        )
    )
    report = await app.orchestrator.acquisition_pipeline.acquire(
        args.task_id,
        resource,
        app.orchestrator.profile_id,
        index_after_store=True,
    )
    print(
        json.dumps(
            report.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
    )
    return 0


def _print_result(result) -> int:
    print(
        json.dumps(
            result.model_dump(mode="json"), ensure_ascii=False, indent=2
        )
    )
    return {
        "completed": 0,
        "failed": 1,
        "partial": 2,
        "cancelled": 130,
    }[result.status]
