import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ExternalLink } from "lucide-react";
import type { FactEvidence } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const columnHelper = createColumnHelper<FactEvidence>();

const columns = [
  columnHelper.accessor("relation", {
    header: "关系",
    cell: (info) => (
      <Badge
        variant={info.getValue() === "supports" ? "default" : "secondary"}
        className={
          info.getValue() === "contradicts" ? "bg-destructive/10 text-destructive" : undefined
        }
      >
        {info.getValue() === "supports" ? "支持" : "反驳"}
      </Badge>
    ),
  }),
  columnHelper.accessor("quote", {
    header: "引用",
    cell: (info) => <span className="leading-relaxed">{info.getValue()}</span>,
  }),
  columnHelper.accessor("source_title", {
    header: "来源",
    cell: (info) => {
      const row = info.row.original;
      return (
        <a
          href={row.source_url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 text-primary hover:underline"
        >
          {info.getValue()}
          <ExternalLink className="size-3" />
        </a>
      );
    },
  }),
];

export function EvidenceTable({ evidence }: { evidence: FactEvidence[] }) {
  const table = useReactTable({
    data: evidence,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  if (evidence.length === 0) {
    return <p className="px-1 py-6 text-sm text-muted-foreground">暂无证据</p>;
  }

  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id}>
              {group.headers.map((header) => (
                <TableHead key={header.id}>
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <TableCell key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
