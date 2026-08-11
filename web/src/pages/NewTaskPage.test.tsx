import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { NewTaskPage } from "./NewTaskPage";

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
