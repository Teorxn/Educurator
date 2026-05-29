import { BarChart3 } from 'lucide-react'

export default function Analytics() {
  return (
    <div className="flex flex-col items-center justify-center h-64 text-center">
      <div className="w-14 h-14 bg-gray-100 rounded-2xl flex items-center justify-center mb-4">
        <BarChart3 className="w-7 h-7 text-gray-400" />
      </div>
      <p className="text-gray-600 font-medium">Analytics</p>
      <p className="text-sm text-gray-400 mt-1">Disponible en Sprint 2 — issue #29</p>
    </div>
  )
}
