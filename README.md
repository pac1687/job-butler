# Job Butler — Hybrid Cloud-Edge Job Intelligence Engine

An autonomous, privacy-preserving job discovery, vector scoring, and guardrail-enforced resume tailoring platform.
Decouples a public **Next.js 14+ (App Router)** web interface on Vercel from an egress-only **Dockerized Python + Typst** background worker interfacing with a host **LM Studio Local Server** (`host.docker.internal:1234/v1`).

---

## Repository Structure

```text
job_butler/
├── REQUIREMENTS.md              # Product & System Requirements (FRs & NFRs)
├── SPEC.md                      # Technical Specification & SQL Schema
├── TASKS.md                     # Implementation Roadmap & Task Checklist
├── Dockerfile                   # Multi-arch (arm64/amd64) Python 3.12 + Typst CLI image
├── docker-compose.yml           # `worker` (batch) & `queue-listener` (daemon) services (2.5GB cap)
├── requirements.txt             # Worker & pytest dependencies
├── db/
│   ├── schema.sql               # Neon PostgreSQL 16+ schema DDL & 30-day retention function
│   └── seed.sql                 # Initial tailoring rules, preferences, & sample master profile
├── templates/
│   ├── resume.typ               # Single-page Typst resume template (`--input data=...`)
│   └── cover_letter.typ         # Single-page Typst evidence-based cover letter template
├── worker/
│   ├── config.py                # Environment & runtime constants
│   ├── schemas.py               # Pydantic schemas (170-char bullet cap, max 4 bullets/role)
│   ├── preflight.py             # Host LM Studio `/v1/models` readiness probe
│   ├── lease.py                 # Distributed PostgreSQL lease coordinator & retention purge
│   ├── cleaner.py               # Boilerplate/EEO regex truncator & SHA-256 content hasher
│   ├── collector.py             # Tier-1 ATS (Greenhouse/Lever/Ashby) + Tier-2 JobSpy fallback
│   ├── ranker.py                # Negative title regex pruning + BAAI/bge-small-en-v1.5 ranker
│   ├── validator.py             # Deterministic guardrail gate (denylist, metrics, cosine >= 0.82)
│   ├── synthesizer.py           # Constrained LM Studio evaluation, tailoring, & cover letter
│   ├── typesetter.py            # Typst compiler & pypdf single-page assertion
│   ├── publisher.py             # Cloudflare R2 uploader & Neon transactional persistence
│   └── main.py                  # CLI entrypoint (`--nightly` and `--listen-queue`)
├── tests/                       # Pytest suite for cleaner, validator, typesetter, lease, ranker
├── scripts/
│   ├── macos/                   # `pmset` wake schedule & `LaunchAgent` plist
│   └── windows/                 # PowerShell Task Scheduler registration script
└── web/                         # Next.js 14+ App Router Web Application (Vercel)
    ├── src/auth.ts              # NextAuth v5 Google SSO + ALLOWED_ADMIN_EMAIL check
    ├── src/middleware.ts        # Edge middleware protecting admin & API routes
    ├── src/lib/                 # Neon serverless SQL client, R2 presigner, & demo mock data
    ├── src/components/          # Navbar, JobMatchFeed, Audit Snapshot Modal, Queue Modal
    ├── src/app/demo/            # Public read-only demo view (/demo)
    ├── src/app/dashboard/       # Authenticated triage feed & status transitions
    ├── src/app/profile/         # PDF/DOCX resume ingestion, bullet editor, & guardrails UI
    ├── src/app/preferences/     # Positive title anchors, negative blacklist, & LLM notes
    └── src/app/api/             # Auth.js handler, 15-min R2 presigned URLs, & task queue API
```

---

## Quick Start

### 1. Database Setup (Neon PostgreSQL)
Run the schema and optional seed script against your Neon database:
```bash
psql "$DATABASE_URL" -f db/schema.sql
psql "$DATABASE_URL" -f db/seed.sql
```

### 2. Host LM Studio Server
1. Open **LM Studio** and load `qwen2.5-7b-instruct` or `meta-llama-3.1-8b-instruct` (`Q4_K_M`).
2. Start the Local Server on port `1234` with context length `8192` and **Serve on Local Network** enabled.
3. Verify readiness: `curl http://localhost:1234/v1/models`.

### 3. Containerized Worker & Tests
```bash
cp .env.example .env
# Build multi-arch worker image
docker compose build

# Run automated unit tests inside container
docker compose run --rm --entrypoint pytest worker

# Run nightly batch discovery & tailoring
docker compose run --rm worker --nightly

# Start persistent on-demand queue listener daemon
docker compose up -d queue-listener
```

### 4. Web Application (Next.js)
```bash
cd web
cp .env.local.example .env.local
npm install
npm test
npm run dev
```

