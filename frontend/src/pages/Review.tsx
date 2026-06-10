import { useEffect, useState, useCallback } from 'react'
import {
  CheckSquare,
  CheckCircle2,
  XCircle,
  Clock,
  AlertCircle,
  Loader2,
  X,
  FileText,
  Brain,
} from 'lucide-react'
import { getSuggestions, approveSuggestion, rejectSuggestion } from '../api/docs'
import type { Suggestion } from '../api/docs'

const TYPE_LABEL: Record<string, { label: string; color: string }> = {
  redundancy: { label: 'Redundancia', color: 'bg-amber-100 text-amber-800 border-amber-200' },
  conflict: { label: 'Conflicto', color: 'bg-red-100 text-red-800 border-red-200' },
  faq: { label: 'FAQ', color: 'bg-blue-100 text-blue-800 border-blue-200' },
}

const STATUS_BADGE: Record<string, { label: string; color: string; dot: string }> = {
  pending: { label: 'Pendiente', color: 'bg-yellow-50 text-yellow-700 border-yellow-200', dot: 'bg-yellow-400' },
  approved: { label: 'Aprobada', color: 'bg-green-50 text-green-700 border-green-200', dot: 'bg-green-500' },
  rejected: { label: 'Rechazada', color: 'bg-red-50 text-red-700 border-red-200', dot: 'bg-red-500' },
}

function fmtDate(d: string) {
  return new Intl.DateTimeFormat('es', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(d))
}

function fmtConfidence(score: number) {
  return `${(score * 100).toFixed(0)}%`
}

const TYPE_OPTIONS = [
  { value: '', label: 'Todos los tipos' },
  { value: 'redundancy', label: 'Redundancia' },
  { value: 'conflict', label: 'Conflicto' },
  { value: 'faq', label: 'FAQ' },
]

