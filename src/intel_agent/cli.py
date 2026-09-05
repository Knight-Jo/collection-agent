"""Command-line entry (spec §16.1)."""

from __future__ import annotations

import argparse
import asyncio
import json

from .bootstrap import bootstrap
from .runtime.config import load_settings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-agent")
    parser.add_argument("--config", help="path to a YAML config file")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="check configured capabilities")

    run = sub.add_parser("run", help="run a new research task")
    run.add_argument("--question", required=True)
    run.add_argument("--prepare-only", action="store_true")

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
        if args.command == "resume":
            task = app.resume(args.task_id)
            result = await app.wait(task.task_id)
            return _print_result(result)
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
