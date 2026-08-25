#!/usr/bin/env python3
"""Run one real task-conversation smoke check against the local Web API."""

from __future__ import annotations

import argparse
import json
import uuid
from collections.abc import Callable
from typing import Any
from urllib.request import Request, urlopen

Opener = Callable[..., Any]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test task-scoped evidence dialogue"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:6780")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--continuation", default=None)
    parser.add_argument("--confirm-proposal", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser


def run_smoke(
    *,
    base_url: str,
    task_id: str,
    question: str,
    timeout: float,
    continuation: str | None = None,
    confirm_proposal: bool = False,
    opener: Opener = urlopen,
) -> dict[str, object]:
    """Ask one evidence question and optionally queue one continuation."""
    base_url = base_url.rstrip("/")
    task = _request_json(opener, base_url, f"/api/tasks/{task_id}", timeout)
    if task.get("task", {}).get("id") != task_id:
        raise RuntimeError("task response does not match --task-id")

    submitted = _post_message(opener, base_url, task_id, question, timeout)
    assistant_id = _wait_for_answer(
        opener, base_url, task_id, str(submitted["id"]), timeout
    )
    answer = _request_json(
        opener, base_url, f"/api/messages/{assistant_id}", timeout
    )

    continuation_status = None
    if continuation:
        submitted = _post_message(
            opener, base_url, task_id, continuation, timeout
        )
        _wait_for_answer(
            opener, base_url, task_id, str(submitted["id"]), timeout
        )
        projection = _request_json(
            opener,
            base_url,
            f"/api/tasks/{task_id}/conversation",
            timeout,
        )
        actions = projection.get("actions", [])
        if actions:
            action = actions[-1]
            continuation_status = action.get("status")
            if continuation_status == "proposed" and confirm_proposal:
                confirmed = _request_json(
                    opener,
                    base_url,
                    f"/api/action-requests/{action['id']}/confirm",
                    timeout,
                    method="POST",
                    payload={"client_message_id": str(uuid.uuid4())},
                )
                continuation_status = confirmed.get("status")

    return {
        "task_id": task_id,
        "message_status": answer.get("status"),
        "answer_chars": len(str(answer.get("content", ""))),
        "citation_count": len(answer.get("citations", [])),
        "continuation_status": continuation_status,
    }


def _post_message(
    opener: Opener,
    base_url: str,
    task_id: str,
    content: str,
    timeout: float,
) -> dict[str, object]:
    return _request_json(
        opener,
        base_url,
        f"/api/tasks/{task_id}/conversation/messages",
        timeout,
        method="POST",
        payload={"content": content, "client_message_id": str(uuid.uuid4())},
    )


def _wait_for_answer(
    opener: Opener,
    base_url: str,
    task_id: str,
    user_message_id: str,
    timeout: float,
) -> str:
    request = Request(
        base_url + f"/api/tasks/{task_id}/conversation/events",
        headers={"Accept": "text/event-stream"},
    )
    event_type = ""
    data = ""
    with opener(request, timeout=timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if line.startswith("event:"):
                event_type = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
            elif not line:
                if event_type == "answer.completed" and data:
                    payload = json.loads(data)
                    if payload.get("reply_to_id") == user_message_id:
                        return str(payload["message_id"])
                event_type = ""
                data = ""
    raise RuntimeError("conversation stream ended before answer.completed")


def _request_json(
    opener: Opener,
    base_url: str,
    path: str,
    timeout: float,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        base_url + path,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with opener(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object from {path}")
    return value


def main() -> None:
    args = build_parser().parse_args()
    metrics = run_smoke(
        base_url=args.base_url,
        task_id=args.task_id,
        question=args.question,
        continuation=args.continuation,
        confirm_proposal=args.confirm_proposal,
        timeout=args.timeout,
    )
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
