import { useState, useEffect } from 'react'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL ?? ''

export default function AdminPage({ onBack }) {
  const [users, setUsers] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ username: '', password: '', display_name: '', is_admin: false })
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [expiryEdit, setExpiryEdit] = useState(null) // { userId, value }
  const [costs, setCosts] = useState(null)

  const fetchCosts = async () => {
    try {
      const res = await axios.get(`${API}/admin/costs`)
      setCosts(res.data)
    } catch { /* 靜默 */ }
  }

  const fetchUsers = async () => {
    try {
      const res = await axios.get(`${API}/admin/users`)
      setUsers(res.data)
    } catch {
      setError('載入失敗，請重新整理')
    }
  }

  useEffect(() => { fetchUsers(); fetchCosts() }, [])

  const handleCreate = async (e) => {
    e.preventDefault()
    if (!form.username || !form.password || !form.display_name) {
      setError('請填寫帳號、顯示名稱、密碼')
      return
    }
    setLoading(true)
    setError(null)
    try {
      await axios.post(`${API}/admin/users`, form)
      setForm({ username: '', password: '', display_name: '', is_admin: false })
      setShowForm(false)
      fetchUsers()
    } catch (e) {
      setError(e.response?.data?.detail || '新增失敗')
    } finally {
      setLoading(false)
    }
  }

  const handleToggle = async (userId) => {
    setError(null)
    try {
      await axios.patch(`${API}/admin/users/${userId}/toggle`)
      fetchUsers()
    } catch (e) {
      setError(e.response?.data?.detail || '操作失敗')
    }
  }

  const handleSetExpiry = async (userId, value) => {
    setError(null)
    try {
      await axios.patch(`${API}/admin/users/${userId}/expires`, { expires_at: value || null })
      setExpiryEdit(null)
      fetchUsers()
    } catch (e) {
      setError(e.response?.data?.detail || '設定失敗')
    }
  }

  const handleResetDevice = async (userId) => {
    if (!confirm('確定要重置此帳號的裝置綁定？下次登入將重新綁定新裝置。')) return
    setError(null)
    try {
      await axios.patch(`${API}/admin/users/${userId}/reset-device`)
      fetchUsers()
    } catch (e) {
      setError(e.response?.data?.detail || '重置失敗')
    }
  }

  const totalAnalyses = users.reduce((s, u) => s + u.analysis_count, 0)

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-navy text-white shadow-md">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-4">
          <button onClick={onBack} className="text-white/70 hover:text-white text-sm transition">
            ← 返回工具
          </button>
          <span className="font-bold">後台管理</span>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6 space-y-6">

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { label: '帳號總數', value: `${users.length} / 10` },
            { label: '啟用中', value: users.filter(u => u.is_active).length },
            { label: '累計分析次數', value: totalAnalyses },
          ].map(({ label, value }) => (
            <div key={label} className="bg-white rounded-xl border shadow-sm p-4 text-center">
              <p className="text-2xl font-bold text-navy">{value}</p>
              <p className="text-sm text-gray-500 mt-1">{label}</p>
            </div>
          ))}
        </div>

        {/* Users */}
        <div className="bg-white rounded-xl border shadow-sm p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-bold text-navy">
              帳號管理
              <span className="text-sm font-normal text-gray-400 ml-2">（最多 10 個）</span>
            </h2>
            {!showForm && users.length < 10 && (
              <button onClick={() => setShowForm(true)}
                className="bg-teal text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-teal/90 transition">
                ＋ 新增帳號
              </button>
            )}
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 text-sm rounded-lg px-3 py-2 mb-4">
              {error}
            </div>
          )}

          {showForm && (
            <form onSubmit={handleCreate} className="border-2 border-teal/30 rounded-xl p-4 bg-teal/5 mb-4">
              <h3 className="text-sm font-semibold text-navy mb-3">新增帳號</h3>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-gray-600 mb-1">帳號 *</label>
                  <input type="text" value={form.username}
                    onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                    placeholder="username"
                    className="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-teal" />
                </div>
                <div>
                  <label className="block text-xs text-gray-600 mb-1">顯示名稱 *</label>
                  <input type="text" value={form.display_name}
                    onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))}
                    placeholder="王小明"
                    className="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-teal" />
                </div>
                <div>
                  <label className="block text-xs text-gray-600 mb-1">密碼 *</label>
                  <input type="password" value={form.password}
                    onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                    placeholder="••••••••"
                    className="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-teal" />
                </div>
                <div className="flex items-center gap-2 mt-4">
                  <input type="checkbox" id="is_admin" checked={form.is_admin}
                    onChange={e => setForm(f => ({ ...f, is_admin: e.target.checked }))}
                    className="accent-teal w-4 h-4" />
                  <label htmlFor="is_admin" className="text-sm text-gray-700 cursor-pointer">管理員權限</label>
                </div>
              </div>
              <div className="flex gap-2 mt-4">
                <button type="submit" disabled={loading}
                  className="flex-1 bg-teal text-white py-2 rounded-lg text-sm font-medium hover:bg-teal/90 transition disabled:opacity-60">
                  {loading ? '新增中...' : '✓ 確認新增'}
                </button>
                <button type="button" onClick={() => { setShowForm(false); setError(null) }}
                  className="px-5 py-2 border rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition">
                  取消
                </button>
              </div>
            </form>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-gray-500 text-xs">
                  <th className="text-left pb-2 font-medium">帳號</th>
                  <th className="text-left pb-2 font-medium">顯示名稱</th>
                  <th className="text-center pb-2 font-medium">身份</th>
                  <th className="text-center pb-2 font-medium">分析次數</th>
                  <th className="text-center pb-2 font-medium">到期日</th>
                  <th className="text-center pb-2 font-medium">裝置</th>
                  <th className="text-center pb-2 font-medium">狀態</th>
                  <th className="text-center pb-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {users.map(u => (
                  <tr key={u.id} className={!u.is_active ? 'opacity-40' : ''}>
                    <td className="py-3 font-mono text-gray-700">{u.username}</td>
                    <td className="py-3 text-gray-800">{u.display_name || '—'}</td>
                    <td className="py-3 text-center">
                      {u.is_admin
                        ? <span className="bg-navy text-white text-xs px-2 py-0.5 rounded-full">管理員</span>
                        : <span className="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded-full">一般</span>
                      }
                    </td>
                    <td className="py-3 text-center font-medium text-navy">{u.analysis_count}</td>
                    <td className="py-3 text-center text-xs">
                      {expiryEdit?.userId === u.id ? (
                        <div className="flex items-center gap-1 justify-center">
                          <input type="date" value={expiryEdit.value}
                            onChange={e => setExpiryEdit(v => ({ ...v, value: e.target.value }))}
                            className="border rounded px-1 py-0.5 text-xs" />
                          <button onClick={() => handleSetExpiry(u.id, expiryEdit.value)}
                            className="text-green-600 hover:text-green-800 font-bold">✓</button>
                          <button onClick={() => setExpiryEdit(null)}
                            className="text-gray-400 hover:text-gray-600">✕</button>
                        </div>
                      ) : (
                        <button onClick={() => setExpiryEdit({ userId: u.id, value: u.expires_at || '' })}
                          className={`px-2 py-0.5 rounded border text-xs transition hover:bg-gray-50 ${
                            u.expires_at && u.expires_at < new Date().toISOString().slice(0,10)
                              ? 'border-red-300 text-red-500'
                              : 'border-gray-200 text-gray-500'
                          }`}>
                          {u.expires_at || '永久'}
                        </button>
                      )}
                    </td>
                    <td className="py-3 text-center">
                      {u.has_device
                        ? <button onClick={() => handleResetDevice(u.id)}
                            className="text-xs px-2 py-0.5 rounded border border-orange-200 text-orange-500 hover:bg-orange-50 transition">
                            重置
                          </button>
                        : <span className="text-xs text-gray-300">未綁定</span>
                      }
                    </td>
                    <td className="py-3 text-center">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        u.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'
                      }`}>
                        {u.is_active ? '啟用' : '停用'}
                      </span>
                    </td>
                    <td className="py-3 text-center">
                      <button onClick={() => handleToggle(u.id)}
                        className={`text-xs px-3 py-1 rounded-lg border transition ${
                          u.is_active
                            ? 'border-red-200 text-red-500 hover:bg-red-50'
                            : 'border-green-200 text-green-600 hover:bg-green-50'
                        }`}>
                        {u.is_active ? '停用' : '啟用'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        {/* API 費用追蹤 */}
        {costs && (
          <div className="bg-white rounded-xl border shadow-sm p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-navy">API 費用紀錄</h2>
              <div className="text-right">
                <p className="text-2xl font-bold text-navy">${costs.total_usd.toFixed(4)} <span className="text-sm font-normal text-gray-400">USD</span></p>
                <p className="text-sm text-gray-400">≈ NT${(costs.total_usd * 32).toFixed(0)}</p>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b text-gray-400">
                    <th className="text-left pb-2 font-medium">時間</th>
                    <th className="text-left pb-2 font-medium">功能</th>
                    <th className="text-right pb-2 font-medium">Input</th>
                    <th className="text-right pb-2 font-medium">Output</th>
                    <th className="text-right pb-2 font-medium">費用</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {costs.logs.map(log => (
                    <tr key={log.id} className="text-gray-600">
                      <td className="py-2 text-gray-400">{log.created_at}</td>
                      <td className="py-2">
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                          log.endpoint === 'analyze' ? 'bg-blue-50 text-blue-600' :
                          log.endpoint === 'extract-policies' ? 'bg-purple-50 text-purple-600' :
                          'bg-gray-50 text-gray-500'
                        }`}>
                          {log.endpoint === 'analyze' ? '保障分析' :
                           log.endpoint === 'extract-policies' ? '掃描保單' :
                           log.endpoint === 'coverage-extract' ? '條款解讀' : log.endpoint}
                        </span>
                      </td>
                      <td className="py-2 text-right font-mono">{log.input_tokens.toLocaleString()}</td>
                      <td className="py-2 text-right font-mono">{log.output_tokens.toLocaleString()}</td>
                      <td className="py-2 text-right font-mono text-navy">${log.cost_usd.toFixed(4)}</td>
                    </tr>
                  ))}
                  {costs.logs.length === 0 && (
                    <tr><td colSpan={5} className="py-4 text-center text-gray-300">尚無紀錄</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
