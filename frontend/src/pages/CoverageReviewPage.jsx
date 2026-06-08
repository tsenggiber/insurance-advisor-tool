// 保障總覽頁：保障檢視（pyramid）+ 方案推薦（AI分析）雙 tab

import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import html2canvas from 'html2canvas'

const API = import.meta.env.VITE_API_URL ?? ''
import { Line } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale,
  PointElement, LineElement, Title, Tooltip, Legend, Filler
} from 'chart.js'
ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler)

// ── 彙整所有保單的細部保障 ────────────────────────────────────────────────────

function aggregate(policies) {
  const s = {
    lifeTraditional: 0, accidentDeath: 0,
    longCareMonthly: 0, disabilityMonthly: 0,
    criticalIllness: 0, cancerFirst: 0, cancerHospDaily: 0, cancerSurgery: 0,
    diseaseHospLifetime: 0, diseaseHospNonLifetime: 0,
    accidentHospDaily: 0, fracture: 0,
    inpatientSurgeryLifetime: 0, inpatientSurgeryNonLifetime: 0,
    outpatientSurgeryLifetime: 0, outpatientSurgeryNonLifetime: 0,
    specificTreatmentLifetime: 0, specificTreatmentNonLifetime: 0,
    medicalReimburseQuasi: 0, medicalReimburseNon: 0,
    accidentReimburse: 0, deductible: 0,
    totalPremium: 0,
  }

  for (const p of policies) {
    s.totalPremium += p.annual_premium || 0
    const lifetime = p.is_lifetime || p.coverage_end_age >= 99

    // 細部欄位優先
    if (p.disease_hosp_daily)  lifetime ? (s.diseaseHospLifetime += p.disease_hosp_daily) : (s.diseaseHospNonLifetime += p.disease_hosp_daily)
    if (p.accident_hosp_daily) s.accidentHospDaily += p.accident_hosp_daily
    if (p.inpatient_surgery)   lifetime ? (s.inpatientSurgeryLifetime += p.inpatient_surgery) : (s.inpatientSurgeryNonLifetime += p.inpatient_surgery)
    if (p.outpatient_surgery)  lifetime ? (s.outpatientSurgeryLifetime += p.outpatient_surgery) : (s.outpatientSurgeryNonLifetime += p.outpatient_surgery)
    if (p.specific_treatment)  lifetime ? (s.specificTreatmentLifetime += p.specific_treatment) : (s.specificTreatmentNonLifetime += p.specific_treatment)
    if (p.medical_reimburse)   lifetime ? (s.medicalReimburseQuasi += p.medical_reimburse) : (s.medicalReimburseNon += p.medical_reimburse)
    if (p.accident_reimburse)  s.accidentReimburse += p.accident_reimburse
    if (p.deductible)          s.deductible = Math.max(s.deductible, p.deductible)
    if (p.disability_monthly)  s.disabilityMonthly += p.disability_monthly
    if (p.long_care_monthly)   s.longCareMonthly += p.long_care_monthly
    if (p.critical_illness)    s.criticalIllness += p.critical_illness
    if (p.cancer_first)        s.cancerFirst += p.cancer_first
    if (p.cancer_hosp_daily)   s.cancerHospDaily += p.cancer_hosp_daily
    if (p.cancer_surgery)      s.cancerSurgery += p.cancer_surgery
    if (p.accident_death)      s.accidentDeath += p.accident_death
    if (p.fracture)            s.fracture += p.fracture

    // 無細部欄位時，只對保額語意明確的險種做 fallback
    // 醫療險/失能險/長照險：coverage_amount 不可靠（可能是舊掃描或主約金額），一律不猜
    const hasDetail = p.disease_hosp_daily || p.inpatient_surgery || p.medical_reimburse ||
                      p.cancer_first || p.cancer_hosp_daily || p.disability_monthly ||
                      p.long_care_monthly || p.accident_death || p.critical_illness ||
                      p.accident_reimburse
    if (!hasDetail) {
      const amt = p.coverage_amount || 0
      switch (p.insurance_type) {
        case '壽險':   s.lifeTraditional += amt; break
        case '意外險': s.accidentDeath   += amt; break
        case '癌症險': s.cancerFirst     += amt; break
        case '儲蓄險': s.lifeTraditional += amt; break
        // 醫療險、失能險、長照險：等 enrichment 填入 detail 欄位後才顯示
      }
    }
  }
  return s
}

// ── 取得保險年齡 ──────────────────────────────────────────────────────────────

function getAge(client) {
  if (client.insurance_age) return parseInt(client.insurance_age)
  if (client.birth_date) {
    const today = new Date()
    const birth = new Date(client.birth_date)
    let age = today.getFullYear() - birth.getFullYear()
    if (today.getMonth() < birth.getMonth() ||
        (today.getMonth() === birth.getMonth() && today.getDate() < birth.getDate())) age--
    return age
  }
  return 35
}

// ── 台灣第六回生命表（TSO2002）qx 死亡率 ─────────────────────────────────────
// 自然保費費率正比於 qx（死亡率 / 罹病率）

