import { Send } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function Composer({
  busy,
  onSubmit,
}: {
  busy: boolean;
  onSubmit: (content: string) => void;
}) {
  const [value, setValue] = useState("");

  function submit() {
    const content = value.trim();
    if (!content || busy) return;
    setValue("");
    onSubmit(content);
  }

  return (
    <div className="flex items-end gap-2 border-t bg-background p-3">
      <Textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder="输入问题、修改方向或明确要求继续搜索…"
        className="min-h-[52px] resize-none"
        rows={2}
      />
      <Button onClick={submit} disabled={busy || !value.trim()} className="shrink-0">
        <Send className="size-4" />
        发送
      </Button>
    </div>
  );
}
