import { useState, useRef } from 'react'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL ?? ''

const INS_TYPES     = ['壽險', '醫療險', '癌症險', '意外險', '失能險', '長照險', '儲蓄險']
const PREMIUM_TYPES = ['自然保費', '平準保費']

const TYPE_COLORS = {
  '壽險':  'bg-blue-100 text-blue-700',
  '醫療險': 'bg-green-100 text-green-700',
  '癌症險': 'bg-red-100 text-red-700',
  '意外險': 'bg-orange-100 text-orange-700',
  '失能險': 'bg-purple-100 text-purple-700',
  '長照險': 'bg-yellow-100 text-yellow-700',
  '儲蓄險': 'bg-teal/10 text-teal',
}

const EMPTY_FORM = {
  company: '', insurance_type: '壽險', product_name: '',
  coverage_amount: '', annual_premium: '', premium_type: '自然保費',
  coverage_end_age: 75,
}

export default function PoliciesPage({ policies, setPolicies, onBack, onAnalyze, isAnalyzing, error }) {
  const [form, setForm]             = useState(EMPTY_FORM)
  const [showForm, setShowForm]     = useState(false)
  const [scanning, setScanning]     = useState(false)
  const [scanResult, setScanResult] = useState(null)
  const [scanError, setScanError]   = useState(null)
  const [selected, setSelected]     = useState(new Set())
  // premium_type overrides for unverified items before adding to DB
  const [premiumOverride, setPremiumOverride] = useState({})
  // which index is being submitted to DB
  const [savingIdx, setSavingIdx]   = useState(null)
  const fileInputRef                = useRef(null)

  // ── Manual add ───────────────────────────────────────────────────────────────

  const handleAdd = () => {
    if (!form.company || !form.product_name || !form.coverage_amount || !form.annual_premium) {
      alert('請填寫保險公司、商品名稱、保額、年繳保費')
      return
    }
    setPolicies(prev => [...prev, {
      ...form,
      coverage_amount:  parseFloat(form.coverage_amount),
      annual_premium:   parseFloat(form.annual_premium),
      coverage_end_age: parseInt(form.coverage_end_age),
    }])
    setForm(EMPTY_FORM)
    setShowForm(false)
  }

  // ── Image scan ───────────────────────────────────────────────────────────────

  const handleScanClick = () => {
    setScanResult(null)
    setScanError(null)
    setPremiumOverride({})
    fileInputRef.current?.click()
  }

  const handleFileChange = (e) => {
    const file = e.target.files[0]
    if (!file) return
    e.target.value = ''

    if (file.size > 10 * 1024 * 1024) {
      setScanError('圖片太大（上限 10MB），請壓縮後再試')
      return
    }

    setScanning(true)
    setScanResult(null)
    setScanError(null)

    const reader = new FileReader()
    reader.onload = async (ev) => {
      try {
        const res = await axios.post(`${API}/extract-policies`, { image_base64: ev.target.result })
        const found = res.data.policies
        if (found.length === 0) {
          setScanError('未辨識到保單資料，請確認圖片清晰度並重試')
        } else {
          setScanResult(found)
          setSelected(new Set(found.map((_, i) => i)))
        }
      } catch (e) {
        setScanError(e.response?.data?.detail || '辨識失敗，請重試')
      } finally {
        setScanning(false)
      }
    }
    reader.readAsDataURL(file)
  }

  // ── Add single item to product DB ────────────────────────────────────────────

  const handleSaveToDb = async (i) => {
    const p = scanResult[i]
    const confirmedPremiumType = premiumOverride[i] ?? p.premium_type
    setSavingIdx(i)
    try {
      await axios.post(`${API}/products`, {
        company:          p.company,
        product_name:     p.product_name,
        insurance_type:   p.insurance_type,
        premium_type:     confirmedPremiumType,
        coverage_end_age: p.coverage_end_age || 75,
      })
      // Mark this item as verified locally
      setScanResult(prev => prev.map((item, idx) =>
        idx === i
          ? { ...item, db_status: 'verified', premium_type: confirmedPremiumType }
          : item
      ))
    } catch (e) {
      alert('加入失敗：' + (e.response?.data?.detail || '請重試'))
    } finally {
      setSavingIdx(null)
    }
  }

  // ── Confirm & add to policy list ─────────────────────────────────────────────

  const toggleSelect = (i) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(i) ? next.delete(i) : next.add(i)
      return next
    })
  }

  const handleAddScanned = () => {
    const toAdd = scanResult
      .filter((_, i) => selected.has(i))
      .map((p, i) => ({
        company:          p.company,
        insurance_type:   p.insurance_type,
        product_name:     p.product_name,
        coverage_amount:  parseFloat(p.coverage_amount)  || 0,
        annual_premium:   parseFloat(p.annual_premium)   || 0,
        premium_type:     premiumOverride[scanResult.indexOf(p)] ?? p.premium_type,
        coverage_end_age: parseInt(p.coverage_end_age)   || 75,
      }))
    setPolicies(prev => [...prev, ...toAdd])
    setScanResult(null)
    setSelected(new Set())
    setPremiumOverride({})
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  const totalPremium = policies.reduce((s, p) => s + p.annual_premium, 0)
  const verifiedCount = scanResult ? scanResult.filter(p => p.db_status === 'verified').length : 0

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div className="bg-white rounded-xl shadow-sm border p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-navy">現有保單</h2>
          <span className="text-sm text-gray-500">
            {policies.length} 筆｜年繳合計 {totalPremium.toLocaleString()} 元
          </span>
        </div>

        {policies.length === 0 && !showForm && !scanResult && (
          <div className="text-center py-8 text-gray-400">
            <p className="text-4xl mb-2">📄</p>
            <p className="text-sm">尚未新增保單，可直接點「開始 AI 分析」進行無保單分析</p>
          </div>
        )}

        {/* Policy list */}
        <div className="space-y-2 mb-3">
          {policies.map((p, i) => (
            <div key={i}
              className="border rounded-lg px-4 py-3 flex items-center justify-between hover:bg-gray-50 transition">
              <div className="flex items-center gap-3 flex-1 min-w-0">
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${TYPE_COLORS[p.insurance_type] || 'bg-gray-100 text-gray-600'}`}>
                  {p.insurance_type}
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">
                    {p.company}｜{p.product_name}
                  </p>
                  <p className="text-xs text-gray-500">
                    保額 {(p.coverage_amount / 10000).toFixed(0)} 萬 ／
                    年繳 {p.annual_premium.toLocaleString()} 元 ／
                    {p.premium_type} ／ 保障至 {p.coverage_end_age} 歲
                  </p>
                </div>
              </div>
              <button onClick={() => setPolicies(prev => prev.filter((_, j) => j !== i))}
                className="text-red-300 hover:text-red-500 ml-3 text-lg shrink-0">✕</button>
            </div>
          ))}
        </div>

        {/* Scan result */}
        {scanResult && (
          <div className="border-2 border-teal/40 rounded-xl p-4 bg-teal/5 mb-3">
            <div className="flex items-center justify-between mb-1">
              <p className="text-sm font-semibold text-navy">
                辨識結果（{scanResult.length} 筆）
              </p>
              <button onClick={() => { setScanResult(null); setPremiumOverride({}) }}
                className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
            </div>

            {/* Verified summary */}
            <p className="text-xs text-gray-500 mb-3">
              <span className="text-green-600 font-medium">✓ {verifiedCount} 筆已驗證</span>
              {scanResult.length - verifiedCount > 0 && (
                <span className="text-orange-500 font-medium ml-2">
                  ⚠ {scanResult.length - verifiedCount} 筆待確認
                </span>
              )}
              　驗證過的保費類型來自資料庫，未驗證的為 AI 推測。
            </p>

            <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
              {scanResult.map((p, i) => {
                const isVerified = p.db_status === 'verified'
                const currentPremiumType = premiumOverride[i] ?? p.premium_type
                return (
                  <div key={i} className={`rounded-xl border p-3 bg-white transition ${
                    isVerified ? 'border-green-200' : 'border-orange-200'
                  }`}>
                    {/* Top row: checkbox + tag + name + badge */}
                    <div className="flex items-start gap-3">
                      <input type="checkbox" checked={selected.has(i)} onChange={() => toggleSelect(i)}
                        className="accent-teal mt-0.5 shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${TYPE_COLORS[p.insurance_type] || 'bg-gray-100 text-gray-600'}`}>
                            {p.insurance_type}
                          </span>
                          <span className="text-sm font-medium text-gray-800">
                            {p.company}｜{p.product_name}
                          </span>
                          {isVerified
                            ? <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">✓ 已驗證</span>
                            : <span className="text-xs bg-orange-100 text-orange-600 px-2 py-0.5 rounded-full font-medium">⚠ 待確認</span>
                          }
                        </div>
                        <p className="text-xs text-gray-500 mt-0.5">
                          保額 {p.coverage_amount > 0 ? `${(p.coverage_amount / 10000).toFixed(0)}萬` : '—'} ／
                          年繳 {p.annual_premium > 0 ? `${p.annual_premium.toLocaleString()}元` : '—'} ／
                          保障至 {p.coverage_end_age} 歲
                        </p>
                      </div>
                    </div>

                    {/* Premium type row */}
                    <div className="flex items-center gap-2 mt-2 ml-6">
                      <span className="text-xs text-gray-500">保費類型：</span>
                      {isVerified
                        ? <span className="text-xs font-medium text-green-700 bg-green-50 px-2 py-0.5 rounded">
                            {p.premium_type}（資料庫）
                          </span>
                        : <>
                            <select
                              value={currentPremiumType}
                              onChange={e => setPremiumOverride(prev => ({ ...prev, [i]: e.target.value }))}
                              className="text-xs border rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-teal">
                              {PREMIUM_TYPES.map(t => <option key={t}>{t}</option>)}
                            </select>
                            <button
                              onClick={() => handleSaveToDb(i)}
                              disabled={savingIdx === i}
                              className="text-xs bg-teal text-white px-3 py-1 rounded-lg hover:bg-teal/90 transition disabled:opacity-60">
                              {savingIdx === i ? '儲存中...' : '確認並加入資料庫'}
                            </button>
                          </>
                      }
                    </div>
                  </div>
                )
              })}
            </div>

            <div className="flex gap-2 mt-3">
              <button onClick={handleAddScanned} disabled={selected.size === 0}
                className="flex-1 bg-navy text-white py-2 rounded-lg text-sm font-medium hover:bg-navy/90 transition disabled:opacity-50">
                加入保單清單（{selected.size} 筆）
              </button>
              <button onClick={() => { setScanResult(null); setPremiumOverride({}) }}
                className="px-4 py-2 border rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition">
                取消
              </button>
            </div>
          </div>
        )}

        {/* Scan error */}
        {scanError && (
          <div className="bg-orange-50 border border-orange-200 text-orange-700 rounded-lg px-4 py-3 text-sm mb-3 flex items-center justify-between">
            <span>⚠ {scanError}</span>
            <button onClick={() => setScanError(null)} className="text-orange-400 hover:text-orange-600 ml-3">✕</button>
          </div>
        )}

        {/* Manual add form */}
        {showForm && (
          <div className="border-2 border-teal/30 rounded-xl p-4 bg-teal/5 mb-3">
            <h3 className="text-sm font-semibold text-navy mb-3">手動新增保單</h3>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-600 mb-1">保險公司 *</label>
                <input type="text" value={form.company}
                  onChange={e => setForm(f => ({ ...f, company: e.target.value }))}
                  placeholder="國泰人壽"
                  className="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-teal" />
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">險種 *</label>
                <select value={form.insurance_type}
                  onChange={e => setForm(f => ({ ...f, insurance_type: e.target.value }))}
                  className="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-teal">
                  {INS_TYPES.map(t => <option key={t}>{t}</option>)}
                </select>
              </div>
              <div className="col-span-2">
                <label className="block text-xs text-gray-600 mb-1">商品名稱 *</label>
                <input type="text" value={form.product_name}
                  onChange={e => setForm(f => ({ ...f, product_name: e.target.value }))}
                  placeholder="鑫安心終身壽險"
                  className="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-teal" />
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">保障金額（元）*</label>
                <input type="number" min="0" value={form.coverage_amount}
                  onChange={e => setForm(f => ({ ...f, coverage_amount: e.target.value }))}
                  placeholder="1000000"
                  className="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-teal" />
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">年繳保費（元）*</label>
                <input type="number" min="0" value={form.annual_premium}
                  onChange={e => setForm(f => ({ ...f, annual_premium: e.target.value }))}
                  placeholder="25000"
                  className="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-teal" />
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">保費類型</label>
                <select value={form.premium_type}
                  onChange={e => setForm(f => ({ ...f, premium_type: e.target.value }))}
                  className="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-teal">
                  {PREMIUM_TYPES.map(t => <option key={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">保障終止年齡</label>
                <input type="number" min="60" max="110" value={form.coverage_end_age}
                  onChange={e => setForm(f => ({ ...f, coverage_end_age: e.target.value }))}
                  className="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-teal" />
              </div>
            </div>
            <div className="flex gap-2 mt-4">
              <button onClick={handleAdd}
                className="flex-1 bg-teal text-white py-2 rounded-lg text-sm font-medium hover:bg-teal/90 transition">
                ✓ 確認新增
              </button>
              <button onClick={() => { setForm(EMPTY_FORM); setShowForm(false) }}
                className="px-5 py-2 border rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition">
                取消
              </button>
            </div>
          </div>
        )}

        {/* Add buttons */}
        {!showForm && !scanResult && (
          <div className="flex gap-2">
            <button onClick={() => { setScanError(null); setShowForm(true) }}
              className="flex-1 border-2 border-dashed border-gray-300 text-gray-400 hover:border-navy hover:text-navy py-2.5 rounded-xl text-sm transition">
              ＋ 手動新增
            </button>
            <button onClick={handleScanClick} disabled={scanning}
              className="flex-1 border-2 border-dashed border-gray-300 text-gray-400 hover:border-teal hover:text-teal py-2.5 rounded-xl text-sm transition disabled:opacity-60 disabled:cursor-not-allowed">
              {scanning
                ? <span className="flex items-center justify-center gap-1.5">
                    <span className="animate-spin inline-block">⟳</span> 辨識中...
                  </span>
                : '📷 掃描文件辨識'
              }
            </button>
          </div>
        )}

        <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleFileChange} />
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
          ⚠️ {error}
        </div>
      )}

      <div className="flex gap-3">
        <button onClick={onBack}
          className="px-6 py-3 border rounded-lg text-gray-600 hover:bg-gray-50 transition">
          ← 上一步
        </button>
        <button onClick={onAnalyze} disabled={isAnalyzing}
          className="flex-1 bg-navy text-white py-3 rounded-lg font-medium hover:bg-navy/90 transition disabled:opacity-60 disabled:cursor-not-allowed">
          {isAnalyzing
            ? <span className="flex items-center justify-center gap-2">
                <span className="animate-spin inline-block">⟳</span> AI 分析中，約需 15 秒...
              </span>
            : '🔍 開始 AI 分析'
          }
        </button>
      </div>
    </div>
  )
}
