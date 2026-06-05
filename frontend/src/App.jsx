import { useState, useEffect } from 'react'
import axios from 'axios'
import AdvisorSetup from './components/AdvisorSetup'
import ClientPage from './pages/ClientPage'
import PoliciesPage from './pages/PoliciesPage'
import ResultsPage from './pages/ResultsPage'
import LoginPage from './pages/LoginPage'
import AdminPage from './pages/AdminPage'

const API = import.meta.env.VITE_API_URL ?? ''

const DEFAULT_CLIENT = {
  name: '', birth_date: '', insurance_age: '', gender: 'male', occupation_class: 1, monthly_income: 0
}

const STEPS = ['客戶資料', '現有保單', '分析結果']

export default function App() {
  const [authToken, setAuthToken] = useState(null)
  const [authUser, setAuthUser] = useState(null)
  const [showAdmin, setShowAdmin] = useState(false)
  const [step, setStep] = useState(0)
  const [showSetup, setShowSetup] = useState(false)
  const [advisor, setAdvisor] = useState(null)
  const [client, setClient] = useState(DEFAULT_CLIENT)
  const [policies, setPolicies] = useState([])
  const [analysis, setAnalysis] = useState(null)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    const token = localStorage.getItem('authToken')
    const user = localStorage.getItem('authUser')
    if (token && user) {
      setAuthToken(token)
      setAuthUser(JSON.parse(user))
      axios.defaults.headers.common['Authorization'] = `Bearer ${token}`
    }
    const savedAdvisor = localStorage.getItem('advisorInfo')
    if (savedAdvisor) setAdvisor(JSON.parse(savedAdvisor))
  }, [])

  const handleLogin = (data) => {
    const user = { username: data.username, display_name: data.display_name, is_admin: data.is_admin }
    localStorage.setItem('authToken', data.token)
    localStorage.setItem('authUser', JSON.stringify(user))
    axios.defaults.headers.common['Authorization'] = `Bearer ${data.token}`
    setAuthToken(data.token)
    setAuthUser(user)
    if (!localStorage.getItem('advisorInfo')) setShowSetup(true)
  }

  const handleLogout = () => {
    localStorage.removeItem('authToken')
    localStorage.removeItem('authUser')
    delete axios.defaults.headers.common['Authorization']
    setAuthToken(null)
    setAuthUser(null)
    setShowAdmin(false)
  }

  const saveAdvisor = (info) => {
    localStorage.setItem('advisorInfo', JSON.stringify(info))
    setAdvisor(info)
    setShowSetup(false)
  }

  const handleAnalyze = async () => {
    if (!advisor) { setShowSetup(true); return }
    setIsAnalyzing(true)
    setError(null)
    try {
      const res = await axios.post(`${API}/analyze`, { client, policies, advisor })
      setAnalysis(res.data)
      setStep(2)
    } catch (e) {
      if (e.response?.status === 401) { handleLogout(); return }
      setError(e.response?.data?.detail || '分析失敗，請確認後端服務已啟動（port 8000）')
    } finally {
      setIsAnalyzing(false)
    }
  }

  const handleDownload = async () => {
    try {
      const res = await axios.post(
        `${API}/download-pptx`,
        { client, policies, advisor, analysis },
        { responseType: 'blob' }
      )
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `保障分析_${client.name}.pptx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert('下載失敗：' + (e.message || '未知錯誤'))
    }
  }

  const handleReset = () => {
    setStep(0)
    setAnalysis(null)
    setClient(DEFAULT_CLIENT)
    setPolicies([])
    setError(null)
  }

  if (!authToken) return <LoginPage onLogin={handleLogin} />
  if (showAdmin) return <AdminPage onBack={() => setShowAdmin(false)} />

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-navy text-white shadow-md">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-teal rounded-full flex items-center justify-center font-bold text-sm">保</div>
            <span className="font-bold">保障缺口分析工具</span>
          </div>

          <div className="flex items-center gap-1">
            {STEPS.map((s, i) => (
              <div key={i} className="flex items-center">
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold transition-colors ${
                  i < step  ? 'bg-green-500 text-white' :
                  i === step ? 'bg-teal text-white' :
                  'bg-white/20 text-white/60'
                }`}>
                  {i < step ? '✓' : i + 1}
                </div>
                <span className={`ml-1 text-xs hidden sm:inline ${i === step ? 'text-teal font-medium' : 'text-white/50'}`}>{s}</span>
                {i < STEPS.length - 1 && <span className="mx-2 text-white/30">›</span>}
              </div>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-white/60 hidden sm:inline">
              {authUser?.display_name || authUser?.username}
            </span>
            {authUser?.is_admin && (
              <button onClick={() => setShowAdmin(true)}
                className="text-sm bg-white/10 hover:bg-white/20 px-3 py-1.5 rounded-lg transition">
                後台
              </button>
            )}
            <button onClick={() => setShowSetup(true)}
              className="text-sm bg-white/10 hover:bg-white/20 px-3 py-1.5 rounded-lg transition">
              ⚙ 設定
            </button>
            <button onClick={handleLogout}
              className="text-sm bg-white/10 hover:bg-white/20 px-3 py-1.5 rounded-lg transition">
              登出
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6">
        {step === 0 && (
          <ClientPage client={client} setClient={setClient} onNext={() => setStep(1)} />
        )}
        {step === 1 && (
          <PoliciesPage
            policies={policies} setPolicies={setPolicies}
            onBack={() => setStep(0)}
            onAnalyze={handleAnalyze}
            isAnalyzing={isAnalyzing}
            error={error}
          />
        )}
        {step === 2 && analysis && (
          <ResultsPage
            client={client} analysis={analysis}
            onDownload={handleDownload}
            onReset={handleReset}
            onBack={() => setStep(1)}
          />
        )}
      </main>

      {showSetup && (
        <AdvisorSetup
          current={advisor}
          onSave={saveAdvisor}
          onClose={advisor ? () => setShowSetup(false) : null}
        />
      )}
    </div>
  )
}
