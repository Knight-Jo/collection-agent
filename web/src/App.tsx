import { useEffect, useState } from "react";
import { Aperture } from "lucide-react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { DashboardPage } from "./pages/DashboardPage";
import { NewTaskPage } from "./pages/NewTaskPage";
import { RunPage } from "./pages/RunPage";
import { TaskPage } from "./pages/TaskPage";
import type { SystemStatus, TaskSummary } from "./types";

export default function App() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  useEffect(() => { api.tasks().then(setTasks); api.system().then(setSystem); }, []);
  return <div className="app"><header className="topbar"><Link className="brand" to="/"><Aperture />Intel<span>Workbench</span></Link><nav><NavLink to="/" end>研究</NavLink><NavLink to="/new">新建任务</NavLink></nav><div className="local-badge"><i />本地工作区</div></header><Routes><Route path="/" element={<DashboardPage tasks={tasks} system={system} />} /><Route path="/new" element={<NewTaskPage createRun={api.createRun} />} /><Route path="/runs/:runId" element={<RunPage />} /><Route path="/tasks/:taskId" element={<TaskPage />} /></Routes><footer className="site-footer">Intel Workbench · 本地运行 · 数据不会离开当前工作区</footer></div>;
}
