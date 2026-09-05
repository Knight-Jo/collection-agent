import { expect, it } from "vitest";
import { api } from "./client";

it("lists seeded conversations", async () => {
  const items = await api.conversations();
  expect(items.length).toBe(3);
  expect(items.every((item) => item.title.length > 0)).toBe(true);
});

it("loads a conversation projection with messages and timeline", async () => {
  const view = await api.conversation("conv-1");
  expect(view?.conversation.title).toBe("先进封装产业竞争格局");
  expect(view?.messages.length).toBe(2);
  expect(view?.timeline.length).toBeGreaterThan(0);
  expect(view?.materials.length).toBeGreaterThan(0);
});

it("lists seeded monitors with change history", async () => {
  const monitors = await api.monitors();
  expect(monitors.length).toBe(2);

  const detail = await api.monitor("mon-1");
  expect(detail?.monitor.frequency).toBe("每天 09:00");
  expect(detail?.runs.length).toBeGreaterThan(0);
  expect(detail?.runs[0].changes.length).toBeGreaterThan(0);
});

it("lists seeded fact checks with verdict and evidence", async () => {
  const checks = await api.factChecks();
  expect(checks.length).toBe(1);

  const check = await api.factCheck("fc-1");
  expect(check?.verdict).toBe("mostly_supported");
  expect(check?.evidence_sufficiency).toBe("medium");
  expect(check?.evidence.length).toBeGreaterThan(0);
});

it("organizes the library across three dimensions", async () => {
  const library = await api.library();
  expect(library.research.length).toBeGreaterThan(0);
  expect(library.monitors.length).toBeGreaterThan(0);
  expect(library.factChecks.length).toBeGreaterThan(0);

  const record = library.research[0];
  expect(record.title.length).toBeGreaterThan(0);
  expect(Array.isArray(record.materials)).toBe(true);
  expect(Array.isArray(record.facts)).toBe(true);
  expect(Array.isArray(record.evidence)).toBe(true);
  expect(Array.isArray(record.sources)).toBe(true);
  expect(Array.isArray(record.questions)).toBe(true);
  expect(Array.isArray(record.timeline)).toBe(true);
});

it("includes the research report on completed tasks", async () => {
  const library = await api.library();
  const done = library.research.find((task) => task.title === "先进封装产业竞争格局");
  expect(done?.report?.status).toBe("published");
  expect(done?.report?.content).toContain("竞争格局");
});

it("lists and configures search sources with cookies", async () => {
  const sources = await api.searchSources();
  expect(sources.length).toBeGreaterThan(0);
  expect(sources.every((source) => "enabled" in source && "cookies" in source)).toBe(true);
});

it("lists AI search tools with api key env mapping", async () => {
  const tools = await api.aiSearchTools();
  expect(tools.map((tool) => tool.name)).toContain("Exa");
  expect(tools.every((tool) => tool.api_key_env.length > 0)).toBe(true);
});

it("lists media jobs with segments, facts and evidence", async () => {
  const jobs = await api.mediaJobs();
  expect(jobs.length).toBeGreaterThan(0);

  const job = await api.mediaJob("media-1");
  expect(job?.kind).toBe("video");
  expect(job?.segments.length).toBeGreaterThan(0);
  expect(job?.facts.length).toBeGreaterThan(0);
  expect(job?.evidence.length).toBeGreaterThan(0);
});
