# Multi-Agent Health Insurance Claims Pipeline

## Overview

A multi-agent system that processes Indian health insurance claims end-to-end. A submitted claim passes through five specialized agents — document verification, document extraction, policy compliance, fraud detection, and decision synthesis — and produces a final decision (`APPROVED` / `PARTIAL` / `REJECTED` / `MANUAL_REVIEW`) with a full audit trace.

## Project Structure

```
multi_agent_claims_pipeline/
│
├── README.md                  # This file
├── Architecture.md            # System design, components, trade-offs
├── component_contracts.md     # Interface contracts for every component
├── eval_report.md             # Results for all 12 test cases
├── execution.md               # Setup and run instructions
├── policy_terms.json          # Policy configuration, coverage rules, member roster
├── test_cases.json            # 12 test scenarios with expected outcomes
├── sample_documents_guide.md  # Indian medical document formats and extraction guidance
├── backend/                   # FastAPI + Celery + PostgreSQL + Redis
└── frontend/                  # Next.js 14 UI
```

## Quick Start

See [execution.md](execution.md) for full setup and run instructions.

```bash
# Copy env and start all services
cp .env.example .env
docker-compose up -d

# UI
open http://localhost:3000

# API docs
open http://localhost:8000/docs
```

## Architecture

See [Architecture.md](Architecture.md) for the full system design document.

Key components:
- **DocumentVerificationAgent** — synchronous, runs in the HTTP handler before any task is queued; catches wrong document types, unreadable uploads, and patient mismatches with specific actionable error messages
- **DocumentExtractionAgent** — vision-based extraction via Ollama `qwen2.5vl:3b` for real file uploads; direct dict mapping for structured test input
- **PolicyComplianceAgent** — 10 ordered rule checks (waiting periods, exclusions, pre-auth, sub-limits, network discount, co-pay)
- **FraudDetectionAgent** — Redis-backed counters; flags same-day/monthly frequency, high value, low confidence
- **DecisionEngine** — synthesises all agent results into a final decision with confidence scoring

## Running Tests

```bash
cd backend
python3 -m venv .venv-core
source .venv-core/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/ -v
```

Expected: `29 passed`

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI (async) |
| Task queue | Celery + Redis |
| Database | PostgreSQL + pgvector |
| Vision model | Ollama `qwen2.5vl:3b` (local) |
| Embeddings | `all-MiniLM-L6-v2` (sentence-transformers) |
| Frontend | Next.js 14 |
| Containers | Docker Compose |
