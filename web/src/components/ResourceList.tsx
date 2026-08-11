import type { CrawlResource } from "../types";

function formatBytes(bytes: number | null) {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  return `${Math.round(bytes / 1024)} KB`;
}

export function ResourceList({ taskId, resources }: { taskId: string; resources: CrawlResource[] }) {
  if (!resources.length) return null;
  return <section className="resource-section" aria-labelledby="resource-heading"><h2 id="resource-heading">抓取资源</h2><div className="resource-table-wrap"><table><thead><tr><th scope="col">来源链</th><th scope="col">层级 / 类型</th><th scope="col">下载</th><th scope="col">状态 / 提取</th><th scope="col">失败原因</th></tr></thead><tbody>{resources.map((resource) => <tr key={resource.canonical_url}><td><a href={resource.canonical_url} target="_blank" rel="noreferrer noopener">{resource.source_chain.join(" → ")}</a></td><td>第 {resource.depth} 层 · {resource.mime_type || "未知类型"}</td><td>{formatBytes(resource.downloaded_bytes)} / {formatBytes(resource.size)}{resource.document_id && <><br /><a href={`/api/tasks/${taskId}/resources/${resource.document_id}/download`}>下载资源</a></>}</td><td>{resource.status} · {resource.extraction.status}</td><td>{resource.error ?? resource.extraction.error ?? "—"}</td></tr>)}</tbody></table></div></section>;
}
