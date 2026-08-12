import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, MousePointerClick, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface TourStep {
  /** Selector del elemento a resaltar, normalmente `[data-tour="…"]`. */
  target?: string;
  /** Ruta en la que vive el paso; el recorrido navega antes de resaltar. */
  route?: string;
  icon: LucideIcon;
  title: string;
  body: string;
  /** La acción concreta que debe hacer el usuario en ese punto. */
  action?: string;
}

interface TourProps {
  open: boolean;
  steps: TourStep[];
  onClose: () => void;
}

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

const CARD_WIDTH = 340;
const GAP = 14;
const EDGE = 12;
/** Margen del recorte alrededor del elemento resaltado. */
const HALO = 6;

const EASE = "cubic-bezier(0.16,1,0.3,1)";
const DIM =
  "pointer-events-none absolute bg-black/60 transition-[top,left,width,height] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]";

/** Espera a que el elemento exista: tras navegar, la vista aún puede estar cargando. */
function waitFor(selector: string, timeout = 2500): Promise<Element | null> {
  const found = document.querySelector(selector);
  if (found) return Promise.resolve(found);

  return new Promise((resolve) => {
    const started = Date.now();
    const tick = () => {
      const el = document.querySelector(selector);
      if (el) return resolve(el);
      if (Date.now() - started > timeout) return resolve(null);
      requestAnimationFrame(tick);
    };
    tick();
  });
}

/**
 * Recorrido guiado: oscurece la pantalla salvo el elemento del paso actual y
 * explica junto a él qué hay que hacer. Si el elemento no está disponible
 * (una sección aún cargando, o una acción que ese rol no ve), el paso se
 * muestra centrado sin resalte en lugar de romperse.
 */
