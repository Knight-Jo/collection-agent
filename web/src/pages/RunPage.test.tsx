import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../api";
import { RunPage } from "./RunPage";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("registers every crawl SSE event on the run stream", async () => {
  const registered: string[] = [];

  class EventSourceFake {
    onerror: (() => void) | null = null;

    constructor(_url: string) {}

    addEventListener(type: string, _listener: EventListener) {
      registered.push(type);
    }

    close() {}
  }

  vi.stubGlobal("EventSource", EventSourceFake);
  vi.spyOn(api, "run").mockResolvedValue({
    run_id: "run-1",
    status: "running",
    task_id: null,
    created_at: "2026-08-12T00:00:00Z",
    started_at: "2026-08-12T00:00:00Z",
    finished_at: null,
    result: null,
    error: null,
  });

  render(
    <MemoryRouter initialEntries={["/runs/run-1"]}>
      <Routes>
        <Route path="/runs/:runId" element={<RunPage />} />
      </Routes>
    </MemoryRouter>,
  );

  await waitFor(() => expect(api.run).toHaveBeenCalledWith("run-1"));
  expect(registered.filter((type) => type.startsWith("crawl."))).toEqual([
    "crawl.started",
    "crawl.progress",
    "crawl.resource",
    "crawl.completed",
  ]);
});
