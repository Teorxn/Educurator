import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import DashboardLayout from "./layouts/DashboardLayout";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Documents from "./pages/Documents";
import DocDetail from "./pages/DocDetail";
import Review from "./pages/Review";
import Analytics from "./pages/Analytics";
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
          {/* Documentos: pestañas "Documentos" y "Documentos de referencia",
              cada una con su propia subida (antes tres módulos separados) */}
          <Route path="/docs" element={<Documents />} />
          <Route path="/docs/:id" element={<DocDetail />} />
          <Route path="/review" element={<Review />} />
          {/* HU-31 — consultas en lenguaje natural */}
          <Route path="/chat" element={<Chat />} />
          <Route path="/agent-runs" element={<AgentRuns />} />
          <Route path="/analytics" element={<Analytics />} />
          {/* HU-30 — administración de usuarios y roles */}
          <Route path="/admin/users" element={<AdminUsers />} />
          {/* Enlaces/bookmarks antiguos */}
          <Route path="/upload" element={<Navigate to="/docs" replace />} />
          <Route
            path="/reference-docs"
            element={<Navigate to="/docs?tab=reference" replace />}
          />
        </Route>
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
