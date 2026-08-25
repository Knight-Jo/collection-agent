import { Aperture } from "lucide-react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import { ConversationWorkbenchPage } from "./pages/ConversationWorkbenchPage";
import { RunPage } from "./pages/RunPage";
import { TaskPage } from "./pages/TaskPage";

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link className="brand" to="/">
          <Aperture />
          Intel<span>Workbench</span>
        </Link>
        <p className="topbar-title">公开信息调研助手</p>
        <div className="local-badge">
          <i />
          本地工作区
        </div>
      </header>
      <Routes>
        <Route path="/" element={<ConversationWorkbenchPage />} />
        <Route path="/conversations/:conversationId" element={<ConversationWorkbenchPage />} />
        <Route path="/new" element={<Navigate to="/" replace />} />
        <Route path="/runs/:runId" element={<RunPage />} />
        <Route path="/tasks/:taskId" element={<TaskPage />} />
      </Routes>
    </div>
  );
}
