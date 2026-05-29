import { useEffect, useState, useRef } from 'react'
import { FileText, RefreshCw, Upload } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import DocBadge from '../components/DocBadge'
import { getDocs } from '../api/docs'
import type { Document } from '../api/docs'

const FILE_EMOJI: Record<string, string> = { pdf: '📄', docx: '📝', txt: '📃' }

function fmtDate(d: string) {
  return new Intl.DateTimeFormat('es', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(d))
}

function fmtSize(b: number) {
  if (b < 1024) return `${b} B`
  if (b < 1048576) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / 1048576).toFixed(1)} MB`
}

export default function DocList() {
  const navigate = useNavigate()
  const [docs, setDocs]       = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const pollingRef            = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchDocs = async (isFirstLoad = false) => {
    try {
      const { data } = await getDocs()
      const sorted = [...data.items].sort(
        (a, b) => new Date(b.uploaded_at).getTime() - new Date(a.uploaded_at).getTime(),
      )
      setDocs(sorted)

      const hasProcessing = data.items.some((d) => d.status === 'processing')
      if (!hasProcessing && pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    } catch {
      // silent fail on background polls
    } finally {
      if (isFirstLoad) setLoading(false)
    }
  }

  useEffect(() => {
    fetchDocs(true)
    pollingRef.current = setInterval(() => fetchDocs(false), 5000)
    return () => { if (pollingRef.current) clearInterval(pollingRef.current) }
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400 gap-2">
        <RefreshCw className="w-5 h-5 animate-spin" />
        <span className="text-sm">Cargando documentos...</span>
      </div>
    )
  }

  if (docs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-center">
        <div className="w-14 h-14 bg-gray-100 rounded-2xl flex items-center justify-center mb-4">
          <FileText className="w-7 h-7 text-gray-400" />
        </div>
        <p className="text-gray-600 font-medium">No hay documentos aún</p>
        <p className="text-sm text-gray-400 mt-1">Sube tu primer documento para comenzar</p>
        <button
          onClick={() => navigate('/upload')}
          className="mt-4 flex items-center gap-2 bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          <Upload className="w-3.5 h-3.5" />
          Subir documento
        </button>
      </div>
    )
  }

  const isPolling = docs.some((d) => d.status === 'processing')

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          {docs.length} documento{docs.length !== 1 ? 's' : ''}
        </p>
        {isPolling && (
          <span className="flex items-center gap-1.5 text-xs text-yellow-800 bg-yellow-50 border border-yellow-200 rounded-full px-3 py-1">
            <RefreshCw className="w-3 h-3 animate-spin" />
            Agente procesando...
          </span>
        )}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Documento</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Tipo</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Estado</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Tamaño</th>
              <th className="px-4 py-3 text-left font-medium text-gray-600">Subido</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {docs.map((doc) => (
              <tr key={doc.id} className="hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-base">{FILE_EMOJI[doc.file_type] ?? '📄'}</span>
                    <span className="font-medium text-gray-800 truncate max-w-xs">{doc.filename}</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className="uppercase text-xs font-semibold text-gray-400 tracking-wide">
                    {doc.file_type}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <DocBadge status={doc.status} />
                </td>
                <td className="px-4 py-3 text-gray-500">{fmtSize(doc.size_bytes)}</td>
                <td className="px-4 py-3 text-gray-500 text-xs">{fmtDate(doc.uploaded_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
