import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function ReportView({ markdown }: { markdown: string }) {
  return (
    <article className="report">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener">{children}</a>,
        }}
      >
        {markdown}
      </ReactMarkdown>
    </article>
  );
}
