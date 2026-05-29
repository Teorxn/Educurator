import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import DashboardLayout from './layouts/DashboardLayout'
import Login from './pages/Login'
import Upload from './pages/Upload'
import DocList from './pages/DocList'
import Review from './pages/Review'
import Analytics from './pages/Analytics'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<DashboardLayout />}>
          <Route path="/upload"    element={<Upload />} />
          <Route path="/docs"      element={<DocList />} />
          <Route path="/review"    element={<Review />} />
          <Route path="/analytics" element={<Analytics />} />
        </Route>
        <Route path="*" element={<Navigate to="/docs" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
