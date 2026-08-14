# Research Report First Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a topic-only research run produce a report-first deliverable with task-specific 1–5 star material recommendations and a collection digest.

**Architecture:** Reuse the current task, document, evidence, audit, crawl, and atomic JSON layers. Add optional research brief fields to the task input, claim-aware coverage rules, a task-scoped material registry/digest, and a deterministic report renderer whose citations come only from verified evidence. Keep the legacy assessment/package paths readable while making `report` the primary artifact.

**Tech Stack:** Python 3.12, Pydantic, pydantic-ai, FastAPI, pytest, React 19, TypeScript, Vite, Bun.

## Global Constraints

- Use existing storage, security, extraction, and citation helpers; add no dependency.
- Preserve old task/document JSON compatibility through defaulted optional fields.
- Write tests before production changes and observe each focused test fail for the intended missing behavior.
- Keep `deep_crawl` as a compatibility override; default it to disabled.
- A recommendation is one task-specific integer from 1 to 5; do not add a second quality or trust label.
- Material descriptions are at most 120 Chinese characters.
- Comments and public API docstrings are in English.

---

### Task 1: Topic-only research input

**Files:**
- Modify: `src/intel_agent/models.py`
- Modify: `src/intel_agent/runner.py`
- Modify: `src/intel_agent/main.py`
- Modify: `src/intel_agent/web/schemas.py`
- Modify: `tests/test_runner.py`
- Modify: `tests/test_main.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Produces: `ResearchScope`, `ReportDepth`, and expanded `TaskRunSpec(topic, objective, questions, scope, report_depth, ...)`.
- Preserves: `questions` received by `intel_plan` must still contain 2–6 final questions; only the external run request may omit them.

- [ ] **Step 1: Write failing input tests**

```python
def test_task_run_spec_accepts_topic_without_questions():
    spec = TaskRunSpec(topic="低空经济")
    assert spec.questions == []
    assert spec.objective == ""
    assert spec.report_depth == "standard"


def test_topic_only_prompt_asks_agent_to_generate_questions():
    prompt = build_task_prompt(TaskRunSpec(topic="低空经济"))
    assert "生成 3–6 个" in prompt
    assert "低空经济" in prompt
```

Add API and CLI tests proving `POST /api/runs` accepts `{ "topic": "测试主题" }` and `--questions` is optional.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_runner.py tests/test_main.py tests/test_web_api.py -q
```

Expected: failures because criteria/questions are required and the new fields do not exist.

- [ ] **Step 3: Implement the minimal input models**

Add:

```python
ReportDepth = Literal["brief", "standard", "deep"]


class ResearchScope(BaseModel):
    time_range: str = ""
    geography: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
```

Give `TaskRunSpec.questions` an empty-list default, `criteria` the current default factory, and normalize zero to six user questions. Add `objective`, `scope`, and `report_depth`. When no questions exist, make `build_task_prompt` require the Agent to generate 3–6 questions; when one or more exist, require them to be preserved and supplemented to a final total of 2–6.

Make CLI `--questions` optional and add `--objective`, `--time-range`, `--geography`, `--language`, and `--report-depth`. Mirror the fields in `RunCreate`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/intel_agent/models.py src/intel_agent/runner.py src/intel_agent/main.py src/intel_agent/web/schemas.py tests/test_runner.py tests/test_main.py tests/test_web_api.py
git commit -m "feat(research): accept topic-only tasks"
```

### Task 2: Claim-aware coverage

**Files:**
- Modify: `src/intel_agent/models.py`
- Modify: `src/intel_agent/fact.py`
- Modify: `src/intel_agent/coverage.py`
- Modify: `src/intel_agent/agent.py`
- Modify: `tests/test_fact.py`
- Modify: `tests/test_coverage.py`

**Interfaces:**
- Produces: `ClaimType = Literal["primary", "corroborated", "reported"]` and `Fact.claim_type` defaulting to `corroborated` for historical JSON.
- Changes: `save_fact(..., claim_type: ClaimType = "corroborated") -> Fact`.
- Produces: `QuestionCoverage.answer_status` with `answered`, `partial`, `unanswered`, or `conflicted`, while retaining legacy `status`.

- [ ] **Step 1: Write failing fact and coverage tests**

```python
def test_primary_claim_is_covered_by_one_verified_source(cwd):
    task = new_task(cwd)
    document = make_document(
        cwd, "政府发布测试主题政策", "https://gov.cn/policy"
    )
    fact = save_fact(
        cwd, task.id, task.questions[0].id, "政府发布测试主题政策", "primary"
    )
    save_evidence(cwd, fact.id, document, "supports", "政府发布测试主题政策")
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    coverage = eval_coverage(cwd, task.id)
    assert coverage.per_question[0].facts[0].status == "covered"