export default function Review() {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<string>('pending')
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [rejectModal, setRejectModal] = useState<{ id: string; open: boolean }>({ id: '', open: false })
  const [rejectReason, setRejectReason] = useState('')
  const [rejecting, setRejecting] = useState(false)
  const [actionLoading, setActionLoading] = useState<Record<string, 'approve' | 'reject' | null>>({})

  const fetchSuggestions = useCallback(async (isFirst = false) => {
    try {
      const params: Record<string, string> = {}
      if (filter !== 'all') params.status = filter
      if (typeFilter) params.type = typeFilter
      const { data } = await getSuggestions(params)
      setSuggestions(data.items)
    } catch {
      // silent
    } finally {
      if (isFirst) setLoading(false)
    }
  }, [filter, typeFilter])

  useEffect(() => {
    fetchSuggestions(true)
  }, [fetchSuggestions])

  const handleApprove = async (id: string) => {
    setActionLoading((p) => ({ ...p, [id]: 'approve' }))
    try {
      await approveSuggestion(id)
      setSuggestions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, status: 'approved' as const } : s))
      )
    } catch {
      // silent
    } finally {
      setActionLoading((p) => ({ ...p, [id]: null }))
    }
  }

  const openRejectModal = (id: string) => {
    setRejectModal({ id, open: true })
    setRejectReason('')
  }

  const handleReject = async () => {
    if (!rejectReason.trim()) return
    setRejecting(true)
    const id = rejectModal.id
    try {
      await rejectSuggestion(id, rejectReason)
      setSuggestions((prev) =>
        prev.map((s) => (s.id === id ? { ...s, status: 'rejected' as const, review_reason: rejectReason } : s))
      )
      setRejectModal({ id: '', open: false })
      setRejectReason('')
    } catch {
      // silent
    } finally {
      setRejecting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 gap-2">
        <Loader2 className="w-5 h-5 animate-spin" />
        <span className="text-sm">Cargando sugerencias...</span>
      </div>
    )
  }

  const pendingCount = suggestions.filter((s) => s.status === 'pending').length

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          {['pending', 'approved', 'rejected', 'all'].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`text-xs font-medium px-3 py-1.5 rounded-full border transition-colors ${
                filter === f
                  ? 'bg-violet-600 text-white border-violet-600'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-violet-300'
              }`}
            >
              {f === 'pending' ? 'Pendientes' : f === 'approved' ? 'Aprobadas' : f === 'rejected' ? 'Rechazadas' : 'Todas'}
            </button>
          ))}
          <span className="w-px h-5 bg-gray-200 mx-1" />
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="text-xs px-2 py-1.5 rounded-full border border-gray-200 bg-white text-gray-600 focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent"
          >
            {TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
        <p className="text-sm text-gray-500">
          {suggestions.length} sugerencia{suggestions.length !== 1 ? 's' : ''}
          {pendingCount > 0 && (
            <span className="text-yellow-600 ml-1">({pendingCount} pendientes)</span>
          )}
        </p>
      </div>

      {suggestions.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <div className="w-14 h-14 bg-gray-100 rounded-2xl flex items-center justify-center mb-4">
            <CheckSquare className="w-7 h-7 text-gray-400" />
          </div>
          <p className="text-gray-600 font-medium">No hay sugerencias</p>
          <p className="text-sm text-gray-400 mt-1">
            {filter === 'pending'
              ? 'No hay sugerencias pendientes de revisión'
              : `No hay sugerencias con el filtro seleccionado`}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {suggestions.map((s) => {
            const typeStyle = TYPE_LABEL[s.type] ?? TYPE_LABEL.redundancy
            const statusStyle = STATUS_BADGE[s.status] ?? STATUS_BADGE.pending
            const loading_action = actionLoading[s.id]

            return (
              <div
                key={s.id}
                className={`bg-white rounded-xl border p-4 transition-colors ${
                  s.status === 'pending' ? 'border-gray-200 hover:border-violet-200' : 'border-gray-100'
                }`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    {/* Header row */}
                    <div className="flex items-center gap-2 mb-2 flex-wrap">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${typeStyle.color}`}>
                        {typeStyle.label}
                      </span>
                      <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${statusStyle.color}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${statusStyle.dot}`} />
                        {statusStyle.label}
                      </span>
                      {s.document_name && (
                        <span className="flex items-center gap-1 text-xs text-gray-400">
                          <FileText className="w-3 h-3" />
                          {s.document_name}
                        </span>
                      )}
                      <span className="text-xs text-gray-400">{fmtDate(s.created_at)}</span>
                    </div>

                    {/* Description */}
                    <p className="text-sm text-gray-800 leading-relaxed">{s.description}</p>

                    {/* Confidence + Reasoning */}
                    <div className="flex items-center gap-3 mt-2">
                      <span className="text-xs font-medium text-violet-600 bg-violet-50 px-2 py-0.5 rounded-full">
                        Confianza: {fmtConfidence(s.confidence_score)}
                      </span>
                      {s.reasoning && (
                        <span className="flex items-center gap-1 text-xs text-gray-400">
                          <Brain className="w-3 h-3" />
                          <button
                            className="hover:text-violet-600 underline decoration-dotted"
                            title={s.reasoning}
                          >
                            Ver razonamiento
                          </button>
                        </span>
                      )}
                    </div>

                    {/* Rejection reason */}
                    {s.status === 'rejected' && s.review_reason && (
                      <div className="flex items-start gap-1.5 mt-2 text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2">
                        <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                        <span>{s.review_reason}</span>
                      </div>
                    )}
                  </div>

                  {/* Actions */}
                  {s.status === 'pending' && (
                    <div className="flex items-center gap-1.5 shrink-0">
                      {loading_action === 'approve' ? (
                        <span className="w-8 h-8 flex items-center justify-center">
                          <Loader2 className="w-4 h-4 animate-spin text-violet-600" />
                        </span>
                      ) : (
                        <button
                          onClick={() => handleApprove(s.id)}
                          className="w-8 h-8 flex items-center justify-center rounded-lg bg-green-50 text-green-600 hover:bg-green-100 transition-colors"
                          title="Aprobar"
                        >
                          <CheckCircle2 className="w-4 h-4" />
                        </button>
                      )}
                      {loading_action === 'reject' ? (
                        <span className="w-8 h-8 flex items-center justify-center">
                          <Loader2 className="w-4 h-4 animate-spin text-red-600" />
                        </span>
                      ) : (
                        <button
                          onClick={() => openRejectModal(s.id)}
                          className="w-8 h-8 flex items-center justify-center rounded-lg bg-red-50 text-red-600 hover:bg-red-100 transition-colors"
                          title="Rechazar"
                        >
                          <XCircle className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  )}
                  {s.status !== 'pending' && (
                    <div className="shrink-0">
                      {s.status === 'approved' ? (
                        <span className="flex items-center gap-1 text-xs text-green-600">
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          Aprobada
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-xs text-red-600">
                          <XCircle className="w-3.5 h-3.5" />
                          Rechazada
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Reject modal */}
      {rejectModal.open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="fixed inset-0 bg-black/40" onClick={() => setRejectModal({ id: '', open: false })} />
          <div className="relative bg-white rounded-2xl shadow-xl max-w-md w-full p-6 space-y-4 z-10">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900">Rechazar sugerencia</h3>
              <button
                onClick={() => setRejectModal({ id: '', open: false })}
                className="p-1 rounded-md text-gray-400 hover:text-gray-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-sm text-gray-600">Indica el motivo del rechazo:</p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              rows={3}
              autoFocus
              placeholder="Ej: Esta sugerencia no es relevante para el contenido del curso..."
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-red-400 focus:border-transparent resize-none"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setRejectModal({ id: '', open: false })}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleReject}
                disabled={!rejectReason.trim() || rejecting}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors flex items-center gap-2"
              >
                {rejecting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {rejecting ? 'Rechazando...' : 'Rechazar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
