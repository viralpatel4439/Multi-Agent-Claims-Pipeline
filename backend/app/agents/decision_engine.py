"""
DecisionEngine — synthesizes all agent outputs into a final ClaimDecision.
Handles graceful degradation: records failed agents, lowers confidence,
and adds manual review notes.
"""
from typing import Optional

from app.agents.base import AgentResult, AgentTimer
from app.schemas.claim import ClaimSubmissionRequest


class DecisionEngine:
    NAME = "DecisionEngine"

    async def run(
        self,
        claim: ClaimSubmissionRequest,
        extraction_results: list[AgentResult],
        compliance_result: AgentResult,
        fraud_result: AgentResult,
        failed_agents: list[str],
    ) -> AgentResult:
        timer = AgentTimer()
        timer.start()
        try:
            result = self._synthesize(
                claim, extraction_results, compliance_result, fraud_result, failed_agents
            )
            return AgentResult(
                success=True,
                data=result,
                error=None,
                agent_name=self.NAME,
                processing_time_ms=timer.elapsed_ms(),
            )
        except Exception as e:
            return AgentResult(
                success=False,
                data=None,
                error=str(e),
                agent_name=self.NAME,
                processing_time_ms=timer.elapsed_ms(),
            )

    def _synthesize(
        self,
        claim: ClaimSubmissionRequest,
        extraction_results: list[AgentResult],
        compliance_result: AgentResult,
        fraud_result: AgentResult,
        failed_agents: list[str],
    ) -> dict:

        # Base decision from compliance
        if compliance_result.success and compliance_result.data:
            comp = compliance_result.data
            decision = comp.get("decision", "MANUAL_REVIEW")
            approved_amount = comp.get("approved_amount", 0.0)
            rejection_reasons = comp.get("rejection_reasons", [])
            decision_reason = comp.get("reason_text", "")
            base_confidence = comp.get("confidence", 0.85)
            line_item_decisions = comp.get("line_item_decisions", [])
            financial_breakdown = comp.get("financial_breakdown")
            waiting_period_eligible_from = comp.get("waiting_period_eligible_from")
            compliance_trace = comp.get("trace_steps", [])
        else:
            decision = "MANUAL_REVIEW"
            approved_amount = 0.0
            rejection_reasons = ["COMPLIANCE_CHECK_FAILED"]
            decision_reason = "Policy compliance check could not be completed. Manual review required."
            base_confidence = 0.3
            line_item_decisions = []
            financial_breakdown = None
            waiting_period_eligible_from = None
            compliance_trace = []
            if compliance_result.agent_name not in failed_agents:
                failed_agents.append(compliance_result.agent_name)

        # Fraud override
        fraud_signals = []
        fraud_score = 0.0
        fraud_recommendation = "PASS"

        if fraud_result.success and fraud_result.data:
            fraud_data = fraud_result.data
            fraud_signals = fraud_data.get("signals", [])
            fraud_score = fraud_data.get("fraud_score", 0.0)
            fraud_recommendation = fraud_data.get("recommendation", "PASS")
        elif not fraud_result.success and fraud_result.agent_name not in failed_agents:
            failed_agents.append(fraud_result.agent_name)

        if fraud_recommendation == "MANUAL_REVIEW" and decision not in ("REJECTED",):
            decision = "MANUAL_REVIEW"
            if not any("fraud" in r.lower() or "manual" in r.lower() for r in rejection_reasons):
                rejection_reasons.append("FRAUD_SIGNAL_DETECTED")
            decision_reason = (
                f"Claim flagged for manual review due to fraud signals: "
                + "; ".join(s["description"] for s in fraud_signals[:3])
            )

        # Confidence penalty for failed agents
        confidence = base_confidence
        confidence -= 0.2 * len(failed_agents)
        confidence = max(0.0, min(1.0, confidence))

        # Manual review note for failed components
        manual_review_note = None
        if failed_agents:
            manual_review_note = (
                f"Manual review recommended: the following pipeline components failed during processing: "
                + ", ".join(failed_agents)
                + ". Decision was made with incomplete information."
            )
            if decision not in ("REJECTED", "MANUAL_REVIEW"):
                pass  # Keep decision but note degraded confidence

        # Build extraction trace
        extraction_trace = []
        for r in extraction_results:
            extraction_trace.append({
                "agent": r.agent_name,
                "success": r.success,
                "data": r.data,
                "error": r.error,
                "processing_time_ms": r.processing_time_ms,
            })

        trace = {
            "document_extraction": extraction_trace,
            "policy_compliance": {
                "success": compliance_result.success,
                "trace_steps": compliance_trace,
                "error": compliance_result.error,
            },
            "fraud_detection": {
                "success": fraud_result.success,
                "fraud_score": fraud_score,
                "signals": fraud_signals,
                "recommendation": fraud_recommendation,
                "error": fraud_result.error,
            },
            "final_decision": {
                "decision": decision,
                "approved_amount": approved_amount,
                "confidence_score": confidence,
                "rejection_reasons": rejection_reasons,
                "failed_components": failed_agents,
            },
        }

        return {
            "decision": decision,
            "approved_amount": approved_amount,
            "confidence_score": round(confidence, 3),
            "rejection_reasons": rejection_reasons,
            "decision_reason": decision_reason,
            "line_item_decisions": line_item_decisions,
            "financial_breakdown": financial_breakdown,
            "waiting_period_eligible_from": waiting_period_eligible_from,
            "fraud_signals": fraud_signals,
            "failed_components": failed_agents,
            "manual_review_note": manual_review_note,
            "trace": trace,
        }
