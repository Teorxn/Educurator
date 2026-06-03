/**
 * HU-09: Consultar sugerencias
 * HU-11: Aprobar sugerencias
 * HU-12: Rechazar sugerencias
 * HU-14: Revisar FAQs propuestas (type=faq)
 */
import { useEffect, useState, useRef } from 'react'
import { CheckCircle2, XCircle, ChevronDown, RefreshCw, AlertCircle, MessageSquare } from 'lucide-react'
import {
  getSuggestions, approveSuggestion, rejectSuggestion, addFeedback,
  type Suggestion, type SuggestionStatus, type SuggestionType,
} from '../api/suggestions'

// ── Helpers ──────────────────────────────────────────────────────────────────

const TYPE_LABELS: Record<SuggestionType, { label: string; color: string }> = {
  redundancy: { label: 'Redundancia',  color: 'bg-yellow-100 text-yellow-800' },
  conflict:   { label: 'Conflicto',    color: 'bg-red-100 text-red-800' },
  faq:        { label: 'FAQ',          color: 'bg-blue-100 text-blue-800' },
  update:     { label: 'Actualización',color: 'bg-purple-100 text-purple-800' },
}

const STATUS_LABELS: Record<SuggestionStatus, { label: string; color: string }> = {
  pending:  { label: 'Pendiente', color: 'bg-gray-100 text-gray-700' },
  approved: { label: 'Aprobada',  color: 'bg-green-100 text-green-800' },
  rejected: { label: 'Rechazada', color: 'bg-red-100 text-red-800' },
}

function fmtDate(d: string) {
  return new Intl.DateTimeFormat('es', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(d))
}

function ConfidenceBadge({ score }: { score: number | null }) {
  if (score === null) return null
  const pct = Math.round(score * 100)
  const color = pct >= 80 ? 'text-green-700' : pct >= 60 ? 'text-yellow-700' : 'text-red-700'
  return <span className={`text-xs font-semibold ${color}`}>{pct}%</span>
}

// ── Reject Modal ─────────────────────────────────────────────────────────────

