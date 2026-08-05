import { useState } from 'react'
import { Outlet, Navigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import Header from '../components/Header'

export default function DashboardLayout() {
  const token = localStorage.getItem('access_token')
  const [sidebarOpen, setSidebarOpen] = useState(false)

  if (!token) return <Navigate to="/login" replace />

  return (
    <div className="flex min-h-screen bg-canvas">
      {/* Capa oscura tras el menú en móvil */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/50 backdrop-blur-[2px] sm:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <div
        className={`
          fixed inset-y-0 left-0 z-30 transition-transform duration-200 sm:relative sm:z-auto sm:translate-x-0
          ${sidebarOpen ? 'translate-x-0' : '-translate-x-full sm:translate-x-0'}
        `}
      >
        <Sidebar onClose={() => setSidebarOpen(false)} />
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <Header onMenuClick={() => setSidebarOpen((v) => !v)} />
        <main className="flex-1 px-4 py-6 sm:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
