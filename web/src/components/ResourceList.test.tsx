import { render, screen } from "@testing-library/react";
import { ResourceList } from "./ResourceList";
import type { CrawlResource } from "../types";

function resource(url: string, rating: number): CrawlResource {
  return {
    canonical_url: url,
    source_chain: [url],
    depth: 0,
    status: "complete",
    mime_type: "text/html",
    size: 10,
    downloaded_bytes: 10,
    document_id: null,
    extraction: { status: "complete", processor: "html", text_path: null, error: null },
    error: null,
    rating,
    description: `${rating} 星材料`,
  };
}

it("sorts a copied material list by reading recommendation", () => {
  const resources = [resource("https://example.com/low", 2), resource("https://example.com/high", 5)];

  render(<ResourceList taskId="task-1" resources={resources} />);

  expect(screen.getAllByLabelText("阅读推荐")[0]).toHaveTextContent("★★★★★");
  expect(resources[0].rating).toBe(2);
  expect(screen.queryByText(/可信度/)).not.toBeInTheDocument();
});