function RejectModal({
  suggestion,
  onConfirm,
  onCancel,
}: {
  suggestion: Suggestion
  onConfirm: (reason: string) => void
  onCancel: () => void
}) {
  const [reason, setReason] = useState('')
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
        <h2 className="text-base font-semibold text-gray-900 mb-1">Rechazar sugerencia</h2>
        <p className="text-sm text-gray-500 mb-4 truncate">{suggestion.description}</p>
        <label className="block text-sm font-medium text-gray-700 mb-1.5">Motivo del rechazo *</label>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder="Explica por qué esta sugerencia no aplica..."
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 resize-none"
        />
        <div className="flex gap-2 mt-4">
          <button onClick={onCancel} className="flex-1 py-2 px-4 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50 transition-colors">
            Cancelar
          </button>
          <button
            onClick={() => reason.trim() && onConfirm(reason)}
            disabled={!reason.trim()}
            className="flex-1 py-2 px-4 bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
          >
            Rechazar
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Reasoning Modal ───────────────────────────────────────────────────────────

function ReasoningModal({ suggestion, onClose }: { suggestion: Suggestion; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg p-6 max-h-[80vh] overflow-y-auto">
        <div className="flex items-start justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900">Razonamiento del agente</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>
        <div className="space-y-3 text-sm">
          <div>
            <p className="font-medium text-gray-700 mb-1">Descripción</p>
            <p className="text-gray-600 bg-gray-50 rounded-lg p-3">{suggestion.description}</p>
          </div>
          {suggestion.reasoning && (
            <div>
              <p className="font-medium text-gray-700 mb-1">Razonamiento</p>
              <p className="text-gray-600 bg-gray-50 rounded-lg p-3 whitespace-pre-wrap">{suggestion.reasoning}</p>
            </div>
          )}
          {suggestion.confidence_score !== null && (
            <div className="flex items-center gap-2">
              <p className="font-medium text-gray-700">Confianza:</p>
              <ConfidenceBadge score={suggestion.confidence_score} />
            </div>
          )}
          {suggestion.source_chunk_ids && (
            <div>
              <p className="font-medium text-gray-700 mb-1">Chunks fuente</p>
              <code className="text-xs bg-gray-100 rounded p-2 block break-all">{suggestion.source_chunk_ids}</code>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Review() {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [loading, setLoading]       = useState(true)
  const [statusFilter, setStatus]   = useState<string>('pending')
  const [typeFilter, setType]       = useState<string>('')
  const [rejectTarget, setReject]   = useState<Suggestion | null>(null)
  const [reasoningTarget, setReasoning] = useState<Suggestion | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [toast, setToast]           = useState<{ msg: string; ok: boolean } | null>(null)
  const pollingRef                  = useRef<ReturnType<typeof setInterval> | null>(null)

  const showToast = (msg: string, ok = true) => {
    setToast({ msg, ok })
    setTimeout(() => setToast(null), 3000)
  }

  const fetchSuggestions = async () => {
    try {
      const { data } = await getSuggestions({
        status: statusFilter || undefined,
        type: typeFilter || undefined,
      })
      setSuggestions(data.items)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setLoading(true)
    fetchSuggestions()
    if (pollingRef.current) clearInterval(pollingRef.current)
    pollingRef.current = setInterval(fetchSuggestions, 8000)
    return () => { if (pollingRef.current) clearInterval(pollingRef.current) }
  }, [statusFilter, typeFilter])

  const handleApprove = async (s: Suggestion) => {
    setActionLoading(s.id)
    try {
      await approveSuggestion(s.id)
      setSuggestions((prev) => prev.filter((x) => x.id !== s.id))
      showToast('Sugerencia aprobada correctamente')
    } catch {
      showToast('Error al aprobar', false)
    } finally {
      setActionLoading(null)
    }
  }

  const handleReject = async (reason: string) => {
    if (!rejectTarget) return
    setActionLoading(rejectTarget.id)
    setReject(null)
    try {
      await rejectSuggestion(rejectTarget.id, reason)
      setSuggestions((prev) => prev.filter((x) => x.id !== rejectTarget.id))
      showToast('Sugerencia rechazada')
    } catch {
      showToast('Error al rechazar', false)
    } finally {
      setActionLoading(null)
    }
  }

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <select
          value={statusFilter}
          onChange={(e) => setStatus(e.target.value)}
          className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-violet-500"
        >
          <option value="">Todos los estados</option>
          <option value="pending">Pendientes</option>
          <option value="approved">Aprobadas</option>
          <option value="rejected">Rechazadas</option>
        </select>

        <select
          value={typeFilter}
          onChange={(e) => setType(e.target.value)}
          className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-violet-500"
        >
          <option value="">Todos los tipos</option>
          <option value="redundancy">Redundancia</option>
          <option value="conflict">Conflicto</option>
          <option value="faq">FAQ</option>
          <option value="update">Actualización</option>
        </select>

        <span className="ml-auto text-xs text-gray-400">{suggestions.length} resultado{suggestions.length !== 1 ? 's' : ''}</span>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center h-64 text-gray-400 gap-2">
          <RefreshCw className="w-5 h-5 animate-spin" />
          <span className="text-sm">Cargando sugerencias...</span>
        </div>
      ) : suggestions.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <AlertCircle className="w-10 h-10 text-gray-300 mb-3" />
          <p className="text-gray-500 text-sm">No hay sugerencias con los filtros seleccionados</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600">Tipo</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">Descripción</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">Confianza</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">Estado</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">Fecha</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {suggestions.map((s) => {
                const typeInfo = TYPE_LABELS[s.type] ?? { label: s.type, color: 'bg-gray-100 text-gray-700' }
                const statusInfo = STATUS_LABELS[s.status]
                const isLoading = actionLoading === s.id
                return (
                  <tr key={s.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${typeInfo.color}`}>
                        {typeInfo.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 max-w-xs">
                      <p className="truncate text-gray-800">{s.description}</p>
                      {s.reasoning && (
                        <button
                          onClick={() => setReasoning(s)}
                          className="flex items-center gap-1 text-xs text-violet-600 hover:underline mt-0.5"
                        >
                          <MessageSquare className="w-3 h-3" /> Ver razonamiento
                        </button>
                      )}
                    </td>
                    <td className="px-4 py-3"><ConfidenceBadge score={s.confidence_score} /></td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${statusInfo.color}`}>
                        {statusInfo.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">{fmtDate(s.created_at)}</td>
                    <td className="px-4 py-3">
                      {s.status === 'pending' && (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => handleApprove(s)}
                            disabled={isLoading}
                            title="Aprobar"
                            className="p-1.5 rounded-md bg-green-50 hover:bg-green-100 text-green-700 disabled:opacity-50 transition-colors"
                          >
                            <CheckCircle2 className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => setReject(s)}
                            disabled={isLoading}
                            title="Rechazar"
                            className="p-1.5 rounded-md bg-red-50 hover:bg-red-100 text-red-700 disabled:opacity-50 transition-colors"
                          >
                            <XCircle className="w-4 h-4" />
                          </button>
                        </div>
                      )}
                      {s.status === 'rejected' && s.rejection_reason && (
                        <span className="text-xs text-gray-400 italic truncate max-w-[120px] block" title={s.rejection_reason}>
                          {s.rejection_reason}
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className={`fixed bottom-6 right-6 flex items-center gap-2 px-4 py-3 rounded-xl shadow-lg text-sm font-medium text-white z-50 ${toast.ok ? 'bg-green-600' : 'bg-red-600'}`}>
          {toast.ok ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
          {toast.msg}
        </div>
      )}

      {/* Modals */}
      {rejectTarget && <RejectModal suggestion={rejectTarget} onConfirm={handleReject} onCancel={() => setReject(null)} />}
      {reasoningTarget && <ReasoningModal suggestion={reasoningTarget} onClose={() => setReasoning(null)} />}
    </div>
  )
}
