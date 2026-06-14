"use client"
import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { fetchMembers, submitClaim, api } from "@/lib/api"
import { AlertCircle, Plus, Trash2, Send } from "lucide-react"

const CATEGORIES = ["CONSULTATION", "DIAGNOSTIC", "PHARMACY", "DENTAL", "VISION", "ALTERNATIVE_MEDICINE"]
const DOC_TYPES = ["PRESCRIPTION", "HOSPITAL_BILL", "PHARMACY_BILL", "LAB_REPORT", "DISCHARGE_SUMMARY", "DENTAL_REPORT"]
const QUALITIES = ["GOOD", "POOR", "UNREADABLE"]

interface DocumentEntry {
  file_id: string
  file_name: string
  actual_type: string
  quality: string
  content_str: string
  patient_name_on_doc: string
}

function genId() {
  return `F${Math.random().toString(36).slice(2, 7).toUpperCase()}`
}

export default function Home() {
  const router = useRouter()
  const [members, setMembers] = useState<any[]>([])
  const [form, setForm] = useState({
    member_id: "",
    policy_id: "PLUM_GHI_2024",
    claim_category: "CONSULTATION",
    treatment_date: "",
    claimed_amount: "",
    hospital_name: "",
    simulate_component_failure: false,
    ytd_claims_amount: "",
    claims_history_str: "",
  })
  const [documents, setDocuments] = useState<DocumentEntry[]>([
    { file_id: genId(), file_name: "", actual_type: "PRESCRIPTION", quality: "GOOD", content_str: "", patient_name_on_doc: "" },
    { file_id: genId(), file_name: "", actual_type: "HOSPITAL_BILL", quality: "GOOD", content_str: "", patient_name_on_doc: "" },
  ])
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState<any[]>([])
  const [globalError, setGlobalError] = useState("")

  useEffect(() => {
    fetchMembers().then(setMembers).catch(() => {})
  }, [])

  function addDoc() {
    setDocuments(prev => [...prev, { file_id: genId(), file_name: "", actual_type: "PRESCRIPTION", quality: "GOOD", content_str: "", patient_name_on_doc: "" }])
  }

  function removeDoc(idx: number) {
    setDocuments(prev => prev.filter((_, i) => i !== idx))
  }

  function updateDoc(idx: number, key: keyof DocumentEntry, val: string) {
    setDocuments(prev => prev.map((d, i) => i === idx ? { ...d, [key]: val } : d))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setErrors([])
    setGlobalError("")

    const docs = documents.map(d => {
      let content = null
      if (d.content_str.trim()) {
        try { content = JSON.parse(d.content_str) } catch { content = null }
      }
      return {
        file_id: d.file_id,
        file_name: d.file_name || d.file_id,
        actual_type: d.actual_type,
        quality: d.quality,
        content,
        patient_name_on_doc: d.patient_name_on_doc || null,
      }
    })

    const payload: any = {
      member_id: form.member_id,
      policy_id: form.policy_id,
      claim_category: form.claim_category,
      treatment_date: form.treatment_date,
      claimed_amount: parseFloat(form.claimed_amount),
      hospital_name: form.hospital_name || null,
      documents: docs,
      simulate_component_failure: form.simulate_component_failure,
    }

    if (form.ytd_claims_amount) payload.ytd_claims_amount = parseFloat(form.ytd_claims_amount)
    if (form.claims_history_str.trim()) {
      try { payload.claims_history = JSON.parse(form.claims_history_str) } catch {}
    }

    try {
      const result = await submitClaim(payload)
      router.push(`/claims/${result.claim_id}`)
    } catch (err: any) {
      if (err.response?.status === 422) {
        const detail = err.response.data?.detail
        if (detail?.issues) {
          setErrors(detail.issues)
        } else {
          setGlobalError(JSON.stringify(detail, null, 2))
        }
      } else {
        setGlobalError(err.message || "Submission failed")
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Submit a Claim</h1>
        <p className="text-gray-500 mt-1">All claims are processed by our multi-agent AI pipeline.</p>
      </div>

      {errors.length > 0 && (
        <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle className="w-5 h-5 text-red-600" />
            <span className="font-semibold text-red-800">Document Validation Failed</span>
          </div>
          {errors.map((issue, i) => (
            <div key={i} className="mt-2 text-sm text-red-700 bg-red-100 rounded p-3">
              <span className="font-medium">[{issue.issue_type}]</span> {issue.message}
            </div>
          ))}
        </div>
      )}

      {globalError && (
        <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">
          {globalError}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <h2 className="font-semibold text-gray-800">Claim Details</h2>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Member *</label>
              <select
                required
                value={form.member_id}
                onChange={e => setForm(f => ({ ...f, member_id: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent"
              >
                <option value="">Select member...</option>
                {members.map(m => (
                  <option key={m.member_id} value={m.member_id}>
                    {m.name} ({m.member_id}) — {m.relationship}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Category *</label>
              <select
                required
                value={form.claim_category}
                onChange={e => setForm(f => ({ ...f, claim_category: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent"
              >
                {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Treatment Date *</label>
              <input
                required
                type="date"
                value={form.treatment_date}
                onChange={e => setForm(f => ({ ...f, treatment_date: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Claimed Amount (₹) *</label>
              <input
                required
                type="number"
                min="1"
                step="0.01"
                value={form.claimed_amount}
                onChange={e => setForm(f => ({ ...f, claimed_amount: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500"
                placeholder="1500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Hospital Name</label>
              <input
                type="text"
                value={form.hospital_name}
                onChange={e => setForm(f => ({ ...f, hospital_name: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500"
                placeholder="Apollo Hospitals (for network discount)"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">YTD Claims Amount (₹)</label>
              <input
                type="number"
                value={form.ytd_claims_amount}
                onChange={e => setForm(f => ({ ...f, ytd_claims_amount: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-green-500"
                placeholder="Optional"
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="simulate_failure"
              checked={form.simulate_component_failure}
              onChange={e => setForm(f => ({ ...f, simulate_component_failure: e.target.checked }))}
              className="w-4 h-4 text-green-600"
            />
            <label htmlFor="simulate_failure" className="text-sm text-gray-700">
              Simulate component failure (TC011 — tests graceful degradation)
            </label>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-gray-800">Documents</h2>
            <button type="button" onClick={addDoc} className="flex items-center gap-1 text-sm text-green-600 hover:text-green-700">
              <Plus className="w-4 h-4" /> Add Document
            </button>
          </div>

          {documents.map((doc, idx) => (
            <div key={doc.file_id} className="border border-gray-200 rounded-lg p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono text-gray-400">{doc.file_id}</span>
                {documents.length > 1 && (
                  <button type="button" onClick={() => removeDoc(idx)} className="text-red-400 hover:text-red-600">
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Doc Type</label>
                  <select
                    value={doc.actual_type}
                    onChange={e => updateDoc(idx, "actual_type", e.target.value)}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-xs focus:ring-2 focus:ring-green-500"
                  >
                    {DOC_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Quality</label>
                  <select
                    value={doc.quality}
                    onChange={e => updateDoc(idx, "quality", e.target.value)}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-xs focus:ring-2 focus:ring-green-500"
                  >
                    {QUALITIES.map(q => <option key={q} value={q}>{q}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Patient Name on Doc</label>
                  <input
                    type="text"
                    value={doc.patient_name_on_doc}
                    onChange={e => updateDoc(idx, "patient_name_on_doc", e.target.value)}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-xs focus:ring-2 focus:ring-green-500"
                    placeholder="Optional"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Content (JSON) — paste structured document data for extraction
                </label>
                <textarea
                  value={doc.content_str}
                  onChange={e => updateDoc(idx, "content_str", e.target.value)}
                  rows={4}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-xs font-mono focus:ring-2 focus:ring-green-500"
                  placeholder='{"patient_name": "Rajesh Kumar", "diagnosis": "Viral Fever", "total": 1500}'
                />
              </div>
            </div>
          ))}
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="font-semibold text-gray-800 mb-3">Claims History (optional — JSON for TC009)</h2>
          <textarea
            value={form.claims_history_str}
            onChange={e => setForm(f => ({ ...f, claims_history_str: e.target.value }))}
            rows={4}
            className="w-full border border-gray-300 rounded px-3 py-2 text-xs font-mono focus:ring-2 focus:ring-green-500"
            placeholder='[{"claim_id": "CLM_0081", "date": "2024-10-30", "amount": 1200, "provider": "City Clinic A"}]'
          />
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="w-full bg-green-600 text-white py-3 rounded-xl font-semibold hover:bg-green-700 disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {submitting ? (
            <span className="animate-spin border-2 border-white border-t-transparent rounded-full w-4 h-4" />
          ) : (
            <Send className="w-4 h-4" />
          )}
          {submitting ? "Submitting..." : "Submit Claim"}
        </button>
      </form>
    </div>
  )
}
