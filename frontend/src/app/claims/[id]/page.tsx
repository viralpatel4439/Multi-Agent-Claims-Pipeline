"use client"
import { useQuery } from "@tanstack/react-query"
import { useParams, useRouter } from "next/navigation"
import { fetchClaim } from "@/lib/api"
import { CheckCircle, XCircle, AlertTriangle, Clock, ChevronDown, ChevronUp, ArrowLeft } from "lucide-react"
import { useState } from "react"

function DecisionBanner({ claim }: { claim: any }) {
  const config: Record<string, { bg: string; border: string; text: string; icon: any; label: string }> = {
    APPROVED: { bg: "bg-green-50", border: "border-green-200", text: "text-green-800", icon: CheckCircle, label: "Approved" },
    PARTIAL: { bg: "bg-yellow-50", border: "border-yellow-200", text: "text-yellow-800", icon: AlertTriangle, label: "Partially Approved" },
    REJECTED: { bg: "bg-red-50", border: "border-red-200", text: "text-red-800", icon: XCircle, label: "Rejected" },
    MANUAL_REVIEW: { bg: "bg-orange-50", border: "border-orange-200", text: "text-orange-800", icon: Clock, label: "Manual Review Required" },
    PENDING: { bg: "bg-blue-50", border: "border-blue-200", text: "text-blue-800", icon: Clock, label: "Processing..." },
    PROCESSING: { bg: "bg-blue-50", border: "border-blue-200", text: "text-blue-800", icon: Clock, label: "Processing..." },
  }
  const status = claim.decision || claim.status
  const c = config[status] || config["PENDING"]
  const Icon = c.icon

  return (
    <div className={`rounded-xl border ${c.bg} ${c.border} p-6 mb-6`}>
      <div className="flex items-center gap-3 mb-4">
        <Icon className={`w-6 h-6 ${c.text}`} />
        <h2 className={`text-xl font-bold ${c.text}`}>{c.label}</h2>
        {claim.confidence_score != null && (
          <span className="ml-auto text-sm text-gray-500">
            Confidence: {(claim.confidence_score * 100).toFixed(0)}%
          </span>
        )}
      </div>

      {claim.decision_reason && (
        <p className="text-gray-700 text-sm mb-4">{claim.decision_reason}</p>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white rounded-lg p-3 border border-gray-200">
          <div className="text-xs text-gray-500 mb-1">Claimed Amount</div>
          <div className="text-lg font-bold text-gray-900">₹{claim.claimed_amount?.toLocaleString('en-IN')}</div>
        </div>
        <div className="bg-white rounded-lg p-3 border border-gray-200">
          <div className="text-xs text-gray-500 mb-1">Approved Amount</div>
          <div className={`text-lg font-bold ${claim.approved_amount > 0 ? 'text-green-700' : 'text-red-700'}`}>
            {claim.approved_amount != null ? `₹${claim.approved_amount?.toLocaleString('en-IN')}` : "—"}
          </div>
        </div>
      </div>

      {claim.confidence_score != null && (
        <div className="mt-4">
          <div className="text-xs text-gray-500 mb-1">Confidence Score</div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className={`h-2 rounded-full ${claim.confidence_score > 0.8 ? 'bg-green-500' : claim.confidence_score > 0.5 ? 'bg-yellow-500' : 'bg-red-500'}`}
              style={{ width: `${(claim.confidence_score * 100).toFixed(0)}%` }}
            />
          </div>
        </div>
      )}

      {claim.rejection_reasons?.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {claim.rejection_reasons.map((r: string, i: number) => (
            <span key={i} className="text-xs px-2 py-1 bg-red-100 text-red-700 rounded-full font-mono">{r}</span>
          ))}
        </div>
      )}

      {claim.pipeline_errors?.failed_components?.length > 0 && (
        <div className="mt-3 text-xs text-orange-700 bg-orange-100 rounded p-2">
          ⚠ Failed components: {claim.pipeline_errors.failed_components.join(", ")}
        </div>
      )}
    </div>
  )
}

function TraceSection({ title, data, defaultOpen = false }: { title: string; data: any; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  if (!data) return null

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden mb-3">
      <button
        className="w-full flex items-center justify-between p-4 bg-gray-50 hover:bg-gray-100 text-left"
        onClick={() => setOpen(o => !o)}
      >
        <span className="font-medium text-gray-800 text-sm">{title}</span>
        {open ? <ChevronUp className="w-4 h-4 text-gray-500" /> : <ChevronDown className="w-4 h-4 text-gray-500" />}
      </button>
      {open && (
        <div className="p-4 bg-white">
          <pre className="text-xs text-gray-700 overflow-auto max-h-80 bg-gray-50 rounded p-3">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

function LineItemTable({ items }: { items: any[] }) {
  if (!items?.length) return null
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-50">
            <th className="text-left p-3 border-b border-gray-200 font-medium text-gray-600">Description</th>
            <th className="text-right p-3 border-b border-gray-200 font-medium text-gray-600">Amount</th>
            <th className="text-right p-3 border-b border-gray-200 font-medium text-gray-600">Approved</th>
            <th className="text-left p-3 border-b border-gray-200 font-medium text-gray-600">Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item: any, i: number) => (
            <tr key={i} className={item.approved ? "" : "bg-red-50"}>
              <td className="p-3 border-b border-gray-100">{item.description}</td>
              <td className="p-3 border-b border-gray-100 text-right">₹{item.amount?.toLocaleString('en-IN')}</td>
              <td className="p-3 border-b border-gray-100 text-right">₹{item.approved_amount?.toLocaleString('en-IN')}</td>
              <td className="p-3 border-b border-gray-100">
                {item.approved
                  ? <span className="text-green-600 text-xs font-medium">✓ Approved</span>
                  : <span className="text-red-600 text-xs">{item.reason || "Excluded"}</span>
                }
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FinancialBreakdown({ bd }: { bd: any }) {
  if (!bd) return null
  const rows = [
    { label: "Claimed Amount", value: bd.claimed_amount, highlight: false },
    { label: "Approved Line Items", value: bd.approved_line_items_total, highlight: false },
    bd.network_discount_applied > 0 && { label: `Network Discount (${bd.network_discount_percent}%)`, value: -bd.network_discount_applied, highlight: false },
    { label: "Amount After Discount", value: bd.amount_after_discount, highlight: false },
    bd.copay_deducted > 0 && { label: `Co-pay (${bd.copay_percent}%)`, value: -bd.copay_deducted, highlight: false },
    { label: "Final Approved Amount", value: bd.final_amount, highlight: true },
  ].filter(Boolean)

  return (
    <div className="bg-gray-50 rounded-lg p-4">
      <h3 className="font-semibold text-gray-800 text-sm mb-3">Financial Breakdown</h3>
      <div className="space-y-2">
        {rows.map((row: any, i) => (
          <div key={i} className={`flex justify-between text-sm ${row.highlight ? 'font-bold border-t pt-2' : ''}`}>
            <span className="text-gray-600">{row.label}</span>
            <span className={row.value < 0 ? "text-red-600" : "text-gray-900"}>
              {row.value < 0 ? "−" : ""}₹{Math.abs(row.value)?.toLocaleString('en-IN')}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function PolicyTraceSteps({ steps }: { steps: any[] }) {
  if (!steps?.length) return null
  return (
    <div className="space-y-2">
      {steps.map((step: any, i: number) => (
        <div key={i} className={`flex items-start gap-2 p-3 rounded-lg text-sm ${step.passed ? 'bg-green-50' : 'bg-red-50'}`}>
          <span className={`mt-0.5 flex-shrink-0 ${step.passed ? 'text-green-600' : 'text-red-600'}`}>
            {step.passed ? '✓' : '✗'}
          </span>
          <div>
            <div className={`font-medium ${step.passed ? 'text-green-800' : 'text-red-800'}`}>{step.check}</div>
            <div className="text-gray-600 text-xs mt-0.5">{step.detail}</div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function ClaimDetailPage() {
  const params = useParams()
  const router = useRouter()
  const claimId = params.id as string

  const { data: claim, isLoading, error } = useQuery({
    queryKey: ["claim", claimId],
    queryFn: () => fetchClaim(claimId),
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data || data.status === "PENDING" || data.status === "PROCESSING") return 2000
      return false
    },
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-4 border-green-600 border-t-transparent rounded-full" />
      </div>
    )
  }

  if (error || !claim) {
    return (
      <div className="text-center text-red-600 py-16">
        <XCircle className="w-12 h-12 mx-auto mb-3" />
        <p>Could not load claim. {(error as any)?.message}</p>
      </div>
    )
  }

  const trace = claim.trace || {}
  const complianceTrace = trace.policy_compliance?.trace_steps || []
  const lineItems = trace.policy_compliance?.line_item_decisions || claim.trace?.policy_compliance?.line_item_decisions || []
  const financialBreakdown = trace.policy_compliance?.financial_breakdown || null

  return (
    <div className="max-w-4xl mx-auto">
      <button onClick={() => router.push("/")} className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800 mb-6">
        <ArrowLeft className="w-4 h-4" /> Back to Submit
      </button>

      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">Claim Review</h1>
        <p className="text-xs text-gray-400 font-mono mt-1">{claimId}</p>
      </div>

      <DecisionBanner claim={claim} />

      {(claim.status === "PENDING" || claim.status === "PROCESSING") && (
        <div className="text-center text-blue-600 py-4 text-sm">
          <div className="animate-spin w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full mx-auto mb-2" />
          Processing claim... checking every 2 seconds
        </div>
      )}

      {lineItems?.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <h3 className="font-semibold text-gray-800 mb-4">Line Item Decisions</h3>
          <LineItemTable items={lineItems} />
        </div>
      )}

      {claim.trace?.policy_compliance?.financial_breakdown && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <FinancialBreakdown bd={claim.trace.policy_compliance.financial_breakdown} />
        </div>
      )}

      {complianceTrace.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <h3 className="font-semibold text-gray-800 mb-4">Policy Compliance Trace</h3>
          <PolicyTraceSteps steps={complianceTrace} />
        </div>
      )}

      {trace.fraud_detection && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <h3 className="font-semibold text-gray-800 mb-3">Fraud Detection</h3>
          <div className="flex items-center gap-4 mb-4">
            <div className="text-sm text-gray-600">
              Score: <span className="font-bold">{(trace.fraud_detection.fraud_score * 100).toFixed(0)}%</span>
            </div>
            <span className={`text-xs px-2 py-1 rounded-full font-medium ${
              trace.fraud_detection.recommendation === "PASS" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
            }`}>
              {trace.fraud_detection.recommendation}
            </span>
          </div>
          {trace.fraud_detection.signals?.length > 0 && (
            <div className="space-y-2">
              {trace.fraud_detection.signals.map((sig: any, i: number) => (
                <div key={i} className={`text-sm p-3 rounded-lg ${
                  sig.severity === "HIGH" ? "bg-red-50 text-red-700" :
                  sig.severity === "MEDIUM" ? "bg-yellow-50 text-yellow-700" :
                  "bg-gray-50 text-gray-700"
                }`}>
                  <span className="font-medium">[{sig.severity}] {sig.signal_type}:</span> {sig.description}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h3 className="font-semibold text-gray-800 mb-4">Full Pipeline Trace</h3>
        <TraceSection title="Document Extraction Results" data={trace.document_extraction} />
        <TraceSection title="Policy Compliance Data" data={trace.policy_compliance} />
        <TraceSection title="Fraud Detection Data" data={trace.fraud_detection} />
        <TraceSection title="Final Decision Data" data={trace.final_decision} />
        <TraceSection title="Raw Claim Trace (complete)" data={claim.trace} />
      </div>
    </div>
  )
}
