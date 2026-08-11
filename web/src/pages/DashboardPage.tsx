import { ArrowRight, FileSearch, Plus } from "lucide-react";
import { Link } from "react-router-dom";
import type { SystemStatus, TaskSummary } from "../types";

const stageLabel = { collect: "资料收集", assess: "综合研判", challenge: "红队复审", done: "已完成" };

export function DashboardPage({ tasks, system }: { tasks: TaskSummary[]; system: SystemStatus | null }) {
  return (
    <main className="page">
      <section className="hero">
        <div><div className="eyebrow">OSINT RESEARCH WORKBENCH</div><h1>让每个结论<br />都有证据可循</h1><p className="lead">从公开来源收集信息，自动建立事实、引文与归档文档之间的证据链。</p><Link className="primary-button" to="/new"><Plus size={18} />新建研究任务</Link></div>
        <div className="hero-orbit" aria-hidden="true"><span>检索</span><span>归档</span><span>审核</span><strong>可信<br />研判</strong></div>
      </section>
      <section className="section-heading"><div><span className="eyebrow">RECENT WORK</span><h2>最近的研究</h2></div><div className="service-status"><i data-ok={system?.model.configured} />模型 <i data-ok={system?.search.configured} />检索</div></section>
      {tasks.length ? <div className="task-grid">{tasks.map((task) => <Link className="task-card" to={`/tasks/${task.id}`} key={task.id}><div><span className={`status-pill stage-${task.stage}`}>{stageLabel[task.stage]}</span><time>{new Date(task.updated_at).toLocaleDateString("zh-CN")}</time></div><h3>{task.topic}</h3><dl><div><dt>证据</dt><dd>{task.evidence_count}</dd></div><div><dt>缺口分</dt><dd>{task.gap_score ?? "—"}</dd></div><div><dt>覆盖度</dt><dd>{task.coverage_level?.replace("_", " ") ?? "待评估"}</dd></div></dl><span className="card-link">查看研究 <ArrowRight size={16} /></span></Link>)}</div> : <div className="empty-state"><FileSearch size={34} /><h3>还没有研究任务</h3><p>创建第一个任务，工作台会在这里展示进展与报告。</p></div>}
    </main>
  );
}
