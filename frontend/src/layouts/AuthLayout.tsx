import type { ReactNode } from "react";
import { BookOpen, ShieldCheck, Sparkles } from "lucide-react";
import ThemeToggle from "../components/ThemeToggle";

const HIGHLIGHTS = [
  {
    icon: Sparkles,
    title: "Curación asistida",
    body: "El agente detecta redundancias, conflictos y vacíos en tu material.",
  },
  {
    icon: ShieldCheck,
    title: "Tú tienes la última palabra",
    body: "Ninguna sugerencia se aplica sin tu aprobación explícita.",
  },
  {
    icon: BookOpen,
    title: "Respuestas con fuente",
    body: "Cada respuesta cita el documento y el fragmento del que proviene.",
  },
];

/**
 * Marco de las pantallas de acceso: panel editorial a la izquierda con la
 * propuesta de valor, formulario a la derecha. En móvil se colapsa a una
 * cabecera compacta de marca sobre el formulario.
 */
export default function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-canvas">
      {/* Panel editorial — sólo en pantallas grandes */}
      <aside className="relative hidden w-[46%] max-w-2xl flex-col justify-between overflow-hidden bg-brand p-12 lg:flex">
        {/* Halo decorativo: da profundidad sin competir con el texto */}
        <div
          aria-hidden
          className="pointer-events-none absolute -top-32 -right-32 h-96 w-96 rounded-full bg-white/10 blur-3xl"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-40 -left-24 h-96 w-96 rounded-full bg-black/10 blur-3xl"
        />

        <div className="relative flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-fg/15 backdrop-blur">
            <img src="/Softserve.png" alt="" className="h-6 w-6 object-contain" />
          </div>
          <span className="font-display text-lg font-semibold text-brand-fg">
            EduCurator
          </span>
        </div>

        <div className="relative">
          <h2 className="font-display text-4xl leading-[1.15] font-semibold text-brand-fg">
            El material de tu curso,
            <br />
            siempre coherente.
          </h2>
          <p className="mt-4 max-w-md text-[15px] leading-relaxed text-brand-fg/75">
            Un asistente que revisa, contrasta y organiza tus documentos
            académicos — y te deja a ti la decisión final.
          </p>

          <ul className="mt-10 space-y-5">
            {HIGHLIGHTS.map(({ icon: Icon, title: t, body }) => (
              <li key={t} className="flex gap-3.5">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-fg/15 backdrop-blur">
                  <Icon className="h-4 w-4 text-brand-fg" />
                </span>
                <div>
                  <p className="text-sm font-semibold text-brand-fg">{t}</p>
                  <p className="mt-0.5 max-w-sm text-[13px] leading-relaxed text-brand-fg/70">
                    {body}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-xs text-brand-fg/60">
          SoftServe University Challenge · 2025
        </p>
      </aside>

      {/* Formulario */}
      <main className="flex flex-1 flex-col items-center justify-center px-4 py-10 sm:px-8">
        <div className="mb-6 flex w-full max-w-md items-center justify-between lg:justify-end">
          <div className="flex items-center gap-2.5 lg:hidden">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand">
              <img src="/Softserve.png" alt="" className="h-5 w-5 object-contain" />
            </div>
            <span className="font-display text-base font-semibold text-ink">
              EduCurator
            </span>
          </div>
          <ThemeToggle />
        </div>

        <div className="w-full max-w-md">
          <h1 className="font-display text-2xl font-semibold text-ink">{title}</h1>
          <p className="mt-1.5 text-sm text-ink-2">{subtitle}</p>

          <div className="mt-7">{children}</div>

          {footer && <div className="mt-6 text-center text-sm text-ink-2">{footer}</div>}
        </div>
      </main>
    </div>
  );
}
