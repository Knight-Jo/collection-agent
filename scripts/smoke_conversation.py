#!/usr/bin/env python3
"""Run one Conversation-first smoke check against the local Web API."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from collections.abc import Callable
from typing import Any
from urllib.request import Request, urlopen

Opener = Callable[..., Any]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test the Conversation-first research workbench"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:6780")
    parser.add_argument("--conversation-id")
    parser.add_argument("--task-id")
    parser.add_argument("--question", required=True)
    parser.add_argument("--continuation", default=None)
    parser.add_argument("--confirm-proposal", action="store_true")
    parser.add_argument(
        "--auth-token-env",
        help="包含 Web Bearer Token 的环境变量名",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser


def run_smoke(
    *,
    base_url: str,
    task_id: str | None,
    conversation_id: str | None = None,
    question: str,
    timeout: float,
    continuation: str | None = None,
    confirm_proposal: bool = False,
    auth_token: str | None = None,
    opener: Opener = urlopen,
) -> dict[str, object]:
    """Ask one question and optionally queue one continuation."""
    base_url = base_url.rstrip("/")
    if task_id is not None:
        task = _request_json(
            opener,
            base_url,
            f"/api/tasks/{task_id}",
            timeout,
            auth_token=auth_token,
        )
        if task.get("task", {}).get("id") != task_id:
            raise RuntimeError("task response does not match --task-id")
        resource = f"/api/tasks/{task_id}/conversation"
    else:
        if conversation_id is None:
            created = _request_json(
                opener,
                base_url,
                "/api/conversations",
                timeout,
                method="POST",
                payload={},
                auth_token=auth_token,
            )
            conversation_id = str(created["id"])
        resource = f"/api/conversations/{conversation_id}"

    submitted = _post_message(
        opener, base_url, resource, question, timeout, auth_token
    )
    assistant_id = _wait_for_answer(
        opener,
        base_url,
        resource,
        str(submitted["id"]),
        timeout,
        auth_token,
    )
    answer = _request_json(
        opener,
        base_url,
        f"/api/messages/{assistant_id}",
        timeout,
        auth_token=auth_token,
    )

    continuation_status = None
    if continuation:
        submitted = _post_message(
            opener, base_url, resource, continuation, timeout, auth_token
        )
        _wait_for_answer(
            opener,
            base_url,
            resource,
            str(submitted["id"]),
            timeout,
            auth_token,
        )
        projection = _request_json(
            opener, base_url, resource, timeout, auth_token=auth_token
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
                    auth_token=auth_token,
                )
                continuation_status = confirmed.get("status")

    if task_id is None:
        projection = _request_json(
            opener, base_url, resource, timeout, auth_token=auth_token
        )
        task_id = projection.get("conversation", {}).get("task_id")
    result = {
        "task_id": task_id,
        "message_status": answer.get("status"),
        "answer_chars": len(str(answer.get("content", ""))),
        "citation_count": len(answer.get("citations", [])),
        "continuation_status": continuation_status,
    }
    if conversation_id is not None:
        result["conversation_id"] = conversation_id
    return result


def _post_message(
    opener: Opener,
    base_url: str,
    resource: str,
    content: str,
    timeout: float,
    auth_token: str | None,
) -> dict[str, object]:
    return _request_json(
        opener,
        base_url,
        f"{resource}/messages",
        timeout,
        method="POST",
        payload={"content": content, "client_message_id": str(uuid.uuid4())},
        auth_token=auth_token,
    )


def _wait_for_answer(
    opener: Opener,
    base_url: str,
    resource: str,
    user_message_id: str,
    timeout: float,
    auth_token: str | None,
) -> str:
    headers = {"Accept": "text/event-stream"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    request = Request(
        base_url + f"{resource}/events",
        headers=headers,
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
                if event_type == "answer.failed" and data:
                    payload = json.loads(data)
                    if payload.get("reply_to_id") == user_message_id:
                        raise RuntimeError(
                            f"answer.failed for message {user_message_id}"
                        )
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
    auth_token: str | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    request = Request(
        base_url + path,
        data=body,
        method=method,
        headers=headers,
    )
    with opener(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object from {path}")
    return value


def main() -> None:
    args = build_parser().parse_args()
    auth_token = (
        os.environ.get(args.auth_token_env) if args.auth_token_env else None
    )
    if args.auth_token_env and not auth_token:
        raise SystemExit(f"环境变量 {args.auth_token_env} 未设置")
    metrics = run_smoke(
        base_url=args.base_url,
        task_id=args.task_id,
        conversation_id=args.conversation_id,
        question=args.question,
        continuation=args.continuation,
        confirm_proposal=args.confirm_proposal,
        timeout=args.timeout,
        auth_token=auth_token,
    )
    print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
