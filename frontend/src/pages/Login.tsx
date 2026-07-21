import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate, Navigate, Link } from "react-router-dom";
import { Loader2, AlertCircle } from "lucide-react";
import { login } from "../api/docs";

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (localStorage.getItem("access_token"))
    return <Navigate to="/dashboard" replace />;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { data } = await login(email, password);
      localStorage.setItem("access_token", data.access_token);
      navigate("/dashboard");
    } catch {
      setError("Credenciales incorrectas. Verifica tu correo y contraseña.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-violet-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Brand */}
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 bg-slate-700 rounded-2xl flex items-center justify-center mb-4 shadow-lg shadow-black/40">
            <img
              src="/Softserve.png"
              alt="SoftServe"
              className="w-9 h-9 object-contain"
            />
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">
            EduCurator AI
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Sistema de curación de conocimiento
          </p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl shadow-2xl p-8">
          <h2 className="text-xl font-semibold text-gray-900 mb-6">
            Iniciar sesión
          </h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Correo electrónico
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                placeholder="instructor@universidad.edu"
                className="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent placeholder:text-gray-400 transition-shadow"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Contraseña
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="••••••••"
                className="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 focus:border-transparent placeholder:text-gray-400 transition-shadow"
              />
            </div>

            {error && (
              <div className="flex items-center gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">
                <AlertCircle className="w-4 h-4 shrink-0" />
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-violet-600 hover:bg-violet-700 disabled:opacity-60 disabled:cursor-not-allowed text-white font-medium py-2.5 px-4 rounded-lg transition-colors flex items-center justify-center gap-2 mt-2"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              {loading ? "Iniciando sesión..." : "Entrar"}
            </button>
          </form>

          {/* HU-29 — acceso al registro de docentes */}
          <p className="text-sm text-gray-500 text-center mt-5">
            ¿No tienes cuenta?{" "}
            <Link
              to="/register"
              className="text-violet-600 hover:text-violet-700 font-medium"
            >
              Regístrate como docente
            </Link>
          </p>
        </div>

        <p className="text-center text-xs text-slate-500 mt-6">
          SoftServe University Challenge · 2025
        </p>
      </div>
    </div>
  );
}
