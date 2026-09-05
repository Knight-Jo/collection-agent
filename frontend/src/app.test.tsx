import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, createRouter, RouterProvider } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { routeTree } from "./routeTree.gen";

it("renders the dashboard and six-module sidebar", async () => {
  const queryClient = new QueryClient();
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/"] }),
    context: { queryClient },
  });
  await router.load();

  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  expect(await screen.findByText("情报态势")).toBeInTheDocument();
  expect(screen.getByText("深度调研")).toBeInTheDocument();
  expect(screen.getByText("持续监测")).toBeInTheDocument();
  expect(screen.getByText("事实核验")).toBeInTheDocument();
  expect(screen.getByText("情报资料库")).toBeInTheDocument();
  expect(screen.getByText("系统设置")).toBeInTheDocument();
});
