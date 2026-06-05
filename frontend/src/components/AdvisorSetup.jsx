import { useState } from 'react'

const FIELDS = [
  { key: 'name',    label: '姓名 *',        placeholder: '王小明' },
  { key: 'company', label: '保險公司 *',    placeholder: '國泰人壽' },
  { key: 'unit',    label: '單位／通訊處',  placeholder: '新竹推展處' },
  { key: 'phone',   label: '手機號碼 *',   placeholder: '0912-345-678' },
  { key: 'line_id', label: 'LINE ID',       placeholder: 'kenzo_advisor' },
]

export default function AdvisorSetup({ current, onSave, onClose }) {
  const [form, setForm] = useState(current || {
    name: '', company: '', unit: '', phone: '', line_id: '', photo_base64: null
  })

  const handlePhoto = (e) => {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      const img = new Image()
      img.onload = () => {
        const canvas = document.createElement('canvas')
        const MAX = 200
        const ratio = Math.min(MAX / img.width, MAX / img.height, 1)
        canvas.width = img.width * ratio
        canvas.height = img.height * ratio
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height)
        setForm(f => ({ ...f, photo_base64: canvas.toDataURL('image/jpeg', 0.8) }))
      }
      img.src = ev.target.result
    }
    reader.readAsDataURL(file)
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!form.name || !form.company || !form.phone) {
      alert('請填寫姓名、保險公司、手機號碼')
      return
    }
    onSave(form)
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md max-h-[90vh] overflow-y-auto">

        <div className="bg-navy text-white px-6 py-4 rounded-t-xl flex items-center justify-between sticky top-0">
          <h2 className="text-lg font-bold">顧問資料設定</h2>
          {onClose && (
            <button onClick={onClose} className="text-gray-300 hover:text-white text-xl leading-none">✕</button>
          )}
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Photo */}
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 rounded-full bg-gray-100 border-2 border-navy/30 overflow-hidden flex items-center justify-center shrink-0">
              {form.photo_base64
                ? <img src={form.photo_base64} alt="photo" className="w-full h-full object-cover" />
                : <span className="text-3xl">👤</span>
              }
            </div>
            <div>
              <p className="text-sm font-medium text-gray-700 mb-1">大頭照（選填）</p>
              <input type="file" accept="image/*" onChange={handlePhoto}
                className="text-sm text-gray-500 file:mr-2 file:text-xs file:border file:rounded file:px-2 file:py-1" />
            </div>
          </div>

          {FIELDS.map(({ key, label, placeholder }) => (
            <div key={key}>
              <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
              <input
                type="text"
                value={form[key] || ''}
                onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                placeholder={placeholder}
                className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal"
              />
            </div>
          ))}

          <button type="submit"
            className="w-full bg-navy text-white py-3 rounded-lg font-medium hover:bg-navy/90 transition">
            儲存設定
          </button>
        </form>
      </div>
    </div>
  )
}