def test_corroborated_claim_still_requires_two_sources(cwd):
    task = new_task(cwd)
    document = make_document(
        cwd, "媒体报道测试主题进展", "https://news.cn/story"
    )
    fact = save_fact(
        cwd, task.id, task.questions[0].id, "测试主题取得进展", "corroborated"
    )
    save_evidence(cwd, fact.id, document, "supports", "媒体报道测试主题进展")
    asyncio.run(audit_task_evidence(cwd, task.id, fake_judge, "test", "fake"))
    assert (
        eval_coverage(cwd, task.id).per_question[0].facts[0].status
        == "partial"
    )
```

Add a historical JSON test that omits `claim_type` and validates it as `corroborated`. Add an answer-status test for answered, partial, unanswered, and conflicted mappings.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_fact.py tests/test_coverage.py -q
```

Expected: failures because facts have no claim type and all facts use the same source thresholds.

- [ ] **Step 3: Implement claim-aware thresholds**

For `primary` and `reported`, require one verified support and no global high-quality minimum. For `corroborated`, keep the task criteria. Recency and unresolved contradiction rules remain unchanged for every claim type.

Set `QuestionCoverage.answer_status` as follows:

```python
if unresolved_conflict:
    answer_status = "conflicted"
elif status == "covered":
    answer_status = "answered"
elif status == "gap":
    answer_status = "unanswered"
else:
    answer_status = "partial"
```

Expose `claim_type` on the `fact_save` Agent tool.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/intel_agent/models.py src/intel_agent/fact.py src/intel_agent/coverage.py src/intel_agent/agent.py tests/test_fact.py tests/test_coverage.py
git commit -m "feat(research): evaluate claims by source needs"
```

### Task 3: Task-scoped material recommendations and digest

**Files:**
- Create: `src/intel_agent/materials.py`
- Create: `tests/test_materials.py`
- Modify: `src/intel_agent/models.py`
- Modify: `src/intel_agent/agent.py`
- Modify: `src/intel_agent/storage.py`

**Interfaces:**
- Produces: `register_material(cwd, task_id, canonical_url, document_id=None, error=None) -> MaterialRecord`.
- Produces: `generate_material_digest(cwd, task_id) -> MaterialDigest`.
- Produces: `load_material_digest(cwd, task_id) -> MaterialDigest | None`.
- Stores: `data/intel/materials/{task_id}.json`.

- [ ] **Step 1: Write failing material tests**

Use real task, document, fact, evidence, and crawl fixtures. Tests must prove:

```python
def test_verified_core_material_receives_five_stars(cwd):
    digest = generate_material_digest(cwd, task.id)
    review = next(
        item for item in digest.materials if item.document_id == document.id
    )
    assert review.rating == 5
    assert len(review.description) <= 120
    assert review.question_ids == [question.id]


def test_failed_material_receives_one_star(cwd):
    record = register_material(
        cwd, task.id, "https://example.com/fail", error="提取失败"
    )
    digest = generate_material_digest(cwd, task.id)
    review = next(
        item
        for item in digest.materials
        if item.canonical_url == record.canonical_url
    )
    assert review.rating == 1
    assert "提取失败" in review.description
```

Also prove that the same `document_id` in two tasks is persisted under separate task snapshots and that the digest recommends only 4–5 star current-task materials.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_materials.py -q
```

Expected: import failure because `intel_agent.materials` does not exist.

- [ ] **Step 3: Implement the registry and deterministic rating**

Use only existing task/doc/evidence metadata. Rating rules, applied in order:

```text
1 star: no readable archived document or explicit collection/extraction error
5 stars: document supports at least one full-reviewed active fact
4 stars: document has task evidence but no full-reviewed active support
3 stars: readable document matches a task question in title/body
2 stars: readable task material without a question match
```

Generate descriptions from title, matched question, evidence use, and error state. Clamp to 120 characters. Build digest overview from counts/types/date range, key points from active fact statements, priority reading from 4–5 star reviews, reading guides from `question_ids`, and gaps from question coverage notes.

