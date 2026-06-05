import { useState, useEffect } from 'react'

const CURRENT_ROC_YEAR = new Date().getFullYear() - 1911

function calcAge(birthDateStr) {
  if (!birthDateStr) return null
  const birth = new Date(birthDateStr)
  const today = new Date()

  let actualAge = today.getFullYear() - birth.getFullYear()
  const mDiff = today.getMonth() - birth.getMonth()
  if (mDiff < 0 || (mDiff === 0 && today.getDate() < birth.getDate())) actualAge--

  // Months elapsed since last birthday
  let monthsSince = today.getMonth() - birth.getMonth()
  if (today.getDate() < birth.getDate()) monthsSince--
  if (monthsSince < 0) monthsSince += 12

  const insuranceAge = monthsSince >= 6 ? actualAge + 1 : actualAge
  return { actualAge, insuranceAge }
}

export default function ClientPage({ client, setClient, onNext }) {
  const [rocYear,  setRocYear]  = useState('')
  const [rocMonth, setRocMonth] = useState('')
  const [rocDay,   setRocDay]   = useState('')

  // Initialize ROC fields if client already has a birth_date
  useEffect(() => {
    if (client.birth_date) {
      const [y, m, d] = client.birth_date.split('-')
      setRocYear(String(parseInt(y) - 1911))
      setRocMonth(String(parseInt(m)))
      setRocDay(String(parseInt(d)))
    }
  }, [])

  // Sync ROC parts → client.birth_date (ISO) + auto-fill insurance_age
  useEffect(() => {
    const y = parseInt(rocYear)
    const m = parseInt(rocMonth)
    const d = parseInt(rocDay)
    if (rocYear && rocMonth && rocDay && y > 0 && m >= 1 && m <= 12 && d >= 1 && d <= 31) {
      const western  = y + 1911
      const birthDate = `${western}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`
      const info = calcAge(birthDate)
      setClient(c => ({
        ...c,
        birth_date:    birthDate,
        insurance_age: info ? String(info.insuranceAge) : c.insurance_age,
      }))
    } else {
      setClient(c => ({ ...c, birth_date: '' }))
      // keep insurance_age so user can still edit it manually
    }
  }, [rocYear, rocMonth, rocDay])

  const ageInfo = calcAge(client.birth_date)
  const recommendedLife = client.monthly_income > 0
    ? (client.monthly_income * 120 / 10000).toFixed(0)
    : null

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!client.name) {
      alert('請填寫客戶姓名')
      return
    }
    if (!client.birth_date && !client.insurance_age) {
      alert('請填寫出生日期，或直接輸入保險年齡（二擇一）')
      return
    }
    onNext()
  }

  return (
    <div className="max-w-2xl mx-auto">
      <div className="bg-white rounded-xl shadow-sm border p-6">
        <h2 className="text-xl font-bold text-navy mb-6">客戶基本資料</h2>
        <form onSubmit={handleSubmit} className="space-y-5">

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">客戶姓名 *</label>
            <input type="text" value={client.name}
              onChange={e => setClient(c => ({ ...c, name: e.target.value }))}
              placeholder="陳大明"
              className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal" />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">出生日期（民國）*</label>
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center gap-1">
                <span className="text-sm text-gray-500">民國</span>
                <input type="number" min="1" max={CURRENT_ROC_YEAR} value={rocYear}
                  onChange={e => setRocYear(e.target.value)}
                  placeholder="75"
                  className="w-20 border rounded-lg px-2 py-2 text-center focus:outline-none focus:ring-2 focus:ring-teal" />
                <span className="text-sm text-gray-500">年</span>
                <input type="number" min="1" max="12" value={rocMonth}
                  onChange={e => setRocMonth(e.target.value)}
                  placeholder="6"
                  className="w-14 border rounded-lg px-2 py-2 text-center focus:outline-none focus:ring-2 focus:ring-teal" />
                <span className="text-sm text-gray-500">月</span>
                <input type="number" min="1" max="31" value={rocDay}
                  onChange={e => setRocDay(e.target.value)}
                  placeholder="15"
                  className="w-14 border rounded-lg px-2 py-2 text-center focus:outline-none focus:ring-2 focus:ring-teal" />
                <span className="text-sm text-gray-500">日</span>
              </div>
              {ageInfo && (
                <div className="text-sm bg-teal/10 px-3 py-2 rounded-lg">
                  <span className="text-gray-600">足歲 <strong className="text-navy">{ageInfo.actualAge}</strong> 歲</span>
                  <span className="mx-2 text-gray-300">／</span>
                  <span className="text-gray-600">保險年齡 <strong className="text-teal">{ageInfo.insuranceAge}</strong> 歲</span>
                </div>
              )}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              保險年齡（歲）
              {client.birth_date
                ? <span className="text-gray-400 font-normal text-xs ml-1">（依出生日期自動計算，可手動覆蓋）</span>
                : <span className="text-teal font-normal text-xs ml-1">* 未填出生日期時必填</span>
              }
            </label>
            <input
              type="number" min="1" max="100"
              value={client.insurance_age || ''}
              onChange={e => setClient(c => ({ ...c, insurance_age: e.target.value }))}
              placeholder="35"
              className="w-32 border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">性別 *</label>
            <div className="flex gap-6">
              {[['male', '男性'], ['female', '女性']].map(([val, label]) => (
                <label key={val} className="flex items-center gap-2 cursor-pointer">
                  <input type="radio" name="gender" value={val}
                    checked={client.gender === val}
                    onChange={e => setClient(c => ({ ...c, gender: e.target.value }))}
                    className="accent-teal w-4 h-4" />
                  <span className="text-sm">{label}</span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">職業類別 *</label>
            <select value={client.occupation_class}
              onChange={e => setClient(c => ({ ...c, occupation_class: parseInt(e.target.value) }))}
              className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal">
              <option value={1}>第1類－辦公室／行政人員（風險最低）</option>
              <option value={2}>第2類－一般銷售／服務人員</option>
              <option value={3}>第3類－技術操作人員</option>
              <option value={4}>第4類－部分高風險作業</option>
              <option value={5}>第5類－高危險職業</option>
              <option value={6}>第6類－拒保職業</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              月收入（元）
              <span className="text-gray-400 font-normal text-xs ml-1">選填</span>
            </label>
            <input type="number" min="0"
              value={client.monthly_income || ''}
              onChange={e => setClient(c => ({ ...c, monthly_income: parseFloat(e.target.value) || 0 }))}
              placeholder="50000"
              className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teal" />
            {recommendedLife && (
              <p className="text-xs text-teal mt-1">
                壽險建議保額：<strong>{recommendedLife} 萬元</strong>（月收入 × 120 倍）
              </p>
            )}
          </div>

          <button type="submit"
            className="w-full bg-navy text-white py-3 rounded-lg font-medium hover:bg-navy/90 transition">
            下一步：填寫現有保單 →
          </button>
        </form>
      </div>
    </div>
  )
}
