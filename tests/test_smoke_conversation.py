from __future__ import annotations

import io
import json

from scripts.smoke_conversation import build_parser, run_smoke


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _json_response(value):
    return _Response(json.dumps(value).encode())


def test_parser_accepts_required_task_and_question():
    args = build_parser().parse_args(
        ["--task-id", "task-1", "--question", "当前结论？"]
    )

    assert args.base_url == "http://127.0.0.1:6780"
    assert args.task_id == "task-1"


def test_smoke_runs_question_and_reports_stable_metrics():
    responses = iter(
        [
            _json_response({"task": {"id": "task-1"}}),
            _json_response({"id": "message-user"}),
            _Response(
                b"id: 1\nevent: answer.completed\n"
                b'data: {"message_id":"old","reply_to_id":"old-user"}\n\n'
                b"id: 2\nevent: answer.completed\n"
                b'data: {"message_id":"message-assistant",'
                b'"reply_to_id":"message-user"}\n\n'
            ),
            _json_response(
                {
                    "id": "message-assistant",
                    "content": "已有结论",
                    "status": "completed",
                    "citations": [{"id": "citation-1"}],
                }
            ),
        ]
    )
    requests = []

    def opener(request, timeout):
        requests.append((request.full_url, request.get_method(), timeout))
        return next(responses)

    metrics = run_smoke(
        base_url="http://127.0.0.1:6780",
        task_id="task-1",
        question="当前结论？",
        timeout=5,
        opener=opener,
    )

    assert metrics == {
        "task_id": "task-1",
        "message_status": "completed",
        "answer_chars": 4,
        "citation_count": 1,
        "continuation_status": None,
    }
    assert requests[1][1] == "POST"
    assert requests[2][0].endswith("/conversation/events")
    assert requests[3][0].endswith("/api/messages/message-assistant")
