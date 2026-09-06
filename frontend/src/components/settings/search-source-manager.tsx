import { Cookie, Plus } from "lucide-react";
import { useState } from "react";
import type { SearchSource } from "@/api/types";
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
import { Textarea } from "@/components/ui/textarea";
import {
  useAddSearchSource,
  useSearchSources,
  useToggleSearchSource,
  useUpdateSearchSource,
} from "@/hooks/use-search-sources";

export function SearchSourceManager() {
  const { data: sources, isLoading } = useSearchSources();
  const toggle = useToggleSearchSource();
  const update = useUpdateSearchSource();
  const add = useAddSearchSource();

  const [cookieSource, setCookieSource] = useState<SearchSource | null>(null);
  const [cookieValue, setCookieValue] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");

  function openCookie(source: SearchSource) {
    setCookieSource(source);
    setCookieValue("");
  }

  async function saveCookie() {
    if (!cookieSource) return;
    await update.mutateAsync({ id: cookieSource.id, cookies: cookieValue });
    setCookieSource(null);
  }

  async function submitAdd() {
    if (!newName.trim() || !newUrl.trim()) return;
    await add.mutateAsync({ name: newName.trim(), url: newUrl.trim() });
    setNewName("");
    setNewUrl("");
    setAddOpen(false);
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          检索公开信息使用的来源站点，可为需要登录的站点配置 Cookie。
        </p>
        <Button variant="outline" size="sm" onClick={() => setAddOpen(true)}>
          <Plus />
          添加来源
        </Button>
      </div>

      {isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      )}

      {sources?.map((source) => (
        <div
          key={source.id}
          className="flex items-center justify-between gap-4 rounded-lg border bg-card p-3"
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{source.name}</p>
            <p className="truncate text-xs text-muted-foreground">{source.url}</p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => openCookie(source)}
              className={source.cookie_configured ? "text-primary" : undefined}
            >
              <Cookie />
              Cookie{source.cookie_configured ? " 已配置" : ""}
            </Button>
            <Switch
              checked={source.enabled}
              onCheckedChange={() => toggle.mutate(source.id)}
              aria-label={`启用 ${source.name}`}
            />
          </div>
        </div>
      ))}

      <Dialog open={cookieSource !== null} onOpenChange={(open) => !open && setCookieSource(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>配置 Cookie — {cookieSource?.name}</DialogTitle>
            <DialogDescription>
              为需要登录才能抓取的站点配置 Cookie（Cookie 头字符串，逐行 name=value）。
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={cookieValue}
            onChange={(event) => setCookieValue(event.target.value)}
            placeholder={"sessionid=xxx\ntoken=yyy"}
            rows={5}
          />
          <DialogFooter>
            <Button onClick={saveCookie} disabled={update.isPending}>
              {update.isPending ? "保存中…" : "保存"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>添加搜索来源</DialogTitle>
            <DialogDescription>新增一个搜索来源站点。</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder="名称，如 搜狗"
            />
            <Input
              value={newUrl}
              onChange={(event) => setNewUrl(event.target.value)}
              placeholder="地址，如 https://www.sogou.com"
            />
          </div>
          <DialogFooter>
            <Button
              onClick={submitAdd}
              disabled={!newName.trim() || !newUrl.trim() || add.isPending}
            >
              {add.isPending ? "添加中…" : "添加"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
