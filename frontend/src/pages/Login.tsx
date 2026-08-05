import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate, Navigate, Link } from "react-router-dom";
import { Loader2, AlertCircle, ArrowRight } from "lucide-react";
import { login } from "../api/docs";
import AuthLayout from "../layouts/AuthLayout";
import { clearProfileCache } from "../useProfile";

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
      // El perfil cacheado podría ser de la sesión anterior
      clearProfileCache();
      navigate("/dashboard");
    } catch {
      setError("Credenciales incorrectas. Verifica tu correo y contraseña.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Iniciar sesión"
      subtitle="Accede a tu base de conocimiento curada."
      footer={
        <>
          ¿No tienes cuenta?{" "}
          <Link
            to="/register"
            className="font-semibold text-brand hover:text-brand-hover"
          >
            Regístrate como docente
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="email" className="label">
            Correo electrónico
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
            autoComplete="email"
            placeholder="instructor@universidad.edu"
            className="input"
          />
        </div>

        <div>
          <label htmlFor="password" className="label">
            Contraseña
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            placeholder="••••••••"
            className="input"
          />
        </div>

        {error && (
          <div className="note note-danger" role="alert">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="btn btn-primary mt-2 w-full py-2.5"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Iniciando sesión...
            </>
          ) : (
            <>
              Entrar
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </button>
      </form>
    </AuthLayout>
  );
}
