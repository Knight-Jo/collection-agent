import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, vi } from "vitest";
import { api } from "../api";
import { NewTaskPage } from "./NewTaskPage";

afterEach(() => vi.restoreAllMocks());

it("requires a topic and at least two questions before creating a run", async () => {
  const user = userEvent.setup();
  const createRun = vi.fn();
  render(
    <MemoryRouter>
      <NewTaskPage createRun={createRun} />
    </MemoryRouter>,
  );

  await user.click(screen.getByRole("button", { name: "开始研究" }));
  expect(screen.getByText("请输入研究主题")).toBeInTheDocument();

  await user.type(screen.getByLabelText("研究主题"), "低空经济投资进展");
  await user.type(screen.getByLabelText("关键问题 1"), "重大投资事件有哪些？");
  await user.type(screen.getByLabelText("关键问题 2"), "产业基金规模如何？");
  await user.click(screen.getByRole("button", { name: "开始研究" }));

  expect(createRun).toHaveBeenCalledWith(
    expect.objectContaining({
      topic: "低空经济投资进展",
      questions: ["重大投资事件有哪些？", "产业基金规模如何？"],
    }),
  );
});

it("adds and removes optional questions", async () => {
  const user = userEvent.setup();
  render(
    <MemoryRouter>
      <NewTaskPage createRun={vi.fn()} />
    </MemoryRouter>,
  );

  await user.click(screen.getByRole("button", { name: "添加问题" }));
  expect(screen.getByLabelText("关键问题 3")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "删除问题 3" }));
  expect(screen.queryByLabelText("关键问题 3")).not.toBeInTheDocument();
});

it("uses the system crawl default and submits the chosen crawl setting", async () => {
  vi.spyOn(api, "system").mockResolvedValue({
    model: { name: "model", configured: true },
    audit: { name: "audit", configured: true },
    search: { name: "search", configured: true },
    crawl: { default_enabled: true },
    processors: { tesseract: true, ffmpeg: true, whisper: true, libreoffice: true },
  });
  const user = userEvent.setup();
  const createRun = vi.fn();
  render(
    <MemoryRouter>
      <NewTaskPage createRun={createRun} />
    </MemoryRouter>,
  );

  const toggle = await screen.findByRole("checkbox", { name: "启用深度抓取" });
  expect(toggle).toBeChecked();
  await user.type(screen.getByLabelText("研究主题"), "低空经济投资进展");
  await user.type(screen.getByLabelText("关键问题 1"), "重大投资事件有哪些？");
  await user.type(screen.getByLabelText("关键问题 2"), "产业基金规模如何？");
  await user.click(screen.getByRole("button", { name: "开始研究" }));

  expect(createRun).toHaveBeenCalledWith(
    expect.objectContaining({ deep_crawl: true }),
  );
});

it("keeps the form usable with deep crawl off when the system request fails", async () => {
  vi.spyOn(api, "system").mockRejectedValue(new Error("offline"));
  const user = userEvent.setup();
  const createRun = vi.fn();
  render(
    <MemoryRouter>
      <NewTaskPage createRun={createRun} />
    </MemoryRouter>,
  );

  expect(await screen.findByRole("checkbox", { name: "启用深度抓取" })).not.toBeChecked();
  await user.type(screen.getByLabelText("研究主题"), "低空经济投资进展");
  await user.type(screen.getByLabelText("关键问题 1"), "重大投资事件有哪些？");
  await user.type(screen.getByLabelText("关键问题 2"), "产业基金规模如何？");
  await user.click(screen.getByRole("button", { name: "开始研究" }));

  expect(createRun).toHaveBeenCalledWith(
    expect.objectContaining({ deep_crawl: false }),
  );
});

it("waits for an unresolved system default before creating a run", async () => {
  let resolveSystem!: (value: Awaited<ReturnType<typeof api.system>>) => void;
  vi.spyOn(api, "system").mockReturnValue(new Promise((resolve) => { resolveSystem = resolve; }));
  const user = userEvent.setup();
  const createRun = vi.fn();
  render(<MemoryRouter><NewTaskPage createRun={createRun} /></MemoryRouter>);

  await user.type(screen.getByLabelText("研究主题"), "低空经济投资进展");
  await user.type(screen.getByLabelText("关键问题 1"), "重大投资事件有哪些？");
  await user.type(screen.getByLabelText("关键问题 2"), "产业基金规模如何？");
  expect(screen.getByRole("button", { name: "开始研究" })).toBeDisabled();
  expect(createRun).not.toHaveBeenCalled();

  resolveSystem({ model: { name: "model", configured: true }, audit: { name: "audit", configured: true }, search: { name: "search", configured: true }, crawl: { default_enabled: true }, processors: { tesseract: true, ffmpeg: true, whisper: true, libreoffice: true } });
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "启用深度抓取" })).toBeChecked());
  await user.click(screen.getByRole("button", { name: "开始研究" }));
  expect(createRun).toHaveBeenCalledWith(expect.objectContaining({ deep_crawl: true }));
});

it("preserves a user crawl choice made before the system default resolves", async () => {
  let resolveSystem!: (value: Awaited<ReturnType<typeof api.system>>) => void;
  vi.spyOn(api, "system").mockReturnValue(new Promise((resolve) => { resolveSystem = resolve; }));
  const user = userEvent.setup();
  render(<MemoryRouter><NewTaskPage createRun={vi.fn()} /></MemoryRouter>);

  await user.click(screen.getByRole("checkbox", { name: "启用深度抓取" }));
  resolveSystem({ model: { name: "model", configured: true }, audit: { name: "audit", configured: true }, search: { name: "search", configured: true }, crawl: { default_enabled: false }, processors: { tesseract: true, ffmpeg: true, whisper: true, libreoffice: true } });
  await waitFor(() => expect(screen.getByRole("checkbox", { name: "启用深度抓取" })).toBeChecked());
});
