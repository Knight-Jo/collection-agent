"""ConversationService: the frontend research-loop surface over the engine."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from .contracts.documents import Citation
from .contracts.research import ResearchPlan
from .runtime.events import EventBus
from .storage.materials import MaterialStore

_RUN_STATUS = {
    "queued": "queued",
    "running": "running",
    "completed": "succeeded",
    "partial": "succeeded",
    "failed": "failed",
    "cancelled": "stopped",
    "interrupted": "stopped",
}


class ConversationService:
    """Exposes the research loop as conversations/messages/timeline."""

    def __init__(
        self,
        store: MaterialStore,
        orchestrator,
        event_bus: EventBus,
        roles,
        registry,
        settings,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.bus = event_bus
        self.roles = roles
        self.registry = registry
        self.settings = settings
        self._runs: set[asyncio.Task] = set()

    # --- conversations ------------------------------------------------------

    def create_conversation(self) -> dict:
        return self._conversation_view(self.store.create_conversation())

    def list_conversations(self, archived: bool = False) -> list[dict]:
        return [
            self._conversation_view(c)
            for c in self.store.list_conversations(archived)
        ]

    def archive(self, conversation_id: str) -> dict:
        return self._conversation_view(
            self.store.set_conversation_status(conversation_id, "archived")
        )

    def restore(self, conversation_id: str) -> dict:
        return self._conversation_view(
            self.store.set_conversation_status(conversation_id, "active")
        )

    def projection(self, conversation_id: str) -> dict:
        conversation = self.store.get_conversation(conversation_id)
        messages = self.store.list_messages(conversation_id)
        timeline = self.store.list_timeline(conversation_id)
        materials = self._materials(conversation_id)
        run = self._run(conversation_id)
        plan = self._load_plan(conversation_id)
        questions = plan.questions if plan else []
        brief = plan.brief() if plan else None
        return {
            "conversation": self._conversation_view(conversation),
            "messages": messages,
            "run": run,
            "materials": materials,
            "timeline": timeline,
            "committed_state_version": 0,
            "report_ready": bool(
                any(m["role"] == "assistant" for m in messages)
            ),
            "brief": brief,
            "questions": [
                {
                    "id": f"q{i}",
                    "text": q,
                    "status": "answered",
                    "evidence_count": 0,
                    "coverage_note": "",
                }
                for i, q in enumerate(questions)
            ],
            "gaps": [],
        }

    def _load_plan(self, conversation_id: str) -> ResearchPlan | None:
        conversation = self.store.get_conversation(conversation_id)
        brief = conversation.get("brief")
        if brief and isinstance(brief, dict):
            try:
                return ResearchPlan.model_validate(brief)
            except Exception:  # noqa: BLE001
                return None
        return None

    def _conversation_view(self, conversation: dict) -> dict:
        run = self._run(conversation["id"])
        return {
            "id": conversation["id"],
            "title": conversation["title"],
            "status": conversation["status"],
            "updated_at": conversation["updated_at"],
            "run_status": run["status"] if run else None,
            "run_phase": run["phase"] if run else None,
        }

    def _run(self, conversation_id: str) -> dict | None:
        task_id = self.store.latest_task_id(conversation_id)
        if task_id is None:
            return None
        try:
            task = self.store.get_task(task_id)
        except Exception:  # noqa: BLE001
            return None
        status = _RUN_STATUS.get(task.status, "queued")
        phase = (
            "collecting"
            if status == "running"
            else ("checkpointing" if status == "succeeded" else None)
        )
        return {"id": task_id, "status": status, "phase": phase}

    def _materials(self, conversation_id: str) -> list[dict]:
        task_id = self.store.latest_task_id(conversation_id)
        if task_id is None:
            return []
        materials = []
        for artifact_id in self.store.list_task_artifacts(task_id):
            try:
                document = self.store.get_document(artifact_id)
            except Exception:  # noqa: BLE001
                continue
            url = next(
                (
                    o.original_url
                    for o in document.provenance
                    if o.original_url
                ),
                "",
            )
            materials.append(
                {
                    "id": artifact_id,
                    "title": document.title or url or artifact_id,
                    "url": url,
                    "source_type": (
                        document.provenance[0].channel
                        if document.provenance
                        else "web"
                    ),
                    "rating": 0,
                    "description": "",
                }
            )
        return materials

    # --- messages -----------------------------------------------------------

    def _make_sink(
        self, conversation_id: str, task_id: str
    ) -> Callable[[dict], Awaitable[None]]:
        async def sink(event: dict) -> None:
            etype = event["event"]
            if etype == "timeline":
                entry = self.store.add_timeline(
                    conversation_id,
                    event["kind"],
                    event["label"],
                    detail=event.get("detail"),
                    task_id=task_id,
                )
                self.bus.publish(
                    conversation_id, {"type": "timeline", "entry": entry}
                )
            elif etype == "material":
                self.bus.publish(
                    conversation_id,
                    {
                        "type": "material",
                        "material": {
                            "id": event.get("url", ""),
                            "title": event.get("title", ""),
                            "url": event.get("url", ""),
                            "source_type": event.get("source_type", "web"),
                            "rating": 0,
                            "description": "",
                        },
                    },
                )
            elif etype == "run.status":
                self.bus.publish(
                    conversation_id,
                    {
                        "type": "run.status",
                        "status": event["status"],
                    },
                )
            elif etype == "run.phase":
                self.bus.publish(
                    conversation_id,
                    {
                        "type": "run.phase",
                        "phase": event["phase"],
                    },
                )
            elif etype == "answer.started":
                self.bus.publish(conversation_id, {"type": "answer.started"})
            elif etype == "answer.delta":
                self.bus.publish(
                    conversation_id,
                    {
                        "type": "answer.delta",
                        "delta": event["delta"],
                    },
                )
            elif etype == "answer.completed":
                self.bus.publish(conversation_id, {"type": "answer.completed"})

        return sink

    async def send_message(self, conversation_id: str, content: str) -> dict:
        content = content.strip()
        if not content:
            raise ValueError("empty message")
        user_message = self.store.add_message(conversation_id, "user", content)
        self.store.set_conversation_title(conversation_id, content[:18])
        task = self.store.create_task(
            content, deadline_seconds=self.settings.research.deadline_seconds
        )
        plan = self._load_plan(conversation_id)
        sink = self._make_sink(conversation_id, task.task_id)
        run = asyncio.create_task(
            self._run_and_reply(conversation_id, task, sink, plan)
        )
        self._runs.add(run)
        run.add_done_callback(self._runs.discard)
        return user_message

    async def _run_and_reply(
        self, conversation_id: str, task, sink, plan
    ) -> None:
        try:
            result = await self.orchestrator.run_task(
                task, event_sink=sink, plan=plan
            )
            citations = self._map_citations(result.citations)
            self.store.add_message(
                conversation_id,
                "assistant",
                result.answer,
                task_id=task.task_id,
                citations=citations,
            )
        except Exception:  # noqa: BLE001
            self.store.add_message(
                conversation_id,
                "assistant",
                "",
                task_id=task.task_id,
                citations=[],
                status="failed",
            )
        finally:
            self.bus.publish(conversation_id, {"type": "refetch"})

    async def close(self) -> None:
        for run in list(self._runs):
            run.cancel()
        if self._runs:
            await asyncio.gather(*self._runs, return_exceptions=True)
        self._runs.clear()

    @staticmethod
    def _map_citations(citations: list[Citation]) -> list[dict]:
        return [
            {
                "id": c.citation_id,
                "sequence": i + 1,
                "title": c.source_url or c.document_id,
                "source_url": c.source_url or "",
                "quote_text": "",
            }
            for i, c in enumerate(citations)
        ]

    # --- brief / system / sources ------------------------------------------

    async def generate_brief(self, prompt: str) -> dict:
        plan = await self._plan(prompt)
        return plan.brief()

    async def _plan(self, prompt: str) -> ResearchPlan:
        result = await self.roles["planner"].run(prompt)
        return result.output

    async def start_research(self, topic: str, brief: dict) -> dict:
        prompt = f"调研主题: {topic}\n\n调研简报:\n" + "\n".join(
            f"- {q}" for q in (brief or {}).get("questions", [])
        )
        plan = await self._plan(prompt)
        conversation = self.store.create_conversation(topic)
        self.store.save_brief(conversation["id"], plan.model_dump(mode="json"))
        self.store.set_conversation_status(conversation["id"], "active")
        return self._conversation_view(
            self.store.get_conversation(conversation["id"])
        )

    def system_status(self) -> dict:
        cfg = self.settings
        model_configured = bool(cfg.model.model_id)
        search = cfg.search.providers
        search_name = (
            next((n for n, p in search.items() if p.enabled), None) or "none"
        )
        return {
            "model": {
                "name": cfg.model.model_id,
                "configured": model_configured,
            },
            "search": {
                "name": search_name,
                "configured": bool(search_name != "none"),
            },
            "processors": {
                "tesseract": self.registry.available("tesseract"),
                "ffmpeg": self.registry.available("ffmpeg"),
                "whisper": self.registry.available("whisper"),
            },
        }

    def search_sources(self) -> list[dict]:
        return [
            {
                "id": name,
                "name": name,
                "url": (p.base_url or ""),
                "enabled": p.enabled,
                "cookies": "",
            }
            for name, p in self.settings.search.providers.items()
        ]

    def ai_search_tools(self) -> list[dict]:
        tools = []
        for name in ("exa", "brave", "tavily"):
            tools.append(
                {
                    "id": name,
                    "name": name,
                    "description": f"{name} AI search provider",
                    "enabled": False,
                    "api_key": "",
                    "api_key_env": f"{name.upper()}_API_KEY",
                }
            )
        return tools

    def library(self) -> dict:
        research = []
        for conv in self.list_conversations(archived=False):
            projection = self.projection(conv["id"])
            research.append(
                {
                    "id": conv["id"],
                    "title": conv["title"],
                    "updated_at": conv["updated_at"],
                    "materials": projection["materials"],
                    "facts": [],
                    "evidence": [],
                    "sources": [],
                    "report": None,
                    "brief": projection["brief"],
                    "questions": projection["questions"],
                    "timeline": projection["timeline"],
                }
            )
        return {"research": research, "monitors": [], "factChecks": []}