export default function Tour({ open, steps, onClose }: TourProps) {
  const [index, setIndex] = useState(0);
  // El ancla lleva el paso al que pertenece, así que al avanzar queda obsoleta
  // sola: no hay que limpiarla desde el efecto. `box: null` = se buscó y no
  // apareció (paso sin resalte); `anchor` obsoleta = todavía buscando.
  const [anchor, setAnchor] = useState<{ step: number; box: Box | null } | null>(
    null,
  );
  const [placement, setPlacement] = useState<{
    step: number;
    top: number;
    left: number;
  } | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const step = steps[index];
  const isLast = index === steps.length - 1;

  // Memoizado: un objeto nuevo en cada render haría que el efecto de
  // colocación se repitiera indefinidamente en los pasos sin elemento.
  const current = useMemo<{ step: number; box: Box | null } | null>(
    () =>
      step?.target
        ? anchor?.step === index
          ? anchor
          : null
        : { step: index, box: null },
    [step, anchor, index],
  );
  const box = current?.box ?? null;
  const cardPos = placement?.step === index ? placement : null;

  const close = useCallback(() => {
    setIndex(0);
    setAnchor(null);
    onClose();
  }, [onClose]);

  // Lleva a la ruta del paso y localiza el elemento a resaltar.
  useEffect(() => {
    if (!open || !step) return;
    let cancelled = false;

    if (step.route && step.route !== pathname) {
      navigate(step.route);
    }

    if (!step.target) return;

    waitFor(step.target).then((el) => {
      if (cancelled) return;
      if (!el) {
        setAnchor({ step: index, box: null });
        return;
      }
      // Desplazamiento inmediato, no suave: medir a mitad de una animación
      // deja el recorte y la tarjeta en la posición equivocada.
      el.scrollIntoView({ block: "center" });
      requestAnimationFrame(() => {
        if (cancelled) return;
        const r = el.getBoundingClientRect();
        setAnchor({
          step: index,
          box: { top: r.top, left: r.left, width: r.width, height: r.height },
        });
      });
    });

    return () => {
      cancelled = true;
    };
    // Depende de `pathname` a propósito: tras navegar vuelve a entrar y busca
    // el elemento ya en el DOM de la nueva vista.
  }, [open, index, step, pathname, navigate]);

  // Recoloca la tarjeta junto al elemento (o centrada si no hay elemento).
  // Mientras el elemento se está localizando, `current` es null y la tarjeta
  // sigue oculta: así no aparece centrada un instante antes de saltar al sitio.
  useLayoutEffect(() => {
    if (!open || !current) return;
    const card = cardRef.current;
    if (!card) return;

    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const h = card.offsetHeight;
    const w = Math.min(CARD_WIDTH, vw - EDGE * 2);

    if (!box) {
      setPlacement({
        step: index,
        top: Math.max(EDGE, (vh - h) / 2),
        left: Math.max(EDGE, (vw - w) / 2),
      });
      return;
    }

    const below = box.top + box.height + GAP;
    const above = box.top - GAP - h;
    const top =
      below + h <= vh - EDGE
        ? below
        : above >= EDGE
          ? above
          : Math.max(EDGE, (vh - h) / 2);

    const left = Math.min(
      Math.max(EDGE, box.left + box.width / 2 - w / 2),
      vw - w - EDGE,
    );

    setPlacement({ step: index, top, left });
  }, [open, current, box, index]);

  // Reposiciona si cambia el tamaño de la ventana o la página se desplaza.
  useEffect(() => {
    if (!open || !step?.target) return;

    const update = () => {
      const el = document.querySelector(step.target!);
      if (!el) return;
      const r = el.getBoundingClientRect();
      setAnchor({
        step: index,
        box: { top: r.top, left: r.left, width: r.width, height: r.height },
      });
    };
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, step, index]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "ArrowRight" && !isLast) setIndex((i) => i + 1);
      if (e.key === "ArrowLeft" && index > 0) setIndex((i) => i - 1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close, isLast, index]);

  if (!open || !step) return null;

  const Icon = step.icon;

  // El foco se mantiene SIEMPRE montado, con la misma geometría en la que se
  // quedó cuando no hay elemento que resaltar: si se desmontara y se volviera a
  // montar entre pasos, el velo desaparecería durante un fotograma y la página
  // se vería a plena luz — el destello que se notaba al pasar de paso.
  // Mientras se localiza el elemento del paso siguiente, `anchor` todavía
  // guarda el del paso anterior: sirve para cerrar el foco donde estaba en vez
  // de hacerlo saltar a una esquina.
  const spot = box ?? anchor?.box ?? null;
  const openSpot = Boolean(box);
  // Sin elemento que resaltar el hueco se cierra sobre sí mismo —los cuatro
  // paños se juntan— y la pantalla queda atenuada por completo.
  const geometry =
    spot && openSpot
      ? {
          top: spot.top - HALO,
          left: spot.left - HALO,
          width: spot.width + HALO * 2,
          height: spot.height + HALO * 2,
        }
      : spot
        ? { top: spot.top + spot.height / 2, left: spot.left + spot.width / 2, width: 0, height: 0 }
        : {
            top: window.innerHeight / 2,
            left: window.innerWidth / 2,
            width: 0,
            height: 0,
          };
  const { top, left, width, height } = geometry;

  return createPortal(
    <div
      className="anim-fade-in fixed inset-0 z-50"
      role="dialog"
      aria-modal="true"
    >
      {/* El velo son cuatro rectángulos alrededor del hueco, no la sombra
          gigante de un solo elemento: con `box-shadow: 0 0 0 9999px` el
          navegador no siempre rasteriza toda la extensión y quedaban franjas
          sin oscurecer en los bordes al cambiar de paso — el destello. */}
      <div className={DIM} style={{ top: 0, left: 0, right: 0, height: top }} />
      <div
        className={DIM}
        style={{ top: top + height, left: 0, right: 0, bottom: 0 }}
      />
      <div className={DIM} style={{ top, left: 0, width: left, height }} />
      <div
        className={DIM}
        style={{ top, left: left + width, right: 0, height }}
      />

      {/* El contorno va aparte del hueco: `outline` no compite con la sombra
          que dibuja el velo, y así puede aparecer y desaparecer por su cuenta. */}
      <div
        className="pointer-events-none absolute rounded-xl"
        style={{
          top,
          left,
          width,
          height,
          outline: "2px solid var(--c-brand)",
          opacity: openSpot ? 1 : 0,
          transition: `top 0.3s ${EASE}, left 0.3s ${EASE}, width 0.3s ${EASE}, height 0.3s ${EASE}, opacity 0.18s ease`,
        }}
      />

      {/* Captura los clics fuera de la tarjeta para que el recorrido no se
          pierda si el usuario pulsa el fondo. */}
      <div className="absolute inset-0" onClick={close} />

      <div
        key={index}
        ref={cardRef}
        onClick={(e) => e.stopPropagation()}
        className={`absolute w-[340px] max-w-[calc(100vw-24px)] rounded-2xl border border-line bg-surface shadow-[var(--shadow-overlay)] ${
          cardPos ? "anim-rise-in" : "invisible"
        }`}
        style={{ top: cardPos?.top ?? 0, left: cardPos?.left ?? 0 }}
      >
        <div className="flex items-start justify-between gap-3 p-4 pb-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="shrink-0 rounded-xl bg-brand-soft p-2 text-brand-soft-fg">
              <Icon className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-ink">{step.title}</h2>
              <p className="mt-0.5 text-[11px] text-ink-3">
                Paso {index + 1} de {steps.length}
              </p>
            </div>
          </div>
          <button
            onClick={close}
            className="btn-icon h-7 w-7 shrink-0"
            aria-label="Salir del tutorial"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        <div className="space-y-2 px-4 pb-3">
          <p className="text-sm leading-relaxed text-ink-2">{step.body}</p>
          {step.action && (
            <p className="note note-brand text-xs">
              <MousePointerClick className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {step.action}
            </p>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-line bg-surface-2 px-4 py-3">
          <div className="flex items-center gap-1.5">
            {steps.map((_, i) => (
              <button
                key={i}
                onClick={() => setIndex(i)}
                aria-label={`Ir al paso ${i + 1}`}
                className={`h-1.5 rounded-full transition-all ${
                  i === index ? "w-4 bg-brand" : "w-1.5 bg-line-strong"
                }`}
              />
            ))}
          </div>

          <div className="flex items-center gap-1.5">
            {index > 0 && (
              <button
                onClick={() => setIndex((i) => i - 1)}
                className="btn btn-ghost btn-sm"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
                Anterior
              </button>
            )}
            {isLast ? (
              <button onClick={close} className="btn btn-primary btn-sm">
                Entendido
              </button>
            ) : (
              <button
                onClick={() => setIndex((i) => i + 1)}
                className="btn btn-primary btn-sm"
              >
                Siguiente
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