const QX = {
  male: {
    15:0.00066,20:0.00089,25:0.00088,30:0.00101,35:0.00140,
    40:0.00213,45:0.00357,50:0.00617,55:0.01002,60:0.01612,
    65:0.02711,70:0.04513,75:0.07542,80:0.12284,85:0.19423,
  },
  female: {
    15:0.00030,20:0.00040,25:0.00043,30:0.00047,35:0.00073,
    40:0.00112,45:0.00197,50:0.00354,55:0.00628,60:0.01026,
    65:0.01762,70:0.03038,75:0.05261,80:0.08967,85:0.14947,
  },
}

function getQx(age, gender) {
  const table = QX[gender] ?? QX.male
  const ages  = Object.keys(table).map(Number).sort((a, b) => a - b)
  for (let i = 0; i < ages.length - 1; i++) {
    if (age >= ages[i] && age <= ages[i + 1]) {
      const t = (age - ages[i]) / (ages[i + 1] - ages[i])
      return table[ages[i]] + t * (table[ages[i + 1]] - table[ages[i]])
    }
  }
  return table[ages[ages.length - 1]]
}

// ── 計算保單購買時的年齡 ──────────────────────────────────────────────────────
// policy_date 為民國格式（如 110/05/01），birth_date 為西元格式（YYYY-MM-DD）

function getPolicyStartAge(policy, client) {
  if (!policy.policy_date || !client.birth_date) return null
  const parts = policy.policy_date.replace(/\s/g, '').split('/')
  if (parts.length < 3) return null
  const rocYear = parseInt(parts[0])
  if (isNaN(rocYear)) return null
  const policyStart = new Date(rocYear + 1911, parseInt(parts[1]) - 1, parseInt(parts[2]))
  const birth = new Date(client.birth_date)
  let age = policyStart.getFullYear() - birth.getFullYear()
  const m = policyStart.getMonth() - birth.getMonth()
  if (m < 0 || (m === 0 && policyStart.getDate() < birth.getDate())) age--
  return age >= 0 ? age : null
}

// ── 從費率表插值取某年齡費率 ─────────────────────────────────────────────────

function interpolateRate(rateTable, age) {
  if (!rateTable || rateTable.length === 0) return null
  const sorted = [...rateTable].sort((a, b) => a.age - b.age)
  // 完全符合
  const exact = sorted.find(r => r.age === age)
  if (exact) return exact.rate_per_10k
  // 超出範圍
  if (age < sorted[0].age) return sorted[0].rate_per_10k
  if (age > sorted[sorted.length - 1].age) return sorted[sorted.length - 1].rate_per_10k
  // 線性插值
  for (let i = 0; i < sorted.length - 1; i++) {
    if (age >= sorted[i].age && age <= sorted[i + 1].age) {
      const t = (age - sorted[i].age) / (sorted[i + 1].age - sorted[i].age)
      return sorted[i].rate_per_10k + t * (sorted[i + 1].rate_per_10k - sorted[i].rate_per_10k)
    }
  }
  return null
}

// ── 保費成長推算 ───────────────────────────────────────────────────────────────
// rateTables: { "公司｜商品名": [{age, rate_per_10k, period}, ...] }
// 優先用費率表；無費率表則退回生命表估算

// 依費率表計算某年齡的實際年繳保費
// - 計劃型（period='計劃X'）：rate_per_10k 本身就是年繳金額
// - 一般型：coverage_amount / 10000 × rate_per_10k
// - coverage 未知：以掃描保費為基，依費率比例推算
function calcPremiumFromRate(p, rateTable, age, currentAge) {
  const rate = interpolateRate(rateTable, age)
  if (rate == null) return null
  const period = rateTable[0]?.period || ''
  if (period.startsWith('計劃')) {
    return rate  // 計劃型費率即年繳額
  }
  if (p.coverage_amount > 0) {
    return (p.coverage_amount / 10000) * rate  // 保額 × 費率/萬
  }
  // fallback：以當前費率為基，比例推算
  const rateNow = interpolateRate(rateTable, currentAge)
  if (rateNow && rateNow > 0) {
    return p.annual_premium * (rate / rateNow)
  }
  return p.annual_premium
}

function projectPremiums(policies, currentAge, gender, client, rateTables = {}) {
  const natural = policies.filter(p => p.premium_type === '自然保費')
  const level   = policies.filter(p => p.premium_type === '平準保費')

  const points = []
  for (let age = currentAge; age <= 80; age += 5) {
    let naturalAmt = 0

    for (const p of natural) {
      if (!p.is_lifetime && p.coverage_end_age < age) continue

      const key = `${p.company}｜${p.product_name}`
      const rateTable = rateTables[key]

      if (rateTable && rateTable.length > 0) {
        // ── 方法一：費率表直接算（出生年月日→年齡→費率→保費）──
        const premium = calcPremiumFromRate(p, rateTable, age, currentAge)
        naturalAmt += premium != null ? Math.max(0, premium) : p.annual_premium
      } else {
        // ── 方法二：無費率表→生命表估算 ──
        const startAge = getPolicyStartAge(p, client) ?? currentAge
        const qxStart  = getQx(startAge, gender)
        if (qxStart > 0) {
          naturalAmt += p.annual_premium * (getQx(age, gender) / qxStart)
        } else {
          naturalAmt += p.annual_premium
        }
      }
    }

    const levelAmt = level
      .filter(p => p.is_lifetime || p.coverage_end_age >= age)
      .reduce((s, p) => s + p.annual_premium, 0)

    points.push({ age, natural: Math.round(naturalAmt), level: Math.round(levelAmt) })
  }
  return points
}

