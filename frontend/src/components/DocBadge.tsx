import {
  Archive,
  CheckCircle2,
  Clock,
  Cpu,
  Sparkles,
  TriangleAlert,
  XCircle,
} from 'lucide-react'

interface StyleDef {
  /** Clase de tono del chip (fondo + texto ya emparejados y con contraste verificado). */
  tone: string
  icon: typeof Clock
  label: string
  /** El icono gira mientras el estado sea de trabajo en curso. */
  spin?: boolean
}

// El color nunca va solo: cada estado lleva icono + etiqueta, de modo que se
// distingue sin depender de percibir el matiz.
const STATUS_MAP: Record<string, StyleDef> = {
  queued: { tone: 'chip-neutral', icon: Clock, label: 'En cola' },
  processing: { tone: 'chip-info', icon: Cpu, label: 'Procesando', spin: true },
  analyzed: { tone: 'chip-brand', icon: Sparkles, label: 'Analizado' },
  error: { tone: 'chip-danger', icon: TriangleAlert, label: 'Error' },
  needs_review: { tone: 'chip-warning', icon: Clock, label: 'Por revisar' },
  approved: { tone: 'chip-success', icon: CheckCircle2, label: 'Aprobado' },
  rejected: { tone: 'chip-danger', icon: XCircle, label: 'Rechazado' },
  archived: { tone: 'chip-neutral', icon: Archive, label: 'Archivado' },
}

interface DocBadgeProps {
  status: string
  /** Renombra estados concretos sin duplicar el resto del mapa: los documentos
   *  de referencia hablan de disponibilidad, no de aprobación. */
  labels?: Record<string, string>
}

export default function DocBadge({ status, labels }: DocBadgeProps) {
  const s = STATUS_MAP[status] ?? STATUS_MAP['needs_review']
  const Icon = s.icon
  return (
    <span className={`chip ${s.tone}`}>
      <Icon className={`h-3 w-3 shrink-0 ${s.spin ? 'animate-spin' : ''}`} />
      {labels?.[status] ?? s.label}
    </span>
  )
}
