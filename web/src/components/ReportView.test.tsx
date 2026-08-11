import { render, screen } from "@testing-library/react";
import { ReportView } from "./ReportView";

it("renders report markdown without interpreting raw HTML", () => {
  render(
    <ReportView markdown={'# 研判报告\n\n<script>alert("x")</script>\n\n[来源](https://example.com)'} />,
  );

  expect(screen.getByRole("heading", { name: "研判报告" })).toBeInTheDocument();
  expect(screen.getByText(/<script>/)).toBeInTheDocument();
  expect(screen.queryByRole("script")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "来源" })).toHaveAttribute(
    "rel",
    "noreferrer noopener",
  );
});
