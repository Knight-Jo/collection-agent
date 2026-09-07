"""ConversationService: the frontend research-loop surface over the engine."""

from __future__ import annotations

import asyncio
import mimetypes
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from .contracts.documents import Citation
from .contracts.errors import DomainError
from .contracts.research import ResearchPlan, ResearchReport
from .runtime.config import AI_SEARCH_TOOL_NAMES
from .runtime.events import EventBus
from .storage._ids import new_id
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
        rebuild_providers=None,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator
        self.bus = event_bus
        self.roles = roles
        self.registry = registry
        self.settings = settings
        self.rebuild_providers = rebuild_providers
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
        brief = plan.brief() if plan else None
        result = self._result(conversation_id)
        coverage = result.get("coverage") if result else None
        questions = self._project_questions(coverage, plan)
        gaps = self._project_gaps(coverage)
        return {
            "conversation": self._conversation_view(conversation),
            "messages": messages,
            "run": run,
            "materials": materials,
            "timeline": timeline,
            "committed_state_version": 0,
            "report_ready": bool(result and result.get("report")),
            "brief": brief,
            "questions": questions,
            "gaps": gaps,
        }

    @staticmethod
    def _project_questions(coverage, plan) -> list[dict]:
        if coverage:
            return [
                {
                    "id": q.get("question_id", f"q{i}"),
                    "text": q.get("question", ""),
                    "status": q.get("status", "pending"),
                    "evidence_count": q.get("evidence_count", 0),
                    "coverage_note": q.get("coverage_note", ""),
                }
                for i, q in enumerate(coverage.get("questions", []))
            ]
        return [
            {
                "id": f"q{i}",
                "text": q,
                "status": "pending",
                "evidence_count": 0,
                "coverage_note": "",
            }
            for i, q in enumerate(plan.questions if plan else [])
        ]

    @staticmethod
    def _project_gaps(coverage) -> list[dict]:
        if not coverage:
            return []
        return [
            {
                "id": g.get("question_id", ""),
                "question_id": g.get("question_id", ""),
                "reason": g.get("reason", ""),
            }
            for g in coverage.get("gaps", [])
        ]

    def _result(self, conversation_id: str) -> dict | None:
        task_id = self.store.latest_task_id(conversation_id)
        if task_id is None:
            return None
        return self.store.get_research_result(task_id)

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
                    "download_url": f"/api/materials/{artifact_id}/download",
                }
            )
        return materials

    # --- material source files ---------------------------------------------

    def _resource_store(self):
        return self.orchestrator.acquisition_pipeline.resource_store

    def _material_filename(self, document, resource) -> str:
        title = document.title or (
            resource.origin.final_url or document.artifact_id
        )
        base = (
            "".join(c if c.isalnum() or c in "-_." else "_" for c in title)[
                :80
            ]
            or document.artifact_id
        )
        ext = mimetypes.guess_extension(resource.media_type) or ""
        return f"{base}{ext}"

    def material_resource(self, artifact_id: str) -> tuple[Path, str, str]:
        """Return (blob path, media type, filename) for a material's source."""
        document = self.store.get_document(artifact_id)
        resource = self.store.get_resource(document.resource_id)
        path = self._resource_store().blob_path(document.resource_id)
        filename = self._material_filename(document, resource)
        return path, resource.media_type, filename

    def materials_zip(self, conversation_id: str) -> Path:
        """Bundle every material source file of the latest task into a zip."""
        task_id = self.store.latest_task_id(conversation_id)
        if task_id is None:
            raise DomainError(
                "NOT_FOUND", f"no task for conversation: {conversation_id}"
            )
        out = self.settings.tmp_root() / f"materials-{conversation_id}.zip"
        out.parent.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for artifact_id in self.store.list_task_artifacts(task_id):
                try:
                    document = self.store.get_document(artifact_id)
                    resource = self.store.get_resource(document.resource_id)
                    path = self._resource_store().blob_path(
                        document.resource_id
                    )
                except DomainError:
                    continue
                if not path.exists():
                    continue
                filename = self._material_filename(document, resource)
                if filename in seen:
                    filename = f"{document.artifact_id}-{filename}"
                seen.add(filename)
                zf.write(path, filename)
        return out

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
        return self._launch(conversation_id, content)

    def _launch(self, conversation_id: str, content: str) -> dict:
        """Record a user message and start the research loop on it."""
        task = self.store.create_task(
            content, deadline_seconds=self.settings.research.deadline_seconds
        )
        user_message = self.store.add_message(
            conversation_id,
            "user",
            content,
            task_id=task.task_id,
        )
        self.store.set_conversation_title(conversation_id, content[:18])
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
            content = result.answer
            if result.status == "partial":
                content = (
                    "已达最大研究轮次，未形成最终报告。"
                    "以下是当前的覆盖与证据评估：\n\n" + content
                )
            self.store.add_message(
                conversation_id,
                "assistant",
                content,
                task_id=task.task_id,
                citations=citations,
            )
        except Exception as error:  # noqa: BLE001
            detail = str(error).strip() or type(error).__name__
            self.store.update_task_status(task.task_id, "failed")
            self.store.add_message(
                conversation_id,
                "assistant",
                f"调研未能完成：{detail[:500]}",
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
        for _attempt in range(2):
            result = await self.roles["brief"].run(prompt)
            brief = result.output.brief()
            if brief.get("goal") and brief.get("questions"):
                return brief
        raise DomainError(
            "INVALID_REQUEST",
            "简报生成失败：模型未返回有效内容，请重试",
        )

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
        self._launch(conversation["id"], topic)
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
        providers = self.settings.search.providers
        sources = []
        for name, p in providers.items():
            if name in AI_SEARCH_TOOL_NAMES:
                continue
            o = self._runtime(f"search_source:{name}")
            sources.append(
                {
                    "id": name,
                    "name": name,
                    "url": p.base_url or "",
                    "enabled": o.get("enabled", p.enabled),
                    "cookies": o.get("cookies", ""),
                }
            )
        for cid in self.store.get_runtime_state("custom_sources") or []:
            o = self._runtime(f"search_source:{cid}")
            if not o:
                continue
            sources.append(
                {
                    "id": cid,
                    "name": o.get("name", ""),
                    "url": o.get("url", ""),
                    "enabled": o.get("enabled", True),
                    "cookies": o.get("cookies", ""),
                }
            )
        return sources

    def ai_search_tools(self) -> list[dict]:
        tools = []
        for name in sorted(AI_SEARCH_TOOL_NAMES):
            tools.append(self._tool_view(name))
        return tools

    # --- search source / AI tool mutations ---------------------------------

    def _runtime(self, key: str) -> dict:
        value = self.store.get_runtime_state(key)
        return value if isinstance(value, dict) else {}

    def _reapply_providers(self) -> None:
        if self.rebuild_providers is None:
            return
        providers = self.rebuild_providers()
        self.orchestrator.search_service.replace_providers(providers)

    def _source_view(self, source_id: str) -> dict:
        provider = self.settings.search.providers.get(source_id)
        o = self._runtime(f"search_source:{source_id}")
        if provider is not None:
            return {
                "id": source_id,
                "name": source_id,
                "url": provider.base_url or "",
                "enabled": o.get("enabled", provider.enabled),
                "cookies": o.get("cookies", ""),
            }
        if o.get("custom"):
            return {
                "id": source_id,
                "name": o.get("name", ""),
                "url": o.get("url", ""),
                "enabled": o.get("enabled", True),
                "cookies": o.get("cookies", ""),
            }
        raise DomainError("NOT_FOUND", f"search source not found: {source_id}")

    def _tool_view(self, tool_id: str) -> dict:
        provider = self.settings.search.providers.get(tool_id)
        o = self._runtime(f"ai_tool:{tool_id}")
        return {
            "id": tool_id,
            "name": tool_id,
            "description": f"{tool_id} AI search provider",
            "enabled": o.get(
                "enabled", provider.enabled if provider else False
            ),
            "api_key": "configured" if self._tool_has_key(tool_id) else "",
            "api_key_env": (provider.api_key_env if provider else None)
            or f"{tool_id.upper()}_API_KEY",
        }

    def _tool_has_key(self, tool_id: str) -> bool:
        o = self._runtime(f"ai_tool:{tool_id}")
        if o.get("api_key"):
            return True
        provider = self.settings.search.providers.get(tool_id)
        if provider is not None and provider.api_key_env:
            import os

            return bool(os.environ.get(provider.api_key_env))
        return False

    def add_search_source(self, name: str, url: str) -> dict:
        cid = new_id("src")
        self.store.set_runtime_state(
            f"search_source:{cid}",
            {
                "name": name,
                "url": url,
                "enabled": True,
                "cookies": "",
                "custom": True,
            },
        )
        ids = list(self.store.get_runtime_state("custom_sources") or [])
        ids.append(cid)
        self.store.set_runtime_state("custom_sources", ids)
        return {
            "id": cid,
            "name": name,
            "url": url,
            "enabled": True,
            "cookies": "",
        }

    def toggle_search_source(self, source_id: str) -> dict:
        o = self._runtime(f"search_source:{source_id}")
        provider = self.settings.search.providers.get(source_id)
        o["enabled"] = not o.get(
            "enabled", provider.enabled if provider else True
        )
        self.store.set_runtime_state(f"search_source:{source_id}", o)
        self._reapply_providers()
        return self._source_view(source_id)

    def update_search_source(self, source_id: str, patch: dict) -> dict:
        o = self._runtime(f"search_source:{source_id}")
        for key in ("enabled", "cookies"):
            if key in patch:
                o[key] = patch[key]
        self.store.set_runtime_state(f"search_source:{source_id}", o)
        self._reapply_providers()
        return self._source_view(source_id)

    def toggle_ai_tool(self, tool_id: str) -> dict:
        o = self._runtime(f"ai_tool:{tool_id}")
        provider = self.settings.search.providers.get(tool_id)
        o["enabled"] = not o.get(
            "enabled", provider.enabled if provider else False
        )
        self.store.set_runtime_state(f"ai_tool:{tool_id}", o)
        self._reapply_providers()
        return self._tool_view(tool_id)

    def update_ai_tool_key(self, tool_id: str, api_key: str) -> dict:
        o = self._runtime(f"ai_tool:{tool_id}")
        o["api_key"] = api_key
        self.store.set_runtime_state(f"ai_tool:{tool_id}", o)
        self._reapply_providers()
        return self._tool_view(tool_id)

    def library_research(self) -> list[dict]:
        research = []
        for conv in self.list_conversations(archived=False):
            task_id = self.store.latest_task_id(conv["id"])
            result = self._result(conv["id"])
            projection = self.projection(conv["id"])
            research.append(
                {
                    "id": conv["id"],
                    "title": conv["title"],
                    "updated_at": conv["updated_at"],
                    "materials": projection["materials"],
                    "facts": self._facts_from_evidence(result),
                    "evidence": self._evidence_from_review(result),
                    "sources": self._sources_from(
                        projection["materials"], result
                    ),
                    "report": self._project_report(task_id, conv, result),
                    "brief": projection["brief"],
                    "questions": projection["questions"],
                    "timeline": projection["timeline"],
                }
            )
        return research

    @staticmethod
    def _project_report(task_id, conv, result) -> dict | None:
        if not result or not result.get("report") or task_id is None:
            return None
        report = ResearchReport.model_validate(result["report"])
        return {
            "id": task_id,
            "version": 1,
            "status": "published",
            "content": report.markdown(),
            "created_at": conv["updated_at"],
        }

    @staticmethod
    def _facts_from_evidence(result) -> list[dict]:
        evidence = result.get("evidence") if result else None
        if not evidence:
            return []
        facts: list[dict] = []
        seen: set[str] = set()

        def add(claim: str, status: str) -> None:
            claim = (claim or "").strip()
            if not claim or claim in seen:
                return
            seen.add(claim)
            facts.append(
                {
                    "id": f"f{len(facts)}",
                    "statement": claim,
                    "status": status,
                    "updated_at": "",
                }
            )

        for item in evidence.get("claims", []):
            add(
                item.get("claim"),
                "accepted"
                if item.get("relation") == "supports"
                else "disputed",
            )
        for conflict in evidence.get("conflicts", []):
            add(conflict.get("claim"), "disputed")
        return facts

    @staticmethod
    def _evidence_from_review(result) -> list[dict]:
        evidence = result.get("evidence") if result else None
        if not evidence:
            return []
        return [
            {
                "id": f"e{i}",
                "relation": item.get("relation", "supports"),
                "quote": item.get("quote", ""),
                "source_title": item.get("source_title", ""),
                "source_url": item.get("source_url", ""),
            }
            for i, item in enumerate(evidence.get("claims", []))
        ]

    @staticmethod
    def _sources_from(materials, result) -> list[dict]:
        evidence = result.get("evidence") if result else None
        seen: set[str] = set()
        sources: list[dict] = []
        for m in materials:
            url = m.get("url", "")
            if url and url not in seen:
                seen.add(url)
                sources.append(
                    {
                        "id": m["id"],
                        "name": m["title"],
                        "type": m["source_type"],
                        "url": url,
                    }
                )
        if evidence:
            for item in evidence.get("claims", []):
                url = item.get("source_url", "")
                if url and url not in seen:
                    seen.add(url)
                    sources.append(
                        {
                            "id": f"s{len(sources)}",
                            "name": item.get("source_title") or url,
                            "type": "证据来源",
                            "url": url,
                        }
                    )
        return sources
