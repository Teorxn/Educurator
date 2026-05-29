interface StyleDef {
  bg: string
  text: string
  dot: string
  label: string
}

const STATUS_MAP: Record<string, StyleDef> = {
  needs_review: { bg: 'bg-gray-100', text: 'text-gray-700', dot: 'bg-gray-400', label: 'Pendiente' },
  processing:   { bg: 'bg-yellow-100', text: 'text-yellow-800', dot: 'bg-yellow-400 animate-pulse', label: 'Procesando' },
  approved:     { bg: 'bg-green-100', text: 'text-green-800', dot: 'bg-green-500', label: 'Aprobado' },
  rejected:     { bg: 'bg-red-100', text: 'text-red-800', dot: 'bg-red-500', label: 'Rechazado' },
  archived:     { bg: 'bg-blue-100', text: 'text-blue-800', dot: 'bg-blue-400', label: 'Archivado' },
}

export default function DocBadge({ status }: { status: string }) {
  const s = STATUS_MAP[status] ?? STATUS_MAP['needs_review']
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${s.bg} ${s.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  )
}
