import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import DashboardLayout from "./layouts/DashboardLayout";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Upload from "./pages/Upload";
import DocDetail from "./pages/DocDetail";
import DocList from "./pages/DocList";
import Review from "./pages/Review";
import Analytics from "./pages/Analytics";
import ReferenceDocs from "./pages/ReferenceDocs";
import AgentRuns from "./pages/AgentRuns";
import Chat from "./pages/Chat";
import AdminUsers from "./pages/AdminUsers";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        {/* HU-29 — registro público de docentes */}
        <Route path="/register" element={<Register />} />
        <Route element={<DashboardLayout />}>
          {/* HU-20 — el panel es la primera pantalla tras iniciar sesión */}
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/docs" element={<DocList />} />
          <Route path="/docs/:id" element={<DocDetail />} />
          <Route path="/review" element={<Review />} />
          {/* HU-31 — consultas en lenguaje natural */}
          <Route path="/chat" element={<Chat />} />
          <Route path="/agent-runs" element={<AgentRuns />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/reference-docs" element={<ReferenceDocs />} />
          {/* HU-30 — administración de usuarios y roles */}
          <Route path="/admin/users" element={<AdminUsers />} />
        </Route>
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
