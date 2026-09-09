import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createElement, type ReactNode } from "react";
import { useMediaStream } from "./use-media-stream";

const invalidateSpy = vi.spyOn(QueryClient.prototype, "invalidateQueries");

function wrapper({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: new QueryClient() }, children);
}

beforeEach(() => {
  vi.useFakeTimers();
  invalidateSpy.mockClear().mockResolvedValue(undefined as never);
});

afterEach(() => {
  vi.useRealTimers();
});

function advance(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

it("polls every 3s while the job is live and stops when disabled", () => {
  const { rerender } = renderHook(
    ({ enabled }: { enabled: boolean }) => useMediaStream("media-1", enabled),
    { wrapper, initialProps: { enabled: true } },
  );

  const mediaCalls = () =>
    invalidateSpy.mock.calls.filter(([opts]) => JSON.stringify(opts).includes("media-1")).length;

  advance(3000);
  advance(3000);
  expect(mediaCalls()).toBeGreaterThanOrEqual(2);

  invalidateSpy.mockClear();
  rerender({ enabled: false });
  advance(30000);
  expect(mediaCalls()).toBe(0);
});

it("never polls without a job id", () => {
  renderHook(() => useMediaStream(undefined, true), { wrapper });
  advance(10000);
  expect(invalidateSpy).not.toHaveBeenCalled();
});
