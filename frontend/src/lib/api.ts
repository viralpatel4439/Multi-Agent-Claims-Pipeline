import axios from 'axios'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'

export const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
})

export async function uploadDocument(file: File): Promise<{ file_path: string; file_name: string }> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await axios.post(`${API_BASE}/upload`, formData)
  return res.data
}

export async function fetchMembers() {
  const res = await api.get('/members')
  return res.data
}

export async function submitClaim(claimData: any) {
  const res = await api.post('/claims', claimData)
  return res.data
}

export async function fetchClaim(claimId: string) {
  const res = await api.get(`/claims/${claimId}`)
  return res.data
}

export async function fetchClaims() {
  const res = await api.get('/claims')
  return res.data
}

export async function rerunClaim(claimId: string) {
  const res = await api.post(`/claims/${claimId}/rerun`)
  return res.data
}

export async function runTests(): Promise<{
  total: number
  passed: number
  failed: number
  errored: number
  duration_ms: number
  results: Array<{
    case_id: string
    description: string
    status: "PASSED" | "FAILED" | "ERROR"
    failure_reason: string | null
    expected_decision: string | null
    actual_decision: string | null
    expected_amount: number | null
    actual_amount: number | null
    actual_confidence: number | null
    rejection_reasons: string[]
    failed_components: string[]
    waiting_period_eligible_from: string | null
    issues: Array<{ issue_type: string; message: string }>
    decision_reason: string | null
    duration_ms: number
  }>
  error?: string
}> {
  const res = await api.get("/tests/run")
  return res.data
}

/**
 * Open a Server-Sent Events connection for a claim.
 * The backend sends the current status immediately, then the final result
 * when the pipeline completes — no polling needed.
 *
 * Returns the EventSource so the caller can close it on unmount.
 */
export function openClaimEventSource(
  claimId: string,
  onMessage: (data: any) => void,
  onError?: (e: Event) => void,
): EventSource {
  const es = new EventSource(`${API_BASE}/claims/${claimId}/events`)
  es.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data))
    } catch {
      // ignore unparseable frames (e.g. heartbeat comments)
    }
  }
  if (onError) es.onerror = onError
  return es
}
