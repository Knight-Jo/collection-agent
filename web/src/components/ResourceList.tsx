import type { CrawlResource } from "../types";

function formatBytes(value: number | null) {
  if (value === null) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function ResourceList({ taskId, resources }: { taskId: string; resources: CrawlResource[] }) {
  if (!resources.length) return null;
  const sorted = [...resources].sort((left, right) => (right.rating ?? 0) - (left.rating ?? 0));
  return (
    <section className="resource-section" aria-labelledby="resource-heading">
      <h2 id="resource-heading">抓取资源</h2>
      <div className="resource-table-wrap"><table><thead><tr><th scope="col">阅读推荐</th><th scope="col">来源链</th><th scope="col">层级 / 类型</th><th scope="col">下载</th><th scope="col">状态 / 提取</th></tr></thead><tbody>
        {sorted.map((resource) => <tr key={resource.canonical_url}>
          <td><span className="material-stars" aria-label="阅读推荐">{resource.rating ? `${"★".repeat(resource.rating)}${"☆".repeat(5 - resource.rating)}` : "未评级"}</span><small className="material-description">{resource.description ?? resource.error ?? resource.extraction.error ?? "尚未生成阅读评价"}</small></td>
          <td><a href={resource.canonical_url} target="_blank" rel="noreferrer noopener">{resource.source_chain.join(" → ")}</a></td>
          <td>第 {resource.depth} 层 · {resource.mime_type || "未知类型"}</td>
          <td>{formatBytes(resource.downloaded_bytes)} / {formatBytes(resource.size)}{resource.document_id && <><br /><a href={`/api/tasks/${taskId}/resources/${resource.document_id}/download`}>下载资源</a></>}</td>
          <td>{resource.status} · {resource.extraction.status}{(resource.error ?? resource.extraction.error) && <><br />{resource.error ?? resource.extraction.error}</>}</td>
        </tr>)}
      </tbody></table></div>
    </section>
  );
}
