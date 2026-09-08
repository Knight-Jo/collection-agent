import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { Report } from "@/api/types";
import { ReportView } from "./report-view";

const report: Report = {
  id: "task-1",
  version: 1,
  status: "published",
  content: "# 报告\n\n正文内容",
  created_at: "2026-01-01T00:00:00Z",
};

it("offers three format links when a conversation is provided", async () => {
  render(<ReportView report={report} conversationId="conv-9" />);
  await userEvent.click(screen.getByRole("button", { name: /下载/ }));

  const markdown = screen.getByRole("menuitem", {
    name: "Markdown (.md)",
  }) as HTMLAnchorElement;
  const pdf = screen.getByRole("menuitem", {
    name: "PDF (.pdf)",
  }) as HTMLAnchorElement;
  const docx = screen.getByRole("menuitem", {
    name: "Word (.docx)",
  }) as HTMLAnchorElement;

  expect(markdown.getAttribute("href")).toBe(
    "/api/conversations/conv-9/report/export?format=markdown",
  );
  expect(pdf.getAttribute("href")).toBe("/api/conversations/conv-9/report/export?format=pdf");
  expect(docx.getAttribute("href")).toBe("/api/conversations/conv-9/report/export?format=docx");
});

it("hides the download menu without a conversation id", () => {
  render(<ReportView report={report} />);
  expect(screen.queryByRole("button", { name: /下载/ })).not.toBeInTheDocument();
});
