import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Loader2, AlertCircle, Plus, X } from "lucide-react";
import { register } from "../api/account";

/** Campo multi-valor: el usuario añade y elimina ítems dinámicamente. */
function TagInput({
  label,
  placeholder,
  required,
  values,
  onChange,
}: {
  label: string;
  placeholder: string;
  required?: boolean;
  values: string[];
  onChange: (v: string[]) => void;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const v = draft.trim();
    if (!v || values.includes(v)) return;
    onChange([...values, v]);
    setDraft("");
  };

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1.5">
        {label} {required && <span className="text-red-500">*</span>}
      </label>
      <div className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent"
        />
        <button
          type="button"
          onClick={add}
          className="px-3 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-gray-600"
          aria-label={`Añadir a ${label}`}
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {values.map((v) => (
            <span
              key={v}
              className="inline-flex items-center gap-1 text-xs bg-violet-50 text-violet-700 border border-violet-200 px-2 py-1 rounded-full"
            >
              {v}
              <button
                type="button"
                onClick={() => onChange(values.filter((x) => x !== v))}
                className="hover:text-violet-900"
                aria-label={`Quitar ${v}`}
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** HU-29 — Registro de docente con perfil académico. */
export default function Register() {
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [profession, setProfession] = useState("");
  const [subjects, setSubjects] = useState<string[]>([]);
  const [specialties, setSpecialties] = useState<string[]>([]);
  const [courses, setCourses] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    // Validación previa al envío (criterio RNF de HU-29)
    if (fullName.trim().length < 3)
      return setError("Ingresa tu nombre completo");
    if (password.length < 8)
      return setError("La contraseña debe tener al menos 8 caracteres");
    if (subjects.length === 0)
      return setError("Indica al menos una materia que impartes");

    setLoading(true);
    try {
      const { data } = await register({
        email,
        password,
        full_name: fullName.trim(),
        profession: profession.trim() || undefined,
        subjects,
        specialties,
        courses_taught: courses,
      });
      localStorage.setItem("access_token", data.access_token);
      navigate("/dashboard");
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: unknown } } })?.response?.data
          ?.detail;
      setError(
        typeof detail === "string"
          ? detail
          : "No se pudo completar el registro. Revisa los datos e intenta de nuevo.",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-violet-950 flex items-center justify-center p-4">
      <div className="w-full max-w-lg my-8">
        <div className="flex flex-col items-center mb-6">
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
          <p className="text-slate-400 text-sm mt-1">Registro de docente</p>
        </div>

        <div className="bg-white rounded-2xl shadow-2xl p-7">
          <h2 className="text-xl font-semibold text-gray-900 mb-1">
            Crea tu cuenta
          </h2>
          <p className="text-sm text-gray-500 mb-5">
            Tu perfil académico permite al agente personalizar sus
            recomendaciones.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Nombre completo <span className="text-red-500">*</span>
              </label>
              <input
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent"
              />
            </div>

            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Correo <span className="text-red-500">*</span>
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  Contraseña <span className="text-red-500">*</span>
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent"
                />
                <p className="text-xs text-gray-400 mt-1">Mínimo 8 caracteres</p>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5">
                Profesión
              </label>
              <input
                value={profession}
                onChange={(e) => setProfession(e.target.value)}
                placeholder="Ej: Ingeniero de sistemas"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent"
              />
            </div>

            <TagInput
              label="Materias que impartes"
              placeholder="Ej: Cálculo diferencial"
              required
              values={subjects}
              onChange={setSubjects}
            />
            <TagInput
              label="Especialidades"
              placeholder="Ej: Machine learning"
              values={specialties}
              onChange={setSpecialties}
            />
            <TagInput
              label="Cursos impartidos"
              placeholder="Ej: Programación I"
              values={courses}
              onChange={setCourses}
            />

            {error && (
              <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-3 py-2.5">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 bg-violet-600 hover:bg-violet-700 disabled:bg-violet-300 text-white font-medium py-2.5 rounded-xl transition-colors"
            >
              {loading && <Loader2 className="w-4 h-4 animate-spin" />}
              {loading ? "Creando cuenta..." : "Crear cuenta"}
            </button>
          </form>

          <p className="text-sm text-gray-500 text-center mt-5">
            ¿Ya tienes cuenta?{" "}
            <Link
              to="/login"
              className="text-violet-600 hover:text-violet-700 font-medium"
            >
              Inicia sesión
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
