/**
 * Huecos de carga con la forma del contenido que van a sustituir.
 *
 * La alternativa —cambiar la página entera por un spinner— hace que el alto
 * del documento colapse y vuelva a crecer: la barra de scroll aparece y
 * desaparece y el contenido salta. Estos bloques ocupan el sitio definitivo.
 */
export default function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden />;
}

interface SkeletonTableProps {
  rows?: number;
  /** Anchos relativos de cada columna, en clases de utilidad. */
  cols?: string[];
}

export function SkeletonTable({
  rows = 5,
  cols = ["w-1/3", "w-16", "w-24", "w-20"],
}: SkeletonTableProps) {
  return (
    <div className="divide-y divide-line" aria-hidden>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-4 px-4 py-3.5">
          {cols.map((w, c) => (
            <Skeleton key={c} className={`h-4 ${w}`} />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Rótulo accesible para quien no ve la animación. */
export function LoadingLabel({ children }: { children: string }) {
  return (
    <span className="sr-only" role="status">
      {children}
    </span>
  );
}
