"use client"
import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { fetchClaims } from "@/lib/api"
import { CheckCircle, XCircle, AlertTriangle, Clock, Plus } from "lucide-react"

function StatusBadge({ status, decision }: { status: string; decision?: string | null }) {
  const key = decision || status
  const styles: Record<string, string> = {
    APPROVED: "bg-green-100 text-green-700",
    PARTIAL: "bg-yellow-100 text-yellow-800",
    REJECTED: "bg-red-100 text-red-700",
    MANUAL_REVIEW: "bg-orange-100 text-orange-800",
    PENDING: "bg-blue-100 text-blue-700",
    PROCESSING: "bg-blue-100 text-blue-700",
  }
  const icons: Record<string, React.ReactNode> = {
    APPROVED: <CheckCircle className="w-3 h-3" />,
    PARTIAL: <AlertTriangle className="w-3 h-3" />,
    REJECTED: <XCircle className="w-3 h-3" />,
    MANUAL_REVIEW: <Clock className="w-3 h-3" />,
    PENDING: <Clock className="w-3 h-3" />,
    PROCESSING: <Clock className="w-3 h-3" />,
  }
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${styles[key] || "bg-gray-100 text-gray-700"}`}>
      {icons[key]}
      {key}
    </span>
  )
}

export default function ClaimsListPage() {
  const { data: claims, isLoading, error } = useQuery({
    queryKey: ["claims"],
    queryFn: fetchClaims,
    refetchInterval: (query) => {
      const data = query.state.data as any[] | undefined
      if (!data) return false
      const hasInFlight = data.some((c: any) => c.status === "PENDING" || c.status === "PROCESSING")
      return hasInFlight ? 3000 : false
    },
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Claims</h1>
          <p className="text-gray-500 mt-1 text-sm">
            {isLoading ? "Loading…" : `${claims?.length ?? 0} total`}
          </p>
        </div>
        <Link
          href="/"
          className="flex items-center gap-1.5 bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700"
        >
          <Plus className="w-4 h-4" /> New Claim
        </Link>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center h-48">
          <div className="animate-spin w-8 h-8 border-4 border-green-600 border-t-transparent rounded-full" />
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700 text-sm">
          Could not load claims. Is the backend running?
        </div>
      )}

      {!isLoading && !error && !claims?.length && (
        <div className="bg-white rounded-xl border border-gray-200 p-12 text-center">
          <p className="text-gray-500">No claims submitted yet.</p>
          <Link href="/" className="text-green-600 hover:underline text-sm mt-2 inline-block">
            Submit your first claim →
          </Link>
        </div>
      )}

      {claims && claims.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left p-4 font-medium text-gray-600">Claim ID</th>
                <th className="text-left p-4 font-medium text-gray-600">Member</th>
                <th className="text-left p-4 font-medium text-gray-600">Category</th>
                <th className="text-left p-4 font-medium text-gray-600">Hospital</th>
                <th className="text-right p-4 font-medium text-gray-600">Claimed</th>
                <th className="text-right p-4 font-medium text-gray-600">Approved</th>
                <th className="text-left p-4 font-medium text-gray-600">Status</th>
                <th className="text-left p-4 font-medium text-gray-600">Date</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((claim: any) => (
                <tr key={claim.claim_id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                  <td className="p-4">
                    <Link
                      href={`/claims/${claim.claim_id}`}
                      className="font-mono text-xs text-green-600 hover:underline"
                    >
                      {claim.claim_id.slice(0, 8)}…
                    </Link>
                  </td>
                  <td className="p-4 text-gray-700 font-medium">{claim.member_id}</td>
                  <td className="p-4 text-gray-600">{claim.claim_category}</td>
                  <td className="p-4 text-gray-600">{claim.hospital_name || "—"}</td>
                  <td className="p-4 text-right text-gray-700">
                    ₹{claim.claimed_amount?.toLocaleString("en-IN")}
                  </td>
                  <td className="p-4 text-right">
                    {claim.approved_amount != null ? (
                      <span className="text-green-700 font-medium">
                        ₹{claim.approved_amount?.toLocaleString("en-IN")}
                      </span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </td>
                  <td className="p-4">
                    <StatusBadge status={claim.status} decision={claim.decision} />
                  </td>
                  <td className="p-4 text-gray-500 text-xs">{claim.treatment_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
