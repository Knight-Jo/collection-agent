import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { RunTimeline } from "../components/RunTimeline";
import type { Run, RunEvent } from "../types";

export function RunPage() {
  const { runId = "" } = useParams();
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api.run(runId).then((value) => active && setRun(value)).catch((cause) => setError(cause.message));
    const source = new EventSource(`/api/runs/${runId}/events`);
    const types = ["run.started", "tool.started", "tool.completed", "task.updated", "run.completed", "run.cancelled", "run.failed"];
    types.forEach((type) => source.addEventListener(type, (event) => {
      const message = event as MessageEvent;
      const next = { id: Number(message.lastEventId), type, timestamp: new Date().toISOString(), data: JSON.parse(message.data) };
      setEvents((items) => items.some((item) => item.id === next.id) ? items : [...items, next]);
      api.run(runId).then(setRun);
      if (type.startsWith("run.") && type !== "run.started") source.close();
    }));
    source.onerror = () => source.close();
    return () => { active = false; source.close(); };
  }, [runId]);

  const terminal = run && ["completed", "failed", "cancelled"].includes(run.status);
  return <main className="page narrow-page"><div className="eyebrow">LIVE RESEARCH</div><h1>{terminal ? "研究运行已结束" : "智能体正在工作"}</h1><p className="lead">页面可安全关闭；本地进程继续执行时，重新打开此地址即可查看当前状态。</p>{error && <p className="form-error">{error}</p>}<section className="panel run-panel"><div className="run-header"><span className={`status-pill stage-${run?.status === "completed" ? "done" : "collect"}`}>{run?.status ?? "连接中"}</span>{run && !terminal && <button className="secondary-button" onClick={() => api.cancelRun(runId).then(setRun)}>停止任务</button>}</div><RunTimeline events={events} />{run?.error && <p className="form-error">{run.error.message}</p>}{run?.task_id && terminal && <Link className="primary-button" to={`/tasks/${run.task_id}`}>查看研究结果</Link>}</section></main>;
}
