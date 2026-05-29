import api from './axios'

export interface Document {
  id: string
  filename: string
  file_type: 'pdf' | 'docx' | 'txt'
  status: 'needs_review' | 'processing' | 'approved' | 'rejected' | 'archived'
  uploaded_at: string
  size_bytes: number
}

export interface DocsResponse {
  items: Document[]
  total: number
}

export interface AuthResponse {
  access_token: string
  token_type: string
}

export const login = (email: string, password: string) =>
  api.post<AuthResponse>('/auth/login', { email, password })

export const getDocs = (params?: { status?: string; page?: number; limit?: number }) =>
  api.get<DocsResponse>('/api/docs', { params })

export const uploadDoc = (file: File, onProgress?: (pct: number) => void) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<Document>('/api/docs/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total))
    },
  })
}
