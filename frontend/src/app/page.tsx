"use client"
import { useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { fetchMembers, submitClaim, uploadDocument } from "@/lib/api"
import { AlertCircle, Plus, Trash2, Send, Upload, CheckCircle, Loader2, } from "lucide-react"

const CATEGORIES = ["CONSULTATION", "DIAGNOSTIC", "PHARMACY", "DENTAL", "VISION", "ALTERNATIVE_MEDICINE"]
const DOC_TYPES = ["PRESCRIPTION", "HOSPITAL_BILL", "PHARMACY_BILL", "LAB_REPORT", "DISCHARGE_SUMMARY", "DENTAL_REPORT"]
const QUALITIES = ["GOOD", "POOR", "UNREADABLE"]

interface DocumentEntry {
  file_id: string
  actual_type: string
  quality: string
  patient_name_on_doc: string
  content_str: string
  // file selected locally — uploaded at submit time
  selected_file: File | null
  uploaded_file_name: string | null
  file_path: string | null
  upload_error: string | null
}

function genId() {
  return `F${Math.random().toString(36).slice(2, 7).toUpperCase()}`
}

function newDoc(): DocumentEntry {
  return {
    file_id: genId(),
    actual_type: "PRESCRIPTION",
    quality: "GOOD",
    patient_name_on_doc: "",
    content_str: "",
    selected_file: null,
    uploaded_file_name: null,
    file_path: null,
    upload_error: null,
  }
}

export default function Home() {
  const router = useRouter()
  const [members, setMembers] = useState<any[]>([])
  const [membersError, setMembersError] = useState(false)
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
  const [documents, setDocuments] = useState<DocumentEntry[]>([newDoc()])
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState<any[]>([])
  const [globalError, setGlobalError] = useState("")
  const fileInputRefs = useRef<(HTMLInputElement | null)[]>([])

  useEffect(() => {
    fetchMembers()
      .then(setMembers)
      .catch(() => setMembersError(true))
  }, [])

  function addDoc() {
    setDocuments(prev => [...prev, newDoc()])
  }

  function removeDoc(idx: number) {
    setDocuments(prev => prev.filter((_, i) => i !== idx))
    fileInputRefs.current = fileInputRefs.current.filter((_, i) => i !== idx)
  }

  function updateDoc(idx: number, patch: Partial<DocumentEntry>) {
    setDocuments(prev => prev.map((d, i) => i === idx ? { ...d, ...patch } : d))
  }

  function handleFileSelect(idx: number, file: File) {
    updateDoc(idx, { selected_file: file, uploaded_file_name: file.name, file_path: null, upload_error: null })
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setErrors([])
    setGlobalError("")

    try {
      // Upload any locally-selected files now (at submit time, not at select time)
      const uploadedDocs = await Promise.all(
        documents.map(async (d, idx) => {
          if (d.selected_file && !d.file_path) {
            const result = await uploadDocument(d.selected_file)
            return { ...d, file_path: result.file_path }
          }
          return d
        })
      )

      const docs = uploadedDocs.map(d => {
        let content = null
        if (d.content_str.trim()) {
          try { content = JSON.parse(d.content_str) } catch { content = null }
        }
        return {
          file_id: d.file_id,
          file_name: d.uploaded_file_name || d.file_id,
          actual_type: d.actual_type,
          quality: d.quality,
          content,
          patient_name_on_doc: d.patient_name_on_doc || null,
          file_path: d.file_path || null,
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
        {/* Claim Details */}
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
                <option value="">
                  {membersError
                    ? "⚠ Could not load members — is backend running?"
                    : members.length === 0
                    ? "Loading members…"
                    : "Select member…"}
                </option>
                {members.map(m => (
                  <option key={m.member_id} value={m.member_id}>
                    {m.name} ({m.member_id}) — {m.relationship}
                  </option>
                ))}
              </select>
              {membersError && (
                <p className="text-xs text-red-600 mt-1">
                  Backend unreachable. Start Docker and run the seed script.
                </p>
              )}
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

        {/* Documents */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-gray-800">Documents</h2>
            <button type="button" onClick={addDoc} className="flex items-center gap-1 text-sm text-green-600 hover:text-green-700">
              <Plus className="w-4 h-4" /> Add Document
            </button>
          </div>

          {documents.map((doc, idx) => (
            <div key={doc.file_id} className="border border-gray-200 rounded-lg p-4 space-y-3">
              {/* Header row */}
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono text-gray-400">{doc.file_id}</span>
                {documents.length > 1 && (
                  <button type="button" onClick={() => removeDoc(idx)} className="text-red-400 hover:text-red-600">
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>

              {/* Type / Quality / Patient Name */}
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Doc Type</label>
                  <select
                    value={doc.actual_type}
                    onChange={e => updateDoc(idx, { actual_type: e.target.value })}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-xs focus:ring-2 focus:ring-green-500"
                  >
                    {DOC_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Quality</label>
                  <select
                    value={doc.quality}
                    onChange={e => updateDoc(idx, { quality: e.target.value })}
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
                    onChange={e => updateDoc(idx, { patient_name_on_doc: e.target.value })}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-xs focus:ring-2 focus:ring-green-500"
                    placeholder="Optional"
                  />
                </div>
              </div>

              {/* File upload */}
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Upload File (PDF / image)</label>
                <input
                  ref={el => { fileInputRefs.current[idx] = el }}
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,.webp"
                  className="hidden"
                  onChange={e => {
                    const file = e.target.files?.[0]
                    if (file) handleFileSelect(idx, file)
                    e.target.value = ""
                  }}
                />
                {doc.selected_file || doc.file_path ? (
                  <div className="flex items-center gap-2 px-3 py-2 bg-green-50 border border-green-200 rounded text-xs text-green-700">
                    <CheckCircle className="w-3.5 h-3.5 flex-shrink-0" />
                    <span className="truncate font-medium">{doc.uploaded_file_name}</span>
                    <span className="ml-1 text-green-500 text-xs">(will upload on submit)</span>
                    <button
                      type="button"
                      onClick={() => updateDoc(idx, { selected_file: null, file_path: null, uploaded_file_name: null })}
                      className="ml-auto text-green-500 hover:text-red-500 flex-shrink-0"
                    >
                      ✕
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => fileInputRefs.current[idx]?.click()}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2.5 border border-dashed border-gray-300 rounded text-xs text-gray-500 hover:border-green-400 hover:text-green-600 hover:bg-green-50 transition-colors"
                  >
                    <Upload className="w-3.5 h-3.5" /> Click to attach PDF or image
                  </button>
                )}
                {doc.upload_error && (
                  <p className="text-xs text-red-600 mt-1">{doc.upload_error}</p>
                )}
              </div>

              {/* JSON content — optional if file uploaded */}
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Content JSON{doc.file_path ? " (optional — vision model will extract from file)" : ""}
                </label>
                <textarea
                  value={doc.content_str}
                  onChange={e => updateDoc(idx, { content_str: e.target.value })}
                  rows={3}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-xs font-mono focus:ring-2 focus:ring-green-500"
                  placeholder='{"patient_name": "Rajesh Kumar", "diagnosis": "Viral Fever", "total": 1500}'
                />
              </div>
            </div>
          ))}
        </div>

        {/* Claims History */}
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
            <><Loader2 className="w-4 h-4 animate-spin" /> Uploading &amp; Submitting…</>
          ) : (
            <><Send className="w-4 h-4" /> Submit Claim</>
          )}
        </button>
      </form>
    </div>
  )
}
