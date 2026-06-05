import {
  Chart as ChartJS, CategoryScale, LinearScale,
  PointElement, LineElement, Title, Tooltip, Legend, Filler
} from 'chart.js'
import { Line } from 'react-chartjs-2'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler)

const STATUS = {
  '足夠':   { bg: 'bg-green-50',  border: 'border-green-200', badge: 'bg-green-500',  icon: '✅' },
  '偏低':   { bg: 'bg-yellow-50', border: 'border-yellow-200', badge: 'bg-yellow-500', icon: '⚠️' },
  '嚴重不足': { bg: 'bg-red-50',   border: 'border-red-200',   badge: 'bg-red-500',    icon: '❌' },
}

export default function ResultsPage({ client, analysis, onDownload, onReset, onBack }) {
  const cs = analysis.coverage_summary

  const chartData = {
    labels: analysis.premium_trend.map(d => `${d.age}歲`),
    datasets: [
      {
        label: '自然保費（估算）',
        data: analysis.premium_trend.map(d => d.natural_premium),
        borderColor: '#0D2E5A',
        backgroundColor: 'rgba(13,46,90,0.1)',
        fill: true,
        tension: 0.3,
        pointRadius: 5,
      },
      {
        label: '平準保費（固定）',
        data: analysis.premium_trend.map(d => d.level_premium),
        borderColor: '#0B7A75',
        borderDash: [6, 4],
        backgroundColor: 'transparent',
        tension: 0.3,
        pointRadius: 5,
      },
    ],
  }

  const chartOptions = {
    responsive: true,
    plugins: {
      legend: { position: 'top' },
      title: { display: true, text: '保費趨勢預測（元/年）', font: { size: 14 } },
      tooltip: {
        callbacks: {
          label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toLocaleString()} 元`
        }
      }
    },
    scales: {
      y: {
        ticks: {
          callback: v => v >= 10000 ? `${(v / 10000).toFixed(1)}萬` : v.toLocaleString()
        }
      }
    }
  }

  const summaryCards = [
    { label: '壽險保額',    value: `${(cs.life_total / 10000).toFixed(0)} 萬元` },
    { label: '醫療日額',    value: `${cs.medical_daily.toLocaleString()} 元` },
    { label: '癌症一次金',  value: `${(cs.cancer_lump_sum / 10000).toFixed(0)} 萬元` },
    { label: '失能月給付',  value: `${cs.disability_monthly.toLocaleString()} 元` },
    { label: '長照保障',    value: cs.long_care_planned ? '✅ 已規劃' : '❌ 未規劃' },
    { label: '意外保額',    value: `${(cs.accident_total / 10000).toFixed(0)} 萬元` },
    { label: '年繳保費合計', value: `${cs.total_annual_premium.toLocaleString()} 元` },
  ]

  return (
    <div className="max-w-4xl mx-auto space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-navy">{client.name} 的保障分析</h2>
        <div className="flex gap-2">
          <button onClick={onBack}
            className="px-4 py-2 border rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition">
            ← 修改保單
          </button>
          <button onClick={onReset}
            className="px-4 py-2 border rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition">
            重新分析
          </button>
          <button onClick={onDownload}
            className="px-4 py-2 bg-teal text-white rounded-lg text-sm font-medium hover:bg-teal/90 transition">
            ⬇ 下載 PPTX
          </button>
        </div>
      </div>

      {/* Coverage Summary */}
      <div className="bg-white rounded-xl shadow-sm border p-6">
        <h3 className="text-lg font-bold text-navy mb-4">保障總覽</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {summaryCards.map(({ label, value }) => (
            <div key={label} className="bg-blue-50 rounded-lg p-3">
              <p className="text-xs text-gray-500 mb-1">{label}</p>
              <p className="text-sm font-bold text-navy">{value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Premium Trend Chart */}
      <div className="bg-white rounded-xl shadow-sm border p-6">
        <Line data={chartData} options={chartOptions} />
      </div>

      {/* Gap Analysis */}
      <div className="bg-white rounded-xl shadow-sm border p-6">
        <h3 className="text-lg font-bold text-navy mb-4">缺口分析</h3>
        <div className="space-y-3">
          {analysis.gap_analysis.map((gap, i) => {
            const s = STATUS[gap.status] || STATUS['偏低']
            return (
              <div key={i} className={`border rounded-xl p-4 ${s.bg} ${s.border}`}>
                <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
                  <div className="flex items-center gap-2">
                    <span>{s.icon}</span>
                    <span className="font-semibold text-gray-800">{gap.category}</span>
                    <span className={`text-xs text-white px-2 py-0.5 rounded-full font-medium ${s.badge}`}>
                      {gap.status}
                    </span>
                  </div>
                  <div className="text-sm text-gray-600 flex gap-3">
                    <span>現有：{gap.current_amount.toLocaleString()}</span>
                    <span className="text-teal font-medium">建議：{gap.recommended_amount.toLocaleString()}</span>
                  </div>
                </div>
                <p className="text-sm text-gray-600">{gap.description}</p>
              </div>
            )
          })}
        </div>
      </div>

      {/* Recommendations */}
      <div className="bg-white rounded-xl shadow-sm border p-6">
        <h3 className="text-lg font-bold text-navy mb-4">加保建議</h3>
        <div className="space-y-3">
          {analysis.recommendations.map((rec, i) => (
            <div key={i} className="flex items-start gap-4 border rounded-xl p-4 hover:bg-gray-50 transition">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold text-white shrink-0 ${i === 0 ? 'bg-teal' : 'bg-navy'}`}>
                {rec.priority}
              </div>
              <div className="flex-1">
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  <span className="font-semibold text-navy">{rec.category}</span>
                  <span className="text-sm text-teal font-medium">
                    建議保額：{rec.recommended_amount.toLocaleString()} 元
                  </span>
                </div>
                <p className="text-sm text-gray-600">{rec.description}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Download CTA */}
      <div className="bg-navy rounded-xl p-6 text-white text-center">
        <p className="text-lg font-bold mb-1">準備好與客戶分享了嗎？</p>
        <p className="text-gray-300 text-sm mb-4">下載精美 PowerPoint 投影片，自動帶入您的顧問名片資訊</p>
        <button onClick={onDownload}
          className="bg-teal text-white px-8 py-3 rounded-lg font-medium hover:bg-teal/90 transition">
          ⬇ 下載 PPTX 投影片（6 張）
        </button>
      </div>
    </div>
  )
}
