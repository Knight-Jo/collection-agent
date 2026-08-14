import { Check } from "lucide-react";
import type { Stage } from "../types";

const stages: Array<{ id: Stage; label: string }> = [
  { id: "collect", label: "资料收集" },
  { id: "assess", label: "综合研判" },
  { id: "challenge", label: "可选复审" },
  { id: "done", label: "报告完成" },
];

export function StageStepper({ stage }: { stage: Stage }) {
  const active = stages.findIndex((item) => item.id === stage);
  return (
    <ol className="stage-stepper" aria-label="研究进度">
      {stages.map((item, index) => {
        const state = index < active ? "complete" : index === active ? "active" : "pending";
        return (
          <li key={item.id} data-state={state}>
            <span className="stage-dot">{state === "complete" ? <Check size={14} /> : index + 1}</span>
            <span>{item.label}</span>
          </li>
        );
      })}
    </ol>
  );
}
