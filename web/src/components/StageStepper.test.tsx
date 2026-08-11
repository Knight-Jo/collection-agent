import { render, screen } from "@testing-library/react";
import { StageStepper } from "./StageStepper";

it("marks completed, active, and future research stages", () => {
  render(<StageStepper stage="assess" />);

  expect(screen.getByText("资料收集").closest("li")).toHaveAttribute(
    "data-state",
    "complete",
  );
  expect(screen.getByText("综合研判").closest("li")).toHaveAttribute(
    "data-state",
    "active",
  );
  expect(screen.getByText("红队复审").closest("li")).toHaveAttribute(
    "data-state",
    "pending",
  );
});
