import { afterEach, expect, it, vi } from "vitest";
import { api } from "./client";

type Call = { method: string; url: string; body: unknown };

function mockFetch(data: unknown): { calls: Call[] } {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ method: init?.method ?? "GET", url, body: init?.body });
    return {
      ok: true,
      status: 200,
      json: async () => data,
    } as Response;
  });
  return { calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

it("lists conversations via GET", async () => {
  const { calls } = mockFetch([
    { id: "c1", title: "t", status: "active", updated_at: "", run_status: null, run_phase: null },
  ]);
  const items = await api.conversations();
  expect(items).toHaveLength(1);
  expect(calls[0].url).toBe("/api/conversations?archived=false");
});

it("loads a conversation projection via GET", async () => {
  const projection = {
    conversation: { id: "c1", title: "t", status: "active", updated_at: "", run_status: null, run_phase: null },
    messages: [],
    run: null,
    materials: [],
    timeline: [],
    committed_state_version: 0,
    report_ready: false,
    brief: null,
    questions: [],
    gaps: [],
  };
  const { calls } = mockFetch(projection);
  const view = await api.conversation("c1");
  expect(view?.conversation.id).toBe("c1");
  expect(calls[0].url).toBe("/api/conversations/c1");
});

it("sends a message via POST with content body", async () => {
  const message = { id: "m1", role: "user", content: "hi", status: "completed", citations: [] };
  const { calls } = mockFetch(message);
  await api.sendMessage("c1", "hi");
  expect(calls[0].method).toBe("POST");
  expect(calls[0].url).toBe("/api/conversations/c1/messages");
  expect(JSON.parse(calls[0].body as string)).toEqual({ content: "hi" });
});

it("reads system status via GET", async () => {
  const status = {
    model: { name: "m", configured: true },
    search: { name: "arxiv", configured: true },
    processors: { tesseract: false, ffmpeg: true, whisper: true },
  };
  const { calls } = mockFetch(status);
  const result = await api.system();
  expect(result.processors.whisper).toBe(true);
  expect(calls[0].url).toBe("/api/system");
});

it("lists search sources via GET", async () => {
  const { calls } = mockFetch([{ id: "arxiv", name: "arxiv", url: "", enabled: true, cookie_configured: false }]);
  const sources = await api.searchSources();
  expect(sources[0].name).toBe("arxiv");
  expect(calls[0].url).toBe("/api/search-sources");
});

it("lists AI search tools via GET", async () => {
  const { calls } = mockFetch([{ id: "exa", name: "exa", description: "", enabled: false, api_key_configured: false, api_key_env: "EXA_API_KEY" }]);
  const tools = await api.aiSearchTools();
  expect(tools[0].api_key_env).toBe("EXA_API_KEY");
  expect(calls[0].url).toBe("/api/ai-search-tools");
});

it("maps monitors from the backend shape", async () => {
  const { calls } = mockFetch([
    {
      monitor_id: "m1",
      name: "n",
      subject: "s",
      strategy: "g",
      schedule: { cadence: "daily", local_time: "09:00", timezone: "UTC", weekday: null },
      status: "active",
      next_run_at: null,
      last_run_at: null,
      created_at: "",
      questions: [],
      websites: [],
    },
  ]);
  const monitors = await api.monitors();
  expect(monitors[0].id).toBe("m1");
  expect(monitors[0].frequency).toBe("每天 09:00");
  expect(calls[0].url).toBe("/api/monitors");
});

it("maps fact checks from the backend shape", async () => {
  mockFetch([
    {
      fact_check: {
        fact_check_id: "fc1",
        claim: "c",
        understanding: "",
        questions: [],
        checkability: "checkable",
        verdict: "supported",
        evidence_sufficiency: "high",
        independent_sources: 2,
        primary_sources: 1,
        counter_evidence: 0,
      },
      status: "completed",
      evidence: [],
    },
  ]);
  const checks = await api.factChecks();
  expect(checks[0].id).toBe("fc1");
  expect(checks[0].verdict).toBe("supported");
});

it("maps media jobs from the backend shape", async () => {
  mockFetch([
    {
      job: {
        media_job_id: "m1",
        filename: "f.mp3",
        kind: "audio",
        size_bytes: 100,
        summary: null,
      },
      status: "completed",
      segments: [],
      facts: [],
      evidence: [],
    },
  ]);
  const jobs = await api.mediaJobs();
  expect(jobs[0].id).toBe("m1");
  expect(jobs[0].filename).toBe("f.mp3");
});