Register successful direct `web_fetch` results in `_web_fetch`. After `crawl_collect`, synchronize every crawl entry, including failed entries, into the material registry before generating the digest. Add an Agent tool `material_digest(task_id)` that generates and returns the persisted digest.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2. Expected: all material tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/intel_agent/materials.py src/intel_agent/models.py src/intel_agent/agent.py src/intel_agent/storage.py tests/test_materials.py
git commit -m "feat(research): rank collected materials"
```

### Task 4: Citation-safe research report artifact

**Files:**
- Create: `src/intel_agent/report.py`
- Create: `tests/test_report.py`
- Modify: `src/intel_agent/models.py`
- Modify: `src/intel_agent/task.py`
- Modify: `src/intel_agent/agent.py`
- Modify: `src/intel_agent/web/schemas.py`
- Modify: `src/intel_agent/web/views.py`
- Modify: `tests/test_task.py`
- Modify: `tests/test_web_views.py`

**Interfaces:**
- Produces: `ResearchReportSection(question_id, conclusions)` and `ResearchReportInput(sections, overall_conclusions)`; the system derives the executive summary, source attribution, reasoning basis, and limitations from verified facts and coverage state.
- Produces: `generate_research_report(cwd, task_id, draft) -> dict`.
- Adds: `TaskOutputs.report: TaskOutputBinding | None`.
- Adds artifact kind: `report`, with `assessment` falling back to the report during compatibility.

- [ ] **Step 1: Write failing report tests**

```python
def test_report_has_question_sections_citations_digest_and_no_internal_ids(
    cwd,
):
    result = generate_research_report(cwd, task.id, draft)
    content = Path(result["path"]).read_text(encoding="utf-8")
    assert "## 执行摘要" in content
    assert "## 材料导读" in content
    assert "[1]" in content
    assert document.final_url in content
    assert "fact-" not in content
    assert "doc-" not in content


def test_report_rejects_cross_task_or_unverified_fact(cwd):
    result = generate_research_report(cwd, task.id, invalid_draft)
    assert result["ok"] is False
    assert result["errors"][0]["code"] == "INSUFFICIENT_EVIDENCE"
```

Add lifecycle tests proving a current report can complete from `assess` without a mandatory challenge/package and that a report bound to stale coverage is rejected. Preserve a test proving historical assessment/package outputs still validate.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_report.py tests/test_task.py tests/test_web_views.py -q
```

Expected: report module and output binding are missing.

- [ ] **Step 3: Implement deterministic report rendering**

Reuse the conclusion validation rules from `assess.py`, but render citations from verified evidence as numbered Markdown references. Do not print internal IDs. Render task scope, executive summary, question sections, disagreements, limitations, overall conclusions, material digest, and a deduplicated source directory.

Generate the digest automatically if it is missing. Refuse `NO_REPORTABLE_FINDINGS` when no supplied conclusion resolves to a verified support. Bind `output/{slug}-research-report.md` as `report` against the latest coverage.

Allow `assess → done`. Completion requires a current, untampered `report`; for old tasks without `report`, accept the existing current `assessment` and `package` pair. Set completion to `sufficient` only when coverage is sufficient, otherwise `with_gaps`.

Add `report` to artifact schemas/views. When callers request legacy `assessment` and only `report` exists, return the report content with kind `assessment`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/intel_agent/report.py src/intel_agent/models.py src/intel_agent/task.py src/intel_agent/agent.py src/intel_agent/web/schemas.py src/intel_agent/web/views.py tests/test_report.py tests/test_task.py tests/test_web_views.py
git commit -m "feat(research): generate citation-safe reports"
```

### Task 5: Generic report-first Agent workflow

**Files:**
- Modify: `src/intel_agent/agent.py`
- Modify: `src/intel_agent/runner.py`
- Modify: `src/intel_agent/config.py`
- Modify: `config.example.yaml`
- Modify: `tests/test_runner.py`
- Modify: `tests/test_workflow.py`

**Interfaces:**
- Adds Agent tool: `generate_research_report` using the Task 4 input model.
- Keeps legacy `intel_assess`, `generate_package`, and challenge tools callable for historical/debug workflows.

- [ ] **Step 1: Write failing workflow tests**

Add tests that inspect the built prompt through behavior and prove:

- no questions means the Agent must generate 3–6 questions;
- the prompt contains no low-altitude-economy, EHang, or hard-coded finance-site guidance;
- the primary workflow ends with material digest plus research report;
- challenge and package are optional, not mandatory;
- default settings resolve `deep_crawl` to false.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest tests/test_runner.py tests/test_workflow.py -q
```

Expected: failures against the old domain-specific prompt and true crawl default.

