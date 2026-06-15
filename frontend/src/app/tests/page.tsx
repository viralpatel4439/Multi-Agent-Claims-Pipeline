"use client"
import { useState } from "react"
import { runTests } from "@/lib/api"
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  Play,
  Loader2,
  ChevronDown,
  ChevronUp,
  FlaskConical,
} from "lucide-react"

type TestResult = {
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
}

type SuiteResult = {
  total: number
  passed: number
  failed: number
  errored: number
  duration_ms: number
  results: TestResult[]
  error?: string
}

// ── Decision badge ─────────────────────────────────────────────────────────────

function DecisionBadge({ decision }: { decision: string | null }) {
  if (!decision) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
        VALIDATION FAIL
      </span>
    )
  }
  const styles: Record<string, string> = {
    APPROVED: "bg-green-100 text-green-700",
    PARTIAL: "bg-yellow-100 text-yellow-800",
    REJECTED: "bg-red-100 text-red-700",
    MANUAL_REVIEW: "bg-orange-100 text-orange-800",
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${styles[decision] ?? "bg-gray-100 text-gray-700"}`}>
      {decision}
    </span>
  )
}

// ── Status chip ────────────────────────────────────────────────────────────────

function StatusChip({ status }: { status: TestResult["status"] }) {
  if (status === "PASSED")
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-green-100 text-green-700">
        <CheckCircle className="w-3 h-3" /> PASSED
      </span>
    )
  if (status === "FAILED")
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-700">
        <XCircle className="w-3 h-3" /> FAILED
      </span>
    )
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-gray-100 text-gray-600">
      <AlertTriangle className="w-3 h-3" /> ERROR
    </span>
  )
}

// ── Confidence bar ─────────────────────────────────────────────────────────────

function ConfidenceBar({ value }: { value: number | null }) {
  if (value == null) return <span className="text-gray-400 text-xs">—</span>
  const pct = Math.round(value * 100)
  const color = value > 0.8 ? "bg-green-500" : value > 0.5 ? "bg-yellow-500" : "bg-red-500"
  return (
    <div className="flex items-center gap-2 min-w-[80px]">
      <div className="flex-1 bg-gray-200 rounded-full h-1.5">
        <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 tabular-nums w-8 text-right">{pct}%</span>
    </div>
  )
}

// ── Expandable detail panel ────────────────────────────────────────────────────

function DetailPanel({ r }: { r: TestResult }) {
  return (
    <div className="px-6 pb-5 pt-1 bg-gray-50 border-t border-gray-100 space-y-3">
      {r.failure_reason && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
          <span className="font-semibold">Failure: </span>{r.failure_reason}
        </div>
      )}

      {r.decision_reason && (
        <div className="text-sm text-gray-700">
          <span className="font-medium text-gray-900">Decision reason: </span>
          {r.decision_reason}
        </div>
      )}

      {r.issues.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
            Validation Issues
          </div>
          <div className="space-y-1">
            {r.issues.map((issue, i) => (
              <div key={i} className="flex items-start gap-2 text-sm bg-orange-50 border border-orange-100 rounded p-2">
                <span className="font-mono text-xs text-orange-700 bg-orange-100 px-1.5 py-0.5 rounded flex-shrink-0">
                  {issue.issue_type}
                </span>
                <span className="text-orange-800">{issue.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {r.rejection_reasons.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
            Rejection Reasons
          </div>
          <div className="flex flex-wrap gap-1.5">
            {r.rejection_reasons.map((rr, i) => (
              <span key={i} className="text-xs font-mono px-2 py-1 bg-red-100 text-red-700 rounded">
                {rr}
              </span>
            ))}
          </div>
        </div>
      )}

      {r.failed_components.length > 0 && (
        <div className="text-sm text-orange-700 bg-orange-50 border border-orange-200 rounded p-2">
          <span className="font-medium">Failed components: </span>
          {r.failed_components.join(", ")}
        </div>
      )}

      {r.waiting_period_eligible_from && (
        <div className="text-sm text-blue-700 bg-blue-50 border border-blue-200 rounded p-2">
          <span className="font-medium">Waiting period ends: </span>
          {r.waiting_period_eligible_from}
        </div>
      )}

      {r.expected_amount != null && (
        <div className="flex items-center gap-6 text-sm pt-1">
          <div>
            <span className="text-gray-500">Expected: </span>
            <span className="font-semibold text-gray-800">
              ₹{r.expected_amount.toLocaleString("en-IN")}
            </span>
          </div>
          <div>
            <span className="text-gray-500">Got: </span>
            <span className={`font-semibold ${
              r.actual_amount != null && Math.abs(r.actual_amount - r.expected_amount) < 1
                ? "text-green-700"
                : "text-red-700"
            }`}>
              {r.actual_amount != null ? `₹${r.actual_amount.toLocaleString("en-IN")}` : "—"}
            </span>
          </div>
        </div>
      )}

      <div className="text-xs text-gray-400 pt-0.5">Ran in {r.duration_ms} ms</div>
    </div>
  )
}

// ── Row ────────────────────────────────────────────────────────────────────────

function TestRow({ r, index }: { r: TestResult; index: number }) {
  const [open, setOpen] = useState(r.status !== "PASSED")

  return (
    <>
      <tr
        className={`border-b border-gray-100 cursor-pointer transition-colors ${
          r.status === "PASSED" ? "hover:bg-gray-50" : r.status === "FAILED" ? "bg-red-50/40 hover:bg-red-50" : "bg-orange-50/40 hover:bg-orange-50"
        }`}
        onClick={() => setOpen(o => !o)}
      >
        {/* # */}
        <td className="p-4 text-xs text-gray-400 tabular-nums w-8">{index + 1}</td>

        {/* Case ID */}
        <td className="p-4">
          <span className="font-mono text-sm font-semibold text-gray-700">{r.case_id}</span>
        </td>

        {/* Description */}
        <td className="p-4 text-sm text-gray-600 max-w-xs">
          <span className="line-clamp-2">{r.description}</span>
        </td>

        {/* Expected → Got */}
        <td className="p-4">
          <div className="flex items-center gap-1.5 flex-wrap">
            <DecisionBadge decision={r.expected_decision} />
            <span className="text-gray-300 text-xs">→</span>
            <DecisionBadge decision={r.actual_decision} />
          </div>
        </td>

        {/* Amount */}
        <td className="p-4 text-right">
          {r.expected_amount != null ? (
            <div className="text-sm">
              <div className="text-gray-500 text-xs">expect</div>
              <div className="font-medium text-gray-800">₹{r.expected_amount.toLocaleString("en-IN")}</div>
              {r.actual_amount != null && (
                <div className={`text-xs font-medium ${Math.abs(r.actual_amount - r.expected_amount) < 1 ? "text-green-600" : "text-red-600"}`}>
                  got ₹{r.actual_amount.toLocaleString("en-IN")}
                </div>
              )}
            </div>
          ) : (
            <span className="text-gray-400 text-xs">—</span>
          )}
        </td>

        {/* Confidence */}
        <td className="p-4">
          <ConfidenceBar value={r.actual_confidence} />
        </td>

        {/* Status */}
        <td className="p-4">
          <StatusChip status={r.status} />
        </td>

        {/* Expand toggle */}
        <td className="p-4 w-8">
          {open
            ? <ChevronUp className="w-4 h-4 text-gray-400" />
            : <ChevronDown className="w-4 h-4 text-gray-400" />
          }
        </td>
      </tr>

      {open && (
        <tr className={r.status !== "PASSED" ? "bg-red-50/20" : ""}>
          <td colSpan={8} className="p-0">
            <DetailPanel r={r} />
          </td>
        </tr>
      )}
    </>
  )
}

// ── Summary cards ──────────────────────────────────────────────────────────────

function SummaryCards({ suite }: { suite: SuiteResult }) {
  const allPassed = suite.passed === suite.total && suite.errored === 0

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
      <div className={`rounded-xl border p-4 ${allPassed ? "bg-green-50 border-green-200" : "bg-white border-gray-200"}`}>
        <div className="text-xs text-gray-500 mb-1">Total</div>
        <div className="text-3xl font-bold text-gray-900">{suite.total}</div>
        <div className="text-xs text-gray-400 mt-1">{(suite.duration_ms / 1000).toFixed(2)} s total</div>
      </div>

      <div className={`rounded-xl border p-4 ${suite.passed > 0 ? "bg-green-50 border-green-200" : "bg-white border-gray-200"}`}>
        <div className="text-xs text-gray-500 mb-1">Passed</div>
        <div className="text-3xl font-bold text-green-700">{suite.passed}</div>
        <div className="text-xs text-green-600 mt-1">
          {Math.round((suite.passed / suite.total) * 100)}% pass rate
        </div>
      </div>

      <div className={`rounded-xl border p-4 ${suite.failed > 0 ? "bg-red-50 border-red-200" : "bg-white border-gray-200"}`}>
        <div className="text-xs text-gray-500 mb-1">Failed</div>
        <div className={`text-3xl font-bold ${suite.failed > 0 ? "text-red-700" : "text-gray-400"}`}>{suite.failed}</div>
        {suite.failed > 0 && <div className="text-xs text-red-600 mt-1">assertion mismatch</div>}
      </div>

      <div className={`rounded-xl border p-4 ${suite.errored > 0 ? "bg-orange-50 border-orange-200" : "bg-white border-gray-200"}`}>
        <div className="text-xs text-gray-500 mb-1">Errors</div>
        <div className={`text-3xl font-bold ${suite.errored > 0 ? "text-orange-700" : "text-gray-400"}`}>{suite.errored}</div>
        {suite.errored > 0 && <div className="text-xs text-orange-600 mt-1">unexpected exceptions</div>}
      </div>
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function TestsPage() {
  const [running, setRunning] = useState(false)
  const [suite, setSuite] = useState<SuiteResult | null>(null)
  const [apiError, setApiError] = useState<string | null>(null)
  const [filter, setFilter] = useState<"ALL" | "PASSED" | "FAILED" | "ERROR">("ALL")

  async function handleRun() {
    setRunning(true)
    setApiError(null)
    setSuite(null)
    try {
      const data = await runTests()
      if (data.error) {
        setApiError(data.error)
      } else {
        setSuite(data)
        // Auto-expand failures
        setFilter("ALL")
      }
    } catch (err: any) {
      setApiError(err?.response?.data?.detail || err?.message || "Request failed")
    } finally {
      setRunning(false)
    }
  }

  const visibleResults = suite
    ? filter === "ALL"
      ? suite.results
      : suite.results.filter(r => r.status === filter)
    : []

  const allPassed = suite ? suite.passed === suite.total && suite.errored === 0 : false

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <FlaskConical className="w-6 h-6 text-green-600" />
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Test Suite</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              12 reference test cases — run entirely in-process, no Celery or DB required
            </p>
          </div>
        </div>

        <button
          onClick={handleRun}
          disabled={running}
          className="flex items-center gap-2 bg-green-600 hover:bg-green-700 disabled:opacity-60 text-white px-5 py-2.5 rounded-xl font-semibold text-sm transition-colors shadow-sm"
        >
          {running ? (
            <><Loader2 className="w-4 h-4 animate-spin" /> Running…</>
          ) : (
            <><Play className="w-4 h-4" /> Run Test Suite</>
          )}
        </button>
      </div>

      {/* API error */}
      {apiError && (
        <div className="mb-6 bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
          <span className="font-semibold">Error: </span>{apiError}
        </div>
      )}

      {/* Loading state */}
      {running && (
        <div className="flex flex-col items-center justify-center h-48 gap-3">
          <Loader2 className="w-8 h-8 animate-spin text-green-600" />
          <p className="text-sm text-gray-500">Running all 12 test cases through the agent pipeline…</p>
        </div>
      )}

      {/* Empty state */}
      {!running && !suite && !apiError && (
        <div className="bg-white rounded-xl border border-gray-200 p-16 text-center">
          <FlaskConical className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500 font-medium">No results yet</p>
          <p className="text-gray-400 text-sm mt-1">
            Click <span className="font-semibold text-green-600">Run Test Suite</span> to execute all 12 test cases
          </p>
        </div>
      )}

      {/* Results */}
      {suite && (
        <>
          {/* All-pass banner */}
          {allPassed && (
            <div className="mb-4 flex items-center gap-2 bg-green-50 border border-green-200 rounded-xl px-4 py-3">
              <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0" />
              <span className="text-green-800 font-semibold text-sm">
                All {suite.total} test cases passed in {(suite.duration_ms / 1000).toFixed(2)} s
              </span>
            </div>
          )}

          <SummaryCards suite={suite} />

          {/* Filter tabs */}
          <div className="flex items-center gap-2 mb-4">
            {(["ALL", "PASSED", "FAILED", "ERROR"] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  filter === f
                    ? "bg-green-600 text-white"
                    : "bg-white border border-gray-200 text-gray-600 hover:border-green-400"
                }`}
              >
                {f}
                {f === "ALL" && ` (${suite.total})`}
                {f === "PASSED" && ` (${suite.passed})`}
                {f === "FAILED" && ` (${suite.failed})`}
                {f === "ERROR" && ` (${suite.errored})`}
              </button>
            ))}
          </div>

          {/* Results table */}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="p-4 text-left text-xs font-medium text-gray-500 w-8">#</th>
                  <th className="p-4 text-left text-xs font-medium text-gray-500">Case ID</th>
                  <th className="p-4 text-left text-xs font-medium text-gray-500">Description</th>
                  <th className="p-4 text-left text-xs font-medium text-gray-500">Expected → Got</th>
                  <th className="p-4 text-right text-xs font-medium text-gray-500">Amount</th>
                  <th className="p-4 text-left text-xs font-medium text-gray-500">Confidence</th>
                  <th className="p-4 text-left text-xs font-medium text-gray-500">Status</th>
                  <th className="p-4 w-8"></th>
                </tr>
              </thead>
              <tbody>
                {visibleResults.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="text-center py-10 text-sm text-gray-400">
                      No {filter.toLowerCase()} results
                    </td>
                  </tr>
                ) : (
                  visibleResults.map((r, i) => (
                    <TestRow key={r.case_id} r={r} index={i} />
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Legend */}
          <div className="mt-4 flex flex-wrap gap-4 text-xs text-gray-400">
            <span>Click any row to expand/collapse details.</span>
            <span>Failed rows auto-expand on load.</span>
            <span>Runs in-process — no Ollama, no Celery, ~200 ms total.</span>
          </div>
        </>
      )}
    </div>
  )
}
