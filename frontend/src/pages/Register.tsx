import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Loader2, AlertCircle, Plus, X, ArrowRight } from "lucide-react";
import { register } from "../api/account";
import AuthLayout from "../layouts/AuthLayout";
import { clearProfileCache } from "../useProfile";

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
      <span className="label">
        {label} {required && <span className="text-danger-fg">*</span>}
      </span>
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
          className="input"
        />
        <button
          type="button"
          onClick={add}
          className="btn btn-secondary shrink-0 px-3"
          aria-label={`Añadir a ${label}`}
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
      {values.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {values.map((v) => (
            <span key={v} className="chip chip-brand">
              {v}
              <button
                type="button"
                onClick={() => onChange(values.filter((x) => x !== v))}
                className="opacity-60 transition-opacity hover:opacity-100"
                aria-label={`Quitar ${v}`}
              >
                <X className="h-3 w-3" />
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
    if (fullName.trim().length < 3) return setError("Ingresa tu nombre completo");
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
      clearProfileCache();
      navigate("/dashboard");
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })
        ?.response?.data?.detail;
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
    <AuthLayout
      title="Crea tu cuenta"
      subtitle="Tu perfil académico permite al agente personalizar sus recomendaciones."
      footer={
        <>
          ¿Ya tienes cuenta?{" "}
          <Link
            to="/login"
            className="font-semibold text-brand hover:text-brand-hover"
          >
            Inicia sesión
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="fullName" className="label">
            Nombre completo <span className="text-danger-fg">*</span>
          </label>
          <input
            id="fullName"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
            autoComplete="name"
            className="input"
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="regEmail" className="label">
              Correo <span className="text-danger-fg">*</span>
            </label>
            <input
              id="regEmail"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="input"
            />
          </div>
          <div>
            <label htmlFor="regPassword" className="label">
              Contraseña <span className="text-danger-fg">*</span>
            </label>
            <input
              id="regPassword"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete="new-password"
              className="input"
            />
            <p className="mt-1 text-xs text-ink-3">Mínimo 8 caracteres</p>
          </div>
        </div>

        <div>
          <label htmlFor="profession" className="label">
            Profesión
          </label>
          <input
            id="profession"
            value={profession}
            onChange={(e) => setProfession(e.target.value)}
            placeholder="Ej: Ingeniero de sistemas"
            className="input"
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
          <div className="note note-danger" role="alert">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="btn btn-primary w-full py-2.5"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Creando cuenta...
            </>
          ) : (
            <>
              Crear cuenta
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </button>
      </form>
    </AuthLayout>
  );
}