// ── 格式化輔助 ────────────────────────────────────────────────────────────────

const fmt = (n) => n >= 10000 ? `${(n / 10000).toFixed(0)}萬` : n.toLocaleString()
const fmtM = (n) => n >= 10000 ? `${(n / 10000).toFixed(0)}萬` : n > 0 ? n.toLocaleString() : '0'

// ── 小格子元件 ────────────────────────────────────────────────────────────────

const Row = ({ label, value, unit = '元' }) => (
  <div className="flex items-baseline justify-between gap-2">
    <span className="text-xs text-gray-500 shrink-0">{label}</span>
    <span className="font-bold text-gray-800 tabular-nums">{value}</span>
    <span className="text-xs text-gray-400 shrink-0">{unit}</span>
  </div>
)

// ── 缺口分析：狀態樣式 ────────────────────────────────────────────────────────

const STATUS = {
  '足夠':     { bg: 'bg-green-50',  border: 'border-green-200',  badge: 'bg-green-500',  icon: '✅' },
  '偏低':     { bg: 'bg-yellow-50', border: 'border-yellow-200', badge: 'bg-yellow-500', icon: '⚠️' },
  '嚴重不足': { bg: 'bg-red-50',    border: 'border-red-200',    badge: 'bg-red-500',    icon: '❌' },
}

// ── 固定基準值（依台灣醫療水準，無需 AI 呼叫）────────────────────────────────

const BENCHMARKS = [
  { key: 'disease_hosp',       label: '疾病住院日額',      unit: '元/日',  min: 3000,    ideal: 5000,
    get: c => c.diseaseHospLifetime + c.diseaseHospNonLifetime },
  { key: 'accident_hosp',      label: '意外住院日額',      unit: '元/日',  min: 3000,    ideal: 5000,
    get: c => c.accidentHospDaily },
  { key: 'medical_reimburse',  label: '醫療實支實付',      unit: '元/次',  min: 200000,  ideal: 300000,
    get: c => c.medicalReimburseQuasi + c.medicalReimburseNon },
  { key: 'inpatient_surgery',  label: '住院手術費',        unit: '元/次',  min: 150000,  ideal: 160000,
    rangeNote: (current) => current > 0
      ? `手術費依等級分級，依客戶條款換算：最低約 ${Math.round(current / 48).toLocaleString()} 元，最高 ${current.toLocaleString()} 元/次`
      : '手術費依等級分級，詳見條款手術等級表',
    get: c => c.inpatientSurgeryLifetime + c.inpatientSurgeryNonLifetime },
  { key: 'outpatient_surgery', label: '門診手術費',        unit: '元/次',  min: 30000,   ideal: 50000,
    get: c => c.outpatientSurgeryLifetime + c.outpatientSurgeryNonLifetime },
  { key: 'cancer_first',       label: '初次罹癌一次金',    unit: '元',     min: 500000,  ideal: 1000000,
    get: c => c.cancerFirst },
  { key: 'critical_illness',   label: '重大傷病/特定傷病', unit: '元',     min: 500000,  ideal: 1000000,
    get: c => c.criticalIllness },
  { key: 'disability_monthly', label: '失能月給付',        unit: '元/月',  min: 30000,   ideal: 50000,
    get: c => c.disabilityMonthly },
  { key: 'long_care_monthly',  label: '長照月給付',        unit: '元/月',  min: 30000,   ideal: 50000,
    get: c => c.longCareMonthly },
  { key: 'accident_death',     label: '意外身故保障',      unit: '元',     min: 2000000, ideal: 5000000,
    get: c => c.accidentDeath },
  { key: 'life',               label: '壽險保障',          unit: '元',     min: 3000000, ideal: 10000000,
    get: c => c.lifeTraditional },
]

// ── 保障檢視主體 ──────────────────────────────────────────────────────────────

