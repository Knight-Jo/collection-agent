"""Render a captured model conversation (conversation.json) for debugging.

Reads the full per-turn message history written by the agent runner
(``--conversation <path>``) and prints a human-readable conversation, or
emits a self-contained HTML page (``--html``).

用法:
  python scripts/analyze_conversation.py <conversation.json>
  python scripts/analyze_conversation.py <run_dir>          # 自动找 run_dir/conversation.json
  python scripts/analyze_conversation.py <run_dir> --turn 3
  python scripts/analyze_conversation.py <run_dir> --grep web_search
  python scripts/analyze_conversation.py <run_dir> --html conversation.html
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import sys
from pathlib import Path

PART_LABELS = {
    "system-prompt": "系统提示",
    "user-prompt": "用户提示",
    "text": "模型输出",
    "thinking": "思考",
    "tool-call": "调用工具",
    "tool-return": "工具结果",
    "retry-prompt": "重试提示",
    "compaction": "上下文压缩",
    "file": "文件",
}


def _load(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"格式错误: {path} 不是消息数组")
    return data


def _resolve_path(arg: str) -> Path:
    path = Path(arg)
    if path.is_dir():
        candidate = path / "conversation.json"
        if candidate.exists():
            return candidate
        raise SystemExit(f"目录下未找到 conversation.json: {path}")
    return path


def _load_tool_specs(conversation_path: Path) -> list[dict]:
    sibling = conversation_path.with_name("tool-specs.json")
    if not sibling.exists():
        return []
    data = json.loads(sibling.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _clip(value: str, limit: int) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if len(value) <= limit:
        return value
    return value[:limit] + f" …（共 {len(value)} 字符，--full 展开）"


def _parse_json(value):
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped[0] in "[{":
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def _deep_parse(value):
    """Recursively parse stringified JSON (e.g. ``criteria`` double-encoded)."""
    if isinstance(value, dict):
        return {key: _deep_parse(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_deep_parse(val) for val in value]
    if isinstance(value, str):
        parsed = _parse_json(value)
        return _deep_parse(parsed) if parsed is not value else value
    return value


def _pretty_json(value) -> str:
    if value is None:
        return ""
    try:
        parsed = _deep_parse(value)
        if isinstance(parsed, (dict, list)):
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        return str(parsed)
    except (ValueError, TypeError):
        return str(value)


def _tool_result(part: dict, full: bool) -> str:
    text = _pretty_json(part.get("content"))
    return text if full else _clip(text, 400)


def _tool_args(part: dict) -> str:
    return _pretty_json(part.get("args"))


def _part_line(part: dict, *, full: bool, thinking: bool) -> tuple[str, str]:
    kind = str(part.get("part_kind") or "?")
    label = str(PART_LABELS.get(kind, kind))
    if kind in (
        "system-prompt",
        "user-prompt",
        "text",
        "thinking",
        "compaction",
    ):
        content = part.get("content")
        text = str(content) if content is not None else ""
        if kind != "thinking" or thinking:
            return label, text if full else _clip(text, 2000)
        return label, f"（{len(text)} 字符，--thinking 展开）"
    if kind == "tool-call":
        return (
            label,
            f"{part.get('tool_name')}({_clip(_tool_args(part), 300) if not full else _tool_args(part)})",
        )
    if kind == "tool-return":
        outcome = part.get("outcome")
        suffix = f" [{outcome}]" if outcome else ""
        return (
            label,
            f"{part.get('tool_name')}{suffix} → {_tool_result(part, full)}",
        )
    return label, _clip(json.dumps(part, ensure_ascii=False), 400)


def _iter_turns(messages: list[dict]):
    pending: list[dict] = []
    for message in messages:
        if message.get("kind") == "request":
            pending.extend(message.get("parts", []))
        else:
            yield pending, message.get("parts", [])
            pending = []
    if pending:
        yield pending, []


def _turn_matches(input_parts, output_parts, pattern: str) -> bool:
    haystack = json.dumps([input_parts, output_parts], ensure_ascii=False)
    return pattern.lower() in haystack.lower()


def _param_type(pschema: dict) -> str:
    if "type" in pschema:
        return str(pschema["type"])
    if "anyOf" in pschema:
        types = [
            str(item.get("type", "?"))
            for item in pschema["anyOf"]
            if isinstance(item, dict)
        ]
        return " | ".join(types) or "?"
    return "?"


def render_tools_terminal(tool_specs: list[dict]) -> None:
    if not tool_specs:
        return
    print(f"\n==== 工具清单（{len(tool_specs)} 个） ====")
    for spec in tool_specs:
        name = str(spec.get("name") or "?")
        desc = (spec.get("description") or "").strip()
        params = spec.get("parameters") or {}
        props = params.get("properties") if isinstance(params, dict) else {}
        required = (
            set(params.get("required") or [])
            if isinstance(params, dict)
            else set()
        )
        print(f"\n## {name}")
        if desc:
            print(f"  {_clip(desc, 400)}")
        if props:
            print("  参数:")
            for pname, pschema in props.items():
                if not isinstance(pschema, dict):
                    continue
                req = "（必填）" if pname in required else ""
                pdesc = (pschema.get("description") or "").strip()
                print(
                    f"    - {pname} [{_param_type(pschema)}]{req}: "
                    f"{_clip(pdesc, 120)}"
                )


def render_terminal(
    messages: list[dict],
    *,
    tool_specs: list[dict],
    turn: int | None,
    grep: str | None,
    full: bool,
    thinking: bool,
) -> int:
    if turn is None and not grep:
        render_tools_terminal(tool_specs)
    shown = 0
    for index, (input_parts, output_parts) in enumerate(
        _iter_turns(messages), 1
    ):
        if turn is not None and index != turn:
            continue
        if grep and not _turn_matches(input_parts, output_parts, grep):
            continue
        shown += 1
        print(f"\n==== 轮次 {index} ====")
        for part in input_parts:
            label, text = _part_line(part, full=full, thinking=thinking)
            print(f"[{label}] {text}")
        for part in output_parts:
            label, text = _part_line(part, full=full, thinking=thinking)
            print(f"[{label}] {text}")
    if shown == 0:
        print("没有匹配的轮次。", file=sys.stderr)
        return 1
    return 0


def _html_escape(value: str) -> str:
    return html_module.escape(value)


def _html_tool_spec(spec: dict) -> str:
    name = _html_escape(str(spec.get("name") or "?"))
    desc = _html_escape((spec.get("description") or "").strip())
    params = spec.get("parameters") or {}
    params_text = _pretty_json(params) or "{}"
    return (
        f'<details class="tool"><summary>{name}</summary>'
        f'<div class="tool-desc">{desc}</div>'
        f'<pre class="json">{_html_escape(params_text)}</pre>'
        f"</details>"
    )


def render_html(
    messages: list[dict], tool_specs: list[dict], out: Path
) -> None:
    turns = list(_iter_turns(messages))
    tools_html = "".join(_html_tool_spec(spec) for spec in tool_specs)
    parts = []
    if tools_html:
        parts.append(f'<section class="tools">{tools_html}</section>')
    for index, (input_parts, output_parts) in enumerate(turns, 1):
        input_html = "".join(_html_part(part) for part in input_parts)
        output_html = "".join(_html_part(part) for part in output_parts)
        parts.append(
            f'<section class="turn" id="turn-{index}">'
            f"<header>轮次 {index}</header>"
            f'<div class="input">{input_html}</div>'
            f'<div class="output">{output_html}</div>'
            f"</section>"
        )
    body = "\n".join(parts)
    document = HTML_TEMPLATE.replace("__BODY__", body).replace(
        "__COUNT__", str(len(turns))
    )
    out.write_text(document, encoding="utf-8")
    print(f"已写入 {out}")


def _html_part(part: dict) -> str:
    kind = str(part.get("part_kind") or "?")
    label = str(PART_LABELS.get(kind, kind))
    if kind in (
        "system-prompt",
        "user-prompt",
        "text",
        "thinking",
        "compaction",
    ):
        content = str(part.get("content") or "")
        return (
            f'<div class="part {kind}"><span class="tag">{_html_escape(label)}</span>'
            f"<pre>{_html_escape(content)}</pre></div>"
        )
    if kind == "tool-call":
        args = _pretty_json(part.get("args"))
        return (
            f'<div class="part tool-call"><span class="tag">{_html_escape(label)}</span>'
            f'<div><code class="tool-name">{_html_escape(part.get("tool_name") or "")}</code>'
            f'<pre class="json">{_html_escape(args)}</pre></div></div>'
        )
    if kind == "tool-return":
        outcome = part.get("outcome")
        detail = _pretty_json(part.get("content"))
        return (
            f'<div class="part tool-return"><span class="tag">{_html_escape(label)}</span>'
            f"<details><summary>{_html_escape(part.get('tool_name') or '')}"
            f"{' [' + _html_escape(outcome) + ']' if outcome else ''}</summary>"
            f'<pre class="json">{_html_escape(detail)}</pre></details></div>'
        )
    return f'<div class="part"><span class="tag">{_html_escape(label)}</span></div>'


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>模型会话｜__COUNT__ 轮</title>
<style>
:root{--ink:#10243b;--muted:#5d6c7d;--paper:#f6f8f3;--line:#dce3da;--navy:#0b1f33;--teal:#1b8a82;--orange:#ed6a3a}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Noto Sans CJK SC","Microsoft YaHei",Arial,sans-serif}
.toolbar{position:sticky;top:0;z-index:10;padding:14px 22px;background:rgba(11,31,51,.95);color:#fff;display:flex;gap:14px;align-items:center}
.toolbar input{flex:1;padding:9px 13px;border:1px solid rgba(255,255,255,.2);border-radius:8px;background:rgba(255,255,255,.08);color:#fff;outline:none}
.toolbar b{font-weight:700}.turn{margin:18px 22px;border:1px solid var(--line);border-radius:12px;background:#fff;overflow:hidden}
.turn>header{padding:9px 16px;background:var(--navy);color:#fff;font-weight:700;font-size:13px}
.input,.output{padding:4px 0}.part{display:grid;grid-template-columns:90px 1fr;gap:10px;padding:7px 16px;border-bottom:1px solid #f0f3ee;align-items:start}
.part:last-child{border-bottom:0}.tag{color:var(--teal);font-size:12px;font-weight:800}.part pre{margin:0;white-space:pre-wrap;word-break:break-word;font-family:inherit;font-size:13px;line-height:1.6}
.part code{font-family:Consolas,monospace;font-size:12px;word-break:break-all}.part.tool-call .tool-name{color:var(--orange);font-weight:700}
.part.tool-return summary{cursor:pointer;font-size:13px}.part.text pre{background:#fbfdf9}.part.thinking pre{color:var(--muted);font-style:italic}
pre.json{font-family:Consolas,Menlo,monospace;font-size:12px;line-height:1.55;background:#fbfdf9;border-radius:6px;padding:8px 10px}
.j-key{color:#0b7a9e}.j-str{color:#1e7a3c}.j-num{color:#c05621}.j-kw{color:#805ad5}
.tools{margin:18px 22px;border:1px solid var(--line);border-radius:12px;background:#fff;overflow:hidden}
.tools::before{content:"工具清单";display:block;padding:9px 16px;background:var(--navy);color:#fff;font-weight:700;font-size:13px}
.tool{border-bottom:1px solid #f0f3ee}.tool:last-child{border-bottom:0}
.tool summary{padding:9px 16px;cursor:pointer;font-weight:700;color:var(--orange);font-family:Consolas,monospace;font-size:13px}
.tool-desc{padding:0 16px 8px;color:var(--muted);font-size:13px;line-height:1.6}
.hidden{display:none}
</style>
</head>
<body>
<div class="toolbar"><b>模型会话</b><input id="q" type="search" placeholder="搜索（轮次内任意文本，回车过滤）"><span id="stat">__COUNT__ 轮</span></div>
<main>__BODY__</main>
<script>
const input=document.getElementById("q"),stat=document.getElementById("stat");
input.addEventListener("input",()=>{const q=input.value.toLowerCase();let n=0;
document.querySelectorAll(".turn").forEach(t=>{const m=t.textContent.toLowerCase().includes(q);t.classList.toggle("hidden",!m);if(m)n++;});
stat.textContent=(q?("命中 "+n+"/"):"")+document.querySelectorAll(".turn").length+" 轮";});
function esc(s){return s.replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}
function highlight(el){const text=el.textContent;const re=/("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;let out="",last=0,m;
while((m=re.exec(text))){out+=esc(text.slice(last,m.index));
if(m[1]){out+=(m[2]?'<span class="j-key">'+esc(m[1])+"</span>":'<span class="j-str">'+esc(m[1])+"</span>")+(m[2]||"");}
else if(m[3]){out+='<span class="j-kw">'+m[3]+"</span>";}
else{out+='<span class="j-num">'+m[0]+"</span>";}last=m.index+m[0].length;}
out+=esc(text.slice(last));el.innerHTML=out;}
document.querySelectorAll("pre.json").forEach(highlight);
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="渲染模型会话（conversation.json）"
    )
    parser.add_argument("path", help="conversation.json 或 run 目录")
    parser.add_argument("--turn", type=int, default=None, help="只看第 N 轮")
    parser.add_argument("--grep", default=None, help="只显示含关键词的轮次")
    parser.add_argument(
        "--full", action="store_true", help="展开完整工具结果/长文本"
    )
    parser.add_argument("--thinking", action="store_true", help="显示思考内容")
    parser.add_argument("--html", default=None, help="输出 HTML 而非终端")
    args = parser.parse_args()

    path = _resolve_path(args.path)
    if not path.exists():
        print(f"文件不存在: {path}", file=sys.stderr)
        return 1
    messages = _load(path)
    tool_specs = _load_tool_specs(path)
    if args.html:
        render_html(messages, tool_specs, Path(args.html))
        return 0
    return render_terminal(
        messages,
        tool_specs=tool_specs,
        turn=args.turn,
        grep=args.grep,
        full=args.full,
        thinking=args.thinking,
    )


if __name__ == "__main__":
    raise SystemExit(main())