- [ ] **Step 3: Replace the workflow instructions minimally**

Keep security, exact-quote, audit, conflict, budget, and injection rules. Replace the long domain-specific workflow with plan → targeted search/fetch → claim/evidence → audit/coverage → material digest → report → done. Tell the Agent to use `primary`, `reported`, and `corroborated` claim types correctly and to disclose gaps instead of chasing uniform double-source coverage.

Change both `CrawlConfig.enabled_by_default` and `config.example.yaml` to false. Enable recursive crawling only for explicit `deep_crawl=true` or `report_depth=deep` in `run_agent_task`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2. Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/intel_agent/agent.py src/intel_agent/runner.py src/intel_agent/config.py config.example.yaml tests/test_runner.py tests/test_workflow.py
git commit -m "feat(research): make agent workflow report-first"
```

### Task 6: Report-first workbench and material guide

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/pages/NewTaskPage.tsx`
- Modify: `web/src/pages/NewTaskPage.test.tsx`
- Modify: `web/src/pages/TaskPage.tsx`
- Modify: `web/src/pages/TaskPage.test.tsx`
- Modify: `web/src/components/ResourceList.tsx`
- Create: `web/src/components/ResourceList.test.tsx`
- Modify: `web/src/styles.css`

**Interfaces:**
- `RunInput.questions` becomes optional/empty-list compatible and adds objective/scope/report depth.
- `CrawlResource` adds `rating` and `description`.
- `TaskDetail` adds `material_digest` and `outputs.report`.

- [ ] **Step 1: Write failing UI tests**

Add tests proving:

```typescript
it("submits a topic without questions", async () => {
  await user.type(screen.getByLabelText("研究主题"), "低空经济");
  await user.click(screen.getByRole("button", { name: /开始研究/ }));
  expect(createRun).toHaveBeenCalledWith(expect.objectContaining({ topic: "低空经济", questions: [] }));
});

it("shows the report first and sorts materials by stars", async () => {
  expect(await screen.findByRole("heading", { name: "调研报告" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "来源与材料" }));
  expect(screen.getAllByLabelText("阅读推荐")[0]).toHaveTextContent("★★★★★");
});
```

- [ ] **Step 2: Run frontend tests and verify RED**

```bash
cd web && bun run test
```

Expected: topic-only form is rejected, evidence is the default tab, and resource ratings are absent.

- [ ] **Step 3: Implement the minimal UI**

Start the question list empty and provide an “添加关键问题” control. Add optional objective and a collapsed advanced section for scope/report depth/deep crawl. Default the task page to `report`, load artifact kind `report`, and label the secondary tab “来源与材料”.

Render digest overview, key points, and priority-reading list above resources. Sort a copied resource array by descending rating so props remain immutable. Render stars with `aria-label="阅读推荐"` and the single description; do not render any parallel quality badge.

- [ ] **Step 4: Run frontend tests and verify GREEN**

```bash
cd web && bun run test
```

Expected: all frontend tests pass.

- [ ] **Step 5: Commit**

```bash
git add web/src/types.ts web/src/pages/NewTaskPage.tsx web/src/pages/NewTaskPage.test.tsx web/src/pages/TaskPage.tsx web/src/pages/TaskPage.test.tsx web/src/components/ResourceList.tsx web/src/components/ResourceList.test.tsx web/src/styles.css
git commit -m "feat(web): present reports and ranked materials first"
```

### Task 7: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-14-research-report-first-design.md` only if implementation names differ from the approved design.

**Interfaces:**
- Documents the topic-only request, report artifact, star semantics, and default targeted collection behavior.

- [ ] **Step 1: Update public documentation**

Document a topic-only CLI/API example, optional scope/questions, the `research-report.md` output, material digest, 1–5 star rubric, and explicit `--deep-crawl` override. Remove claims that recursive crawl is the default product path.

- [ ] **Step 2: Run Python quality gates**

```bash
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff format --check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run ruff check .
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pyright
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv run pytest
UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX uv build
```

Expected: zero errors and all tests pass.

- [ ] **Step 3: Run frontend quality gates**

```bash
cd web
bun install --frozen-lockfile
bun run test
bun run typecheck
bun run build
```

Expected: zero errors and successful production build.

- [ ] **Step 4: Verify repository state and commit docs**

```bash
git diff --check
git status --short
git add README.md docs/superpowers/specs/2026-08-14-research-report-first-design.md
git commit -m "docs: explain report-first research workflow"
```

Do not create an empty commit if the design document did not need changes.
