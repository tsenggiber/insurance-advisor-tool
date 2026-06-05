import { useState } from 'react'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL ?? ''

export default function LoginPage({ onLogin }) {
  const [form, setForm] = useState({ username: '', password: '' })
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const device_token = localStorage.getItem('deviceToken') || undefined
      const res = await axios.post(`${API}/auth/login`, { ...form, device_token })
      if (res.data.device_token) {
        localStorage.setItem('deviceToken', res.data.device_token)
      }
      onLogin(res.data)
    } catch (e) {
      setError(e.response?.data?.detail || '登入失敗，請確認後端已啟動')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-lg w-full max-w-sm">
        <div className="bg-navy text-white px-6 py-5 rounded-t-xl text-center">
          <div className="w-12 h-12 bg-teal rounded-full flex items-center justify-center font-bold text-xl mx-auto mb-2">保</div>
          <h1 className="text-xl font-bold">保障缺口分析工具</h1>
          <p className="text-white/60 text-sm mt-1">請登入以繼續使用</p>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">帳號</label>
            <input
              type="text"
              value={form.username}
              onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
              placeholder="your_username"
              className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">密碼</label>
            <input
              type="password"
              value={form.password}
              onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
              placeholder="••••••••"
              className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal"
            />
          </div>
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 text-sm rounded-lg px-3 py-2">
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-navy text-white py-3 rounded-lg font-medium hover:bg-navy/90 transition disabled:opacity-60"
          >
            {loading ? '登入中...' : '登入'}
          </button>
        </form>
      </div>
    </div>
  )
}