function CoverageView({ policies, client, onEnriched }) {
  const currentAge = getAge(client)
  const [rateTables, setRateTables] = useState({})
  const [rateLoading, setRateLoading] = useState(false)
  const [rateSources, setRateSources] = useState({})
  const [enrichedPolicies, setEnrichedPolicies] = useState(policies)
  const [enrichLoading, setEnrichLoading] = useState(false)
  const [enrichDone, setEnrichDone] = useState(false)
  const [activeTab, setActiveTab] = useState('coverage') // 'coverage' | 'chart' | 'policies'
  // 區塊標記：key → 0(正常) 1(黃/注意) 2(紅/不足)
  const [highlights, setHighlights] = useState({})

  const cycleHighlight = (key) =>
    setHighlights(prev => ({ ...prev, [key]: ((prev[key] || 0) + 1) % 3 }))

  const hl = (key, base = '') => {
    const lvl = highlights[key] || 0
    if (lvl === 1) return base + ' ring-2 ring-yellow-400 bg-yellow-50 cursor-pointer'
    if (lvl === 2) return base + ' ring-2 ring-red-400 bg-red-50 cursor-pointer'
    return base + ' cursor-pointer hover:ring-1 hover:ring-gray-300'
  }

  const handleEnrich = () => {
    if (enrichLoading || enrichDone) return
    setEnrichLoading(true)
    axios.post(`${API}/enrich-policies`, { policies })
      .then(res => {
        if (res.data.policies && res.data.policies.length > 0) {
          setEnrichedPolicies(res.data.policies)
          onEnriched?.(res.data.policies)
          setEnrichDone(true)
        }
      })
      .catch(() => {})
      .finally(() => setEnrichLoading(false))
  }

  // 自動抓取自然保費附約的費率表
  useEffect(() => {
    const naturalPolicies = policies.filter(p => p.premium_type === '自然保費')
    if (naturalPolicies.length === 0) return

    setRateLoading(true)
    const gender = client.gender === 'female' ? 'female' : 'male'

    Promise.all(
      naturalPolicies.map(async p => {
        const key = `${p.company}｜${p.product_name}`
        try {
          const res = await axios.post(`${API}/rate-table`, {
            company: p.company,
            product_name: p.product_name,
            gender,
            occupation_class: p.occupation_class || null,
          })
          return { key, rates: res.data.rates || [], found: (res.data.rates || []).length > 0 }
        } catch {
          return { key, rates: [], found: false }
        }
      })
    ).then(results => {
      const tables = {}
      const sources = {}
      for (const { key, rates, found } of results) {
        tables[key]  = rates
        sources[key] = found ? 'actual' : 'estimate'
      }
      setRateTables(tables)
      setRateSources(sources)
      setRateLoading(false)
    })
  }, [policies, client.gender])

  const c = aggregate(enrichedPolicies)

  const trendPoints = projectPremiums(enrichedPolicies, currentAge, client.gender, client, rateTables)

  const chartData = {
    labels: trendPoints.map(p => `${p.age}歲`),
    datasets: [
      {
        label: Object.values(rateSources).some(s => s === 'actual') ? '自然保費（費率表）' : '自然保費（估算）',
        data: trendPoints.map(p => p.natural),
        borderColor: '#DC2626',
        backgroundColor: 'rgba(220,38,38,0.08)',
        fill: true, tension: 0.4, pointRadius: 5,
      },
      {
        label: '平準保費（固定）',
        data: trendPoints.map(p => p.level),
        borderColor: '#0B7A75',
        borderDash: [6, 4],
        backgroundColor: 'transparent',
        tension: 0.1, pointRadius: 5,
      },
    ],
  }
  const chartOptions = {
    responsive: true,
    plugins: {
      legend: { position: 'top' },
      title: { display: true, text: `保費趨勢推算（${currentAge}歲起）`, font: { size: 13 } },
      tooltip: {
        callbacks: {
          label: ctx => `${ctx.dataset.label}：${ctx.parsed.y.toLocaleString()} 元/年`,
          afterBody: (items) => {
            const idx = items[0]?.dataIndex
            if (idx == null) return []
            const p = trendPoints[idx]
            return [`合計：${(p.natural + p.level).toLocaleString()} 元/年`]
          }
        }
      }
    },
    scales: {
      y: { ticks: { callback: v => v >= 10000 ? `${(v/10000).toFixed(1)}萬` : v.toLocaleString() } }
    }
  }
  const totalCare = c.longCareMonthly + c.disabilityMonthly
  const diseaseHospTotal = c.diseaseHospLifetime + c.diseaseHospNonLifetime
  const inpatientSurgTotal = c.inpatientSurgeryLifetime + c.inpatientSurgeryNonLifetime
  const outpatientSurgTotal = c.outpatientSurgeryLifetime + c.outpatientSurgeryNonLifetime
  const specificTreatTotal = c.specificTreatmentLifetime + c.specificTreatmentNonLifetime
  const medicalReimburseTotal = c.medicalReimburseQuasi + c.medicalReimburseNon

  const TABS = [
    { key: 'coverage', label: '保障檢視' },
    { key: 'gap',      label: '缺口分析' },
    { key: 'chart',    label: '保費曲線' },
    { key: 'policies', label: '保單明細' },
  ]

  return (
    <div className="space-y-3 select-none">

      {/* ── 讀取條款按鈕 ── */}
      {enrichDone ? (
        <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-2 text-sm text-green-600 flex items-center gap-2">
          ✓ 條款已讀取，保障細項已更新
        </div>
      ) : (
        <button
          onClick={handleEnrich}
          disabled={enrichLoading}
          className="w-full bg-blue-50 border border-blue-200 rounded-xl px-4 py-2 text-sm text-blue-600 hover:bg-blue-100 transition flex items-center justify-center gap-2 disabled:opacity-70"
        >
          {enrichLoading
            ? <><span className="animate-spin inline-block">⟳</span> 正在讀取條款 PDF，提取準確保障細項...</>
            : <><span>📄</span> 讀取條款（提升精準度，每次分析約 NT$1–3）</>
          }
        </button>
      )}

      {/* ── 頁籤列 ── */}
      <div className="flex border-b border-gray-200">
        {TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex-1 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px
              ${activeTab === tab.key
                ? 'border-navy text-navy'
                : 'border-transparent text-gray-400 hover:text-gray-600'}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ══════════════ 頁籤一：保障檢視 ══════════════ */}
      {activeTab === 'coverage' && (
      <div className="space-y-3">

      {/* 標記說明 */}
      <div className="flex items-center gap-3 text-xs text-gray-400 px-1">
        <span>點擊區塊標記：</span>
        <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-yellow-200 border border-yellow-400 inline-block" /> 注意</span>
        <span className="flex items-center gap-1"><span className="w-3 h-3 rounded bg-red-200 border border-red-400 inline-block" /> 不足</span>
        <span className="text-gray-300">（再點一次還原）</span>
      </div>

      {/* ── 頂部：失能長照 + 壽險 ── */}
      <div className="grid grid-cols-3 gap-3">

        {/* 重大疾病 */}
        <div onClick={() => cycleHighlight('critical')}
          className={`bg-white border rounded-xl p-3 space-y-1.5 transition ${hl('critical')}`}>
          <div className="text-xs font-semibold text-gray-500 mb-1">重大疾病</div>
          <Row label="重大疾病/特定傷病" value={fmtM(c.criticalIllness)} />
          <Row label="初次罹癌" value={fmtM(c.cancerFirst)} />
          <div className="border-t pt-1.5 mt-1">
            <div className="text-xs font-semibold text-gray-500 mb-1">癌症</div>
            <Row label="住院" value={fmtM(c.cancerHospDaily)} unit="元/日" />
            <Row label="手術" value={fmtM(c.cancerSurgery)} unit="元/次" />
          </div>
        </div>

        {/* 失能長照 — 中心，改為淺綠色 */}
        <div onClick={() => cycleHighlight('disability')}
          className={`relative border-2 border-emerald-300 bg-emerald-50 rounded-xl p-4 flex flex-col items-center justify-center text-center transition ${hl('disability')}`}>
          <div className="text-sm font-bold text-emerald-700 mb-2">(失能)長照</div>
          <div className="text-3xl font-extrabold tabular-nums text-emerald-800">{fmtM(totalCare)}</div>
          <div className="text-sm text-emerald-600 mb-3">元/月</div>
          <div className="w-full border-t border-emerald-200 pt-2 space-y-1">
            <div className="flex justify-between text-xs text-emerald-700">
              <span>長照</span>
              <span className="font-bold">{fmtM(c.longCareMonthly)}</span>
              <span>元/月</span>
            </div>
            <div className="flex justify-between text-xs text-emerald-700">
              <span>失能</span>
              <span className="font-bold">{fmtM(c.disabilityMonthly)}</span>
              <span>元/月</span>
            </div>
          </div>
        </div>

        {/* 壽險 */}
        <div onClick={() => cycleHighlight('life')}
          className={`bg-white border rounded-xl p-3 space-y-1.5 transition ${hl('life')}`}>
          <div className="text-xs font-semibold text-gray-500 mb-1">壽險</div>
          <Row label="傳統型壽險" value={fmtM(c.lifeTraditional)} />
          <Row label="意外身故" value={fmtM(c.accidentDeath)} />
          <div className="text-xl font-extrabold text-navy text-center mt-2">
            {fmtM(c.lifeTraditional + c.accidentDeath)}
            <span className="text-sm font-normal text-gray-400 ml-1">元</span>
          </div>
          <div className="text-xs text-gray-400 text-center">年繳 {c.totalPremium.toLocaleString()} 元</div>
        </div>
      </div>

      {/* ── 中層：住院醫療（橙色區塊）── */}
      <div className="border-2 border-orange-300 rounded-xl overflow-hidden">
        <div className="bg-orange-50 px-3 py-2">
          <div className="grid grid-cols-3 gap-0">

            {/* 疾病住院 */}
            <div onClick={() => cycleHighlight('hosp')}
              className={`space-y-1 p-2 rounded-lg transition ${hl('hosp')}`}>
              <div className="text-sm font-bold text-green-700">疾病住院</div>
              <div className="text-2xl font-extrabold text-gray-800 tabular-nums">
                {fmtM(diseaseHospTotal)}
                <span className="text-xs font-normal text-gray-400 ml-1">元/日</span>
              </div>
              {c.accidentHospDaily > 0 && (
                <div className="text-xs text-gray-500">意外住院 {fmtM(c.accidentHospDaily)}/日</div>
              )}
              {c.fracture > 0 && (
                <div className="text-xs text-gray-500">骨折 {fmtM(c.fracture)} 元</div>
              )}
            </div>

            {/* 手術/處置 */}
            <div onClick={() => cycleHighlight('surgery')}
              className={`border-x border-orange-200 px-3 space-y-1.5 p-2 rounded-lg transition ${hl('surgery')}`}>
              <div className="text-sm font-bold text-green-700">手術 / 處置</div>
              <div className="space-y-1">
                <Row label="住院手術" value={fmtM(inpatientSurgTotal)} unit="元/次" />
                {inpatientSurgTotal > 0 && (
                  <div className="text-xs text-amber-600 mt-0.5 leading-tight">
                    依手術等級：約 {Math.round(inpatientSurgTotal / 48).toLocaleString()}–{inpatientSurgTotal.toLocaleString()}元
                  </div>
                )}
                <Row label="門診手術" value={fmtM(outpatientSurgTotal)} unit="元/次" />
                <Row label="特定處置" value={fmtM(specificTreatTotal)} unit="元/次" />
              </div>
            </div>

            {/* 實支實付 */}
            <div onClick={() => cycleHighlight('reimburse')}
              className={`space-y-1.5 p-2 rounded-lg transition ${hl('reimburse')}`}>
              <div className="text-sm font-bold text-green-700">實支實付</div>
              <div className="space-y-1">
                <Row label="醫療" value={fmtM(medicalReimburseTotal)} />
                {c.deductible > 0 && (
                  <div className="text-xs text-gray-400">(自負額 {fmtM(c.deductible)} 元)</div>
                )}
                <Row label="意外" value={fmtM(c.accidentReimburse)} />
              </div>
            </div>
          </div>
        </div>

        {/* 終身/非終身細項 */}
        <div className="bg-orange-50/50 border-t border-orange-200 px-3 py-2">
          <div className="grid grid-cols-5 gap-2 text-xs">
            {[
              { label: '疾病住院', lv: c.diseaseHospLifetime, nlv: c.diseaseHospNonLifetime, unit: '元' },
              { label: '住院手術', lv: c.inpatientSurgeryLifetime, nlv: c.inpatientSurgeryNonLifetime, unit: '元/次' },
              { label: '門診手術', lv: c.outpatientSurgeryLifetime, nlv: c.outpatientSurgeryNonLifetime, unit: '元/次' },
              { label: '特定處置', lv: c.specificTreatmentLifetime, nlv: c.specificTreatmentNonLifetime, unit: '元/次' },
              { label: '醫療實支', lv: c.medicalReimburseQuasi, nlv: c.medicalReimburseNon, unit: '元' },
            ].map(({ label, lv, nlv, unit }) => {
              const hkey = `sub_${label}`
              return (
                <div key={label}
                  onClick={() => cycleHighlight(hkey)}
                  className={`bg-white rounded-lg p-2 border border-orange-100 transition ${hl(hkey)}`}>
                  <div className="font-semibold text-gray-600 mb-1">{label}</div>
                  <div className="flex justify-between"><span className="text-gray-400">終身</span><span className="font-bold">{fmtM(lv)}</span></div>
                  <div className="flex justify-between"><span className="text-gray-400">非終身</span><span className="font-bold">{fmtM(nlv)}</span></div>
                  <div className="text-gray-300 text-right">{unit}</div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      </div>
      )} {/* end 保障檢視 */}

      {/* ══════════════ 頁籤：缺口分析 ══════════════ */}
      {activeTab === 'gap' && (
        <div className="space-y-3">
          <div className="text-xs text-gray-400 px-1">依台灣醫療水準訂定固定基準，自動計算，不額外收費</div>
          {BENCHMARKS.map(b => {
            const current = b.get(c)
            const status = current >= b.ideal ? '足夠' : current >= b.min ? '偏低' : '嚴重不足'
            const st = STATUS[status]
            return (
              <div key={b.key} className={`${st.bg} ${st.border} border rounded-xl p-3`}>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-sm font-semibold text-gray-800">{st.icon} {b.label}</span>
                  <span className={`${st.badge} text-white text-xs px-2 py-0.5 rounded-full`}>{status}</span>
                </div>
                <div className="flex items-baseline gap-2 mb-2">
                  <span className="text-xs text-gray-400">目前</span>
                  <span className="text-xl font-bold text-gray-800">{fmtM(current)}</span>
                  <span className="text-xs text-gray-400">{b.unit}</span>
                </div>
                <div className="flex items-center gap-5 flex-wrap">
                  <div className="flex items-baseline gap-1">
                    <span className="text-xs text-gray-400">建議最低</span>
                    <span className="text-base font-bold text-gray-800">{fmtM(b.min)}</span>
                    <span className="text-xs text-gray-500">{b.unit}</span>
                  </div>
                  <div className="flex items-baseline gap-1 opacity-60">
                    <span className="text-xs text-gray-400">建議理想</span>
                    <span className="text-sm text-gray-500">{fmtM(b.ideal)}</span>
                    <span className="text-xs text-gray-400">{b.unit}</span>
                  </div>
                </div>
                {b.rangeNote && (
                  <div className="text-xs text-amber-600 bg-amber-50 rounded px-2 py-1 mt-2">
                    {typeof b.rangeNote === 'function' ? b.rangeNote(current) : b.rangeNote}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* ══════════════ 頁籤：保費曲線 ══════════════ */}
      {activeTab === 'chart' && (
        <div className="space-y-3">
          {rateLoading && (
            <div className="text-xs text-center text-gray-400 animate-pulse">
              ⟳ 正在載入費率表資料...
            </div>
          )}
          {trendPoints.length > 0 ? (
            <div className="bg-white border rounded-xl p-4">
              <Line data={chartData} options={chartOptions} />
              <div className="mt-3 flex flex-wrap gap-2 justify-center text-xs text-gray-400">
                {Object.entries(rateSources).map(([key, src]) => (
                  <span key={key} className={`px-2 py-0.5 rounded-full ${
                    src === 'actual' ? 'bg-green-50 text-green-600' : 'bg-yellow-50 text-yellow-600'
                  }`}>
                    {src === 'actual' ? '✓' : '≈'} {key.split('｜')[1] || key}
                  </span>
                ))}
              </div>
              <p className="text-xs text-gray-400 mt-1 text-center">
                ✓ 費率表直接計算　≈ 生命表估算
              </p>
            </div>
          ) : (
            <div className="text-center py-8 text-gray-400 text-sm">載入中…</div>
          )}
        </div>
      )}

      {/* ══════════════ 頁籤三：保單明細 ══════════════ */}
      {activeTab === 'policies' && (
        <div className="space-y-2">
          {/* 當年度合計 */}
          {(() => {
            const total = policies.reduce((sum, p) => {
              const key = `${p.company}｜${p.product_name}`
              const rt  = rateTables[key]
              if (rt && rt.length > 0) {
                const premium = calcPremiumFromRate(p, rt, currentAge, currentAge)
                return sum + (premium != null ? Math.round(premium) : p.annual_premium)
              }
              return sum + (p.premium_type === '平準保費' ? p.annual_premium : 0)
            }, 0)
            return (
              <div className="bg-navy text-white rounded-xl px-4 py-3 flex items-center justify-between">
                <span className="text-sm font-medium">{currentAge} 歲當年度總保費</span>
                <span className="text-xl font-bold tabular-nums">{total.toLocaleString()} 元/年</span>
              </div>
            )
          })()}

          {/* 每筆保單 */}
          <div className="space-y-2">
            {policies.map((p, i) => {
              const key = `${p.company}｜${p.product_name}`
              const rt  = rateTables[key]
              const rtPremium = rt && rt.length > 0
                ? calcPremiumFromRate(p, rt, currentAge, currentAge)
                : null
              const displayPremium = rtPremium != null
                ? Math.round(rtPremium)
                : (p.premium_type === '平準保費' ? p.annual_premium : null)
              const isNatural = p.premium_type === '自然保費'

              return (
                <div key={i} className="bg-white border rounded-xl px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className={`w-2 h-2 rounded-full shrink-0 ${isNatural ? 'bg-red-400' : 'bg-teal-500'}`} />
                        <span className="text-xs text-gray-400">{p.company}</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded-full ${isNatural ? 'bg-red-50 text-red-600' : 'bg-teal-50 text-teal-600'}`}>
                          {isNatural ? '自然保費' : '平準保費'}
                        </span>
                      </div>
                      <div className="text-sm font-medium text-gray-700 truncate">{p.product_name}</div>
                      {p.coverage_amount > 0 && (
                        <div className="text-xs text-gray-400 mt-0.5">保額 {p.coverage_amount.toLocaleString()} 元</div>
                      )}
                    </div>
                    <div className="text-right shrink-0">
                      {displayPremium != null ? (
                        <>
                          <div className="text-lg font-bold text-gray-800 tabular-nums">{displayPremium.toLocaleString()}</div>
                          <div className="text-xs text-gray-400">元/年</div>
                          {rtPremium != null && (
                            <div className="text-xs text-green-600 mt-0.5">費率表計算</div>
                          )}
                        </>
                      ) : (
                        <div className="text-sm text-gray-300">費率待查</div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

    </div>
  )
}

// ── 方案推薦（AI 分析）────────────────────────────────────────────────────────

function AnalysisView({ analysis, client, onAnalyze, isAnalyzing, onDownload }) {
  if (!analysis) {
    return (
      <div className="text-center py-12 space-y-4">
        <div className="text-5xl">🔍</div>
        <p className="text-gray-600">點擊下方按鈕，讓 AI 分析保障缺口並給出建議</p>
        <button onClick={onAnalyze} disabled={isAnalyzing}
          className="bg-navy text-white px-8 py-3 rounded-xl font-medium hover:bg-navy/90 transition disabled:opacity-60">
          {isAnalyzing
            ? <span className="flex items-center gap-2"><span className="animate-spin">⟳</span>AI 分析中，約需 15 秒...</span>
            : '開始 AI 缺口分析'
          }
        </button>
      </div>
    )
  }

  const cs = analysis.coverage_summary
  const chartData = {
    labels: analysis.premium_trend.map(d => `${d.age}歲`),
    datasets: [
      { label: '自然保費（估算）', data: analysis.premium_trend.map(d => d.natural_premium),
        borderColor: '#0D2E5A', backgroundColor: 'rgba(13,46,90,0.1)', fill: true, tension: 0.3, pointRadius: 4 },
      { label: '平準保費（固定）', data: analysis.premium_trend.map(d => d.level_premium),
        borderColor: '#0B7A75', borderDash: [6, 4], backgroundColor: 'transparent', tension: 0.3, pointRadius: 4 },
    ],
  }
  const chartOptions = {
    responsive: true,
    plugins: { legend: { position: 'top' },
      tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toLocaleString()} 元` } } },
    scales: { y: { ticks: { callback: v => v >= 10000 ? `${(v / 10000).toFixed(1)}萬` : v.toLocaleString() } } },
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={onDownload}
          className="bg-teal text-white px-4 py-2 rounded-lg text-sm hover:bg-teal/90 transition">
          ⬇ 下載 PPTX 報告
        </button>
      </div>

      {/* 缺口分析 */}
      <div className="grid grid-cols-1 gap-3">
        {analysis.gap_analysis.map((g, i) => {
          const st = STATUS[g.status] || STATUS['足夠']
          return (
            <div key={i} className={`${st.bg} ${st.border} border rounded-xl p-4`}>
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span>{st.icon}</span>
                  <span className="font-semibold text-gray-800">{g.category}</span>
                </div>
                <span className={`${st.badge} text-white text-xs px-2 py-0.5 rounded-full`}>{g.status}</span>
              </div>
              <p className="text-sm text-gray-600">{g.description}</p>
              {g.recommended_amount > 0 && (
                <p className="text-xs text-gray-400 mt-1">
                  現有 {(g.current_amount / 10000).toFixed(0)} 萬 → 建議 {(g.recommended_amount / 10000).toFixed(0)} 萬
                </p>
              )}
            </div>
          )
        })}
      </div>

      {/* 保費趨勢 */}
      <div className="bg-white border rounded-xl p-4">
        <Line data={chartData} options={chartOptions} />
      </div>

      {/* 建議清單 */}
      <div className="bg-white border rounded-xl p-4">
        <h3 className="font-semibold text-navy mb-3">優先補強建議</h3>
        <div className="space-y-3">
          {analysis.recommendations.map((r, i) => (
            <div key={i} className="flex gap-3">
              <span className="w-6 h-6 bg-navy text-white rounded-full flex items-center justify-center text-xs shrink-0 font-bold">
                {r.priority}
              </span>
              <div>
                <p className="text-sm font-medium text-gray-800">{r.category}</p>
                <p className="text-xs text-gray-500">{r.description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── 主元件 ────────────────────────────────────────────────────────────────────

export default function CoverageReviewPage({
  client, policies, analysis, isAnalyzing,
  onAnalyze, onDownload, onBack, onReset,
  onSave, onEnriched,
}) {
  const [tab, setTab] = useState('coverage')
  const [saving, setSaving] = useState(false)
  const coverageRef = useRef(null)

  const handleSaveImage = async () => {
    const el = coverageRef.current
    if (!el) return
    setSaving(true)
    try {
      const canvas = await html2canvas(el, {
        backgroundColor: '#f9fafb',
        scale: 2,
        useCORS: true,
        logging: false,
      })
      const url = canvas.toDataURL('image/png')
      const a = document.createElement('a')
      a.href = url
      a.download = `保障總覽_${client.name}.png`
      a.click()
    } finally {
      setSaving(false)
    }
  }

  const handlePrint = () => window.print()

  return (
    <div className="max-w-4xl mx-auto">
      {/* ── 操作列（列印時隱藏）── */}
      <div className="no-print flex gap-2 mb-4 items-center flex-wrap">
        <button onClick={onBack}
          className="px-4 py-2 border rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition">
          ← 修改保單
        </button>
        <h2 className="text-xl font-bold text-navy flex-1">
          {client.name} 的保障總覽
        </h2>
        {onSave && (
          <button onClick={onSave}
            className="px-3 py-2 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700 transition flex items-center gap-1">
            💾 儲存紀錄
          </button>
        )}
        <button onClick={handleSaveImage} disabled={saving}
          className="px-3 py-2 bg-teal text-white rounded-lg text-sm hover:bg-teal/90 transition disabled:opacity-60 flex items-center gap-1">
          {saving ? <span className="animate-spin inline-block">⟳</span> : '⬇'} 存圖
        </button>
        <button onClick={handlePrint}
          className="px-3 py-2 bg-navy text-white rounded-lg text-sm hover:bg-navy/90 transition flex items-center gap-1">
          🖨 列印
        </button>
        <button onClick={onReset}
          className="px-4 py-2 border rounded-lg text-sm text-gray-500 hover:bg-gray-50 transition">
          重新開始
        </button>
      </div>

      {/* ── 列印時才顯示的標題 ── */}
      <div className="print-only">
        <h1 className="text-2xl font-bold text-gray-800 mb-1">{client.name} 的保障總覽</h1>
        <p className="text-sm text-gray-400 mb-4">分析日期：{new Date().toLocaleDateString('zh-TW')}</p>
      </div>

      {/* ── Tabs（列印時隱藏）── */}
      <div className="no-print flex border-b mb-4">
        {[
          { key: 'coverage', label: '📊 保障檢視' },
          { key: 'analysis', label: `🔍 方案推薦${analysis ? '' : ' (未分析)'}` },
        ].map(({ key, label }) => (
          <button key={key} onClick={() => setTab(key)}
            className={`px-5 py-2.5 text-sm font-medium border-b-2 transition ${
              tab === key
                ? 'border-teal text-teal'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {/* ── 保障檢視（存圖範圍）── */}
      {tab === 'coverage' && (
        <div ref={coverageRef} className="bg-gray-50 p-2 rounded-xl">
          <CoverageView policies={policies} client={client} onEnriched={onEnriched} />
        </div>
      )}

      {/* ── 列印時強制顯示保障檢視 ── */}
      <div className="print-only">
        <CoverageView policies={policies} client={client} />
      </div>

      {tab === 'analysis' && (
        <div className="no-print">
          <AnalysisView
            analysis={analysis}
            client={client}
            onAnalyze={onAnalyze}
            isAnalyzing={isAnalyzing}
            onDownload={onDownload}
          />
        </div>
      )}
    </div>
  )
}
