import { KeyRound } from "lucide-react";
import { useState } from "react";
import type { AiSearchTool } from "@/api/types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  useAiSearchTools,
  useToggleAiSearchTool,
  useUpdateAiSearchToolApiKey,
} from "@/hooks/use-ai-search-tools";

export function AiSearchTools() {
  const { data: tools, isLoading } = useAiSearchTools();
  const toggle = useToggleAiSearchTool();
  const updateKey = useUpdateAiSearchToolApiKey();

  const [editing, setEditing] = useState<AiSearchTool | null>(null);
  const [apiKey, setApiKey] = useState("");

  function openEdit(tool: AiSearchTool) {
    setEditing(tool);
    setApiKey(tool.api_key);
  }

  async function saveKey() {
    if (!editing) return;
    await updateKey.mutateAsync({ id: editing.id, apiKey });
    setEditing(null);
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        通过 API Key 接入的 AI 搜索工具，提供语义检索与结构化返回。
      </p>

      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      )}

      {tools?.map((tool) => (
        <div
          key={tool.id}
          className="flex items-center justify-between gap-4 rounded-lg border bg-card p-3"
        >
          <div className="min-w-0">
            <p className="text-sm font-medium">{tool.name}</p>
            <p className="truncate text-xs text-muted-foreground">{tool.description}</p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => openEdit(tool)}
              className={tool.api_key ? "text-primary" : undefined}
            >
              <KeyRound />
              {tool.api_key ? "已配置" : "配置 API Key"}
            </Button>
            <Switch
              checked={tool.enabled}
              onCheckedChange={() => toggle.mutate(tool.id)}
              aria-label={`启用 ${tool.name}`}
            />
          </div>
        </div>
      ))}

      <Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>配置 API Key — {editing?.name}</DialogTitle>
            <DialogDescription>
              对应环境变量 <code className="rounded bg-muted px-1">{editing?.api_key_env}</code>
              ，密钥仅保存在本地配置中。
            </DialogDescription>
          </DialogHeader>
          <Input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={`输入 ${editing?.api_key_env}`}
          />
          <DialogFooter>
            <Button onClick={saveKey} disabled={updateKey.isPending}>
              {updateKey.isPending ? "保存中…" : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
