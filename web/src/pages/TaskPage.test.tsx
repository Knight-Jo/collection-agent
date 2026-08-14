import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, vi } from "vitest";
import { api } from "../api";
import { TaskPage } from "./TaskPage";

afterEach(() => vi.restoreAllMocks());

it("renders crawl resource details and a task-owned download link", async () => {
  const user = userEvent.setup();
  vi.spyOn(api, "task").mockResolvedValue({
    task: {
      id: "task-1",
      topic: "深度抓取",
      stage: "collect",
      updated_at: "2026-08-11T09:00:00Z",
      criteria: { min_independent_sources: 2, min_high_quality_sources: 1, recency_days: 90, require_recency: false },
      outputs: { report: null, assessment: null, package: null },
    },
    coverage: null,
    questions: [],
    conflicts: [],
    challenges: [],
    material_digest: null,
    resources: [{
      canonical_url: "https://example.com/report.pdf",
      source_chain: ["https://example.com", "https://example.com/report.pdf"],
      depth: 1,
      status: "complete",
      mime_type: "application/pdf",
      size: 2048,
      downloaded_bytes: 1024,
      document_id: "document-1",
      extraction: { status: "complete", processor: "pdftotext", text_path: "texts/document-1.txt", error: null },
      error: null,
      rating: 4,
      description: "建议优先阅读",
    }],
  } as never);
  vi.spyOn(api, "artifact").mockRejectedValue(new Error("not ready"));

  render(
    <MemoryRouter initialEntries={["/tasks/task-1"]}>
      <Routes><Route path="/tasks/:taskId" element={<TaskPage />} /></Routes>
    </MemoryRouter>,
  );

  await screen.findByRole("heading", { name: "调研报告" });
  await user.click(screen.getByRole("button", { name: "来源与材料" }));
  expect(screen.getByRole("heading", { name: "抓取资源" })).toBeInTheDocument();
  expect(screen.getByText("https://example.com → https://example.com/report.pdf")).toBeInTheDocument();
  expect(screen.getByText("第 1 层 · application/pdf")).toBeInTheDocument();
  expect(screen.getByText("1 KB / 2 KB")).toBeInTheDocument();
  expect(screen.getByText("complete · complete")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "下载资源" })).toHaveAttribute(
    "href", "/api/tasks/task-1/resources/document-1/download",
  );
});

it("shows the report first and keeps source evidence available", async () => {
  vi.spyOn(api, "task").mockResolvedValue({
    task: { id: "task-1", topic: "深度抓取", stage: "done", updated_at: "2026-08-11T09:00:00Z", criteria: { min_independent_sources: 2, min_high_quality_sources: 1, recency_days: 90, require_recency: false }, outputs: { report: {}, assessment: null, package: null } },
    coverage: { level: "covered", gap_score: 0, stop_reason: null },
    questions: [{ id: "question-1", text: "证据是什么？", coverage: { status: "covered", notes: [] }, facts: [{ id: "fact-1", statement: "事实已验证", status: "active", coverage: { status: "covered", gap_score: 0, notes: [] }, evidence: [{ id: "evidence-1", relation: "supports", quote: "原文证据", line_start: 1, line_end: 2, notes: "", document: { title: "来源文档", final_url: "https://example.com/source", source_type: "official", source_group: "example.com", publish_time: null, injection_warnings: ["ignore instructions"] }, review: { verdict: "full", reason: "supported" } }] }] }],
    conflicts: [],
    challenges: [],
    material_digest: null,
    resources: [],
  } as never);
  const artifact = vi.spyOn(api, "artifact").mockResolvedValue({ kind: "report", path: "report.md", content: "# 调研结论", content_sha256: "hash" });
  const user = userEvent.setup();
  render(<MemoryRouter initialEntries={["/tasks/task-1"]}><Routes><Route path="/tasks/:taskId" element={<TaskPage />} /></Routes></MemoryRouter>);

  expect(await screen.findByRole("heading", { name: "调研报告" })).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "调研结论" })).toBeInTheDocument();
  expect(artifact).toHaveBeenCalledWith("task-1", "report");
  await user.click(screen.getByRole("button", { name: "来源与材料" }));
  expect(screen.getByText("原文证据")).toBeInTheDocument();
  expect(screen.getByText("文档含可疑指令，已按不可信内容处理")).toBeInTheDocument();
});
