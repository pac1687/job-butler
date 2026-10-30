# Technical Specification: Hybrid Cloud-Edge Job Intelligence Engine

## 1. System Topology

[Public Web / Vercel] Next.js 14+ (App Router)
       |
       v (Connection-Pooled TLS)
[Managed Cloud DB] Neon PostgreSQL 16+ <---> [Cloudflare R2] (Private PDF Blobs + Presigned Access)
       ^
       | (Egress TLS / Distributed Lease / Queue Polling)
[Local Workstations (Mac / Windows / Linux)]
       |-- Native Host Runtime:
       |     `-- LM Studio Local Server (Port 1234/v1 via Apple Metal or NVIDIA CUDA)
       `-- Docker Container (job-pipeline-worker):
             |-- Pre-Flight Check & Text Cleaner (Stripping EEO/Disclosures)
             |-- Python 3.12 (JobSpy, HTTPX, OpenAI SDK, ChromaDB, Psycopg3, Boto3)
             |-- Deterministic Validator (Regex, Metric Extractor, Cosine Drift)
             `-- Typst CLI Binary with Single-Page Assertion

---

## 2. Database Schema & Data Retention (Neon PostgreSQL)

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Distributed lease to prevent multi-device race conditions
CREATE TABLE pipeline_leases (
    lock_name TEXT PRIMARY KEY,
    acquired_at TIMESTAMPTZ DEFAULT NOW(),
    locked_by TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

-- Master user resume state extracted from uploaded documents
CREATE TABLE master_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    is_active BOOLEAN DEFAULT TRUE,
    basics JSONB NOT NULL,       -- name, title, contact, links, high-level summary
    skills JSONB NOT NULL,       -- categorized lists: languages, frameworks, cloud, databases
    experience JSONB NOT NULL,   -- array of roles, verified accomplishments, and tech tags
    education JSONB NOT NULL,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- Strict guardrail configuration governing LLM synthesis
CREATE TABLE tailoring_rules (
    id SERIAL PRIMARY KEY,
    forbidden_terms JSONB NOT NULL DEFAULT '[]',   -- e.g. ["Java", "gRPC", "Go"]
    protected_metrics JSONB NOT NULL DEFAULT '[]', -- metrics that must NOT be changed
    max_bullets_per_role INT DEFAULT 4,
    allow_rephrasing BOOLEAN DEFAULT TRUE,         -- if false, uses verbatim selection only
    lock_company_names BOOLEAN DEFAULT TRUE,
    lock_dates BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- User steering configuration
CREATE TABLE job_preferences (
    id SERIAL PRIMARY KEY,
    positive_titles JSONB NOT NULL DEFAULT '["Full Stack Engineer", "Senior Software Engineer"]',
    negative_title_keywords JSONB NOT NULL DEFAULT '["Manager", "Staff", "Director", "Wordpress"]',
    natural_language_notes TEXT DEFAULT 'Focus on TypeScript, Node.js, distributed backend systems, and modern web architectures.',
    min_semantic_score NUMERIC(3, 2) DEFAULT 0.70,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Master table for scraped listings
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    is_remote BOOLEAN DEFAULT TRUE,
    url TEXT NOT NULL UNIQUE,
    content_hash CHAR(64) NOT NULL UNIQUE,
    description_text TEXT NOT NULL,
    salary_range TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_jobs_content_hash ON jobs(content_hash);

-- Enriched evaluation state, generated artifacts, and historical snapshots
CREATE TABLE evaluated_matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    semantic_score NUMERIC(3, 2) NOT NULL,
    fit_score NUMERIC(3, 1) NOT NULL,
    fit_rationale TEXT NOT NULL,
    matched_skills JSONB NOT NULL DEFAULT '[]',
    missing_skills JSONB NOT NULL DEFAULT '[]',
    resume_storage_key TEXT,         -- S3/R2 Object Key for presigned URL generation
    cover_letter_storage_key TEXT,   -- S3/R2 Object Key for presigned URL generation
    payload_snapshot JSONB NOT NULL, -- Exact JSON payload passed to Typst compiler
    status TEXT NOT NULL DEFAULT 'NEW_MATCH' CHECK (status IN ('NEW_MATCH', 'SAVED', 'APPLIED', 'ARCHIVED')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_matches_status_fit ON evaluated_matches(status, fit_score DESC);

-- Task queue for ad-hoc requests (supports multi-node execution)
CREATE TABLE job_task_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL CHECK (task_type IN ('PARSE_MASTER_RESUME', 'EVALUATE_URL', 'REGENERATE_RESUME', 'REWRITE_COVER_LETTER')),
    payload JSONB DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_task_queue_pending ON job_task_queue(status, created_at);

-- Automated 30-Day Retention Cascade Function
CREATE OR REPLACE FUNCTION purge_stale_job_records() RETURNS void AS $$
BEGIN
    DELETE FROM jobs 
    WHERE created_at < NOW() - INTERVAL '30 days'
      AND id NOT IN (
          SELECT job_id FROM evaluated_matches WHERE status IN ('SAVED', 'APPLIED')
      );
END;
$$ LANGUAGE plpgsql;
```

---

## 3. Worker Ingestion, Guardrails & Page-Budget

### 3.1 Pre-Processing Text Cleaner (worker/cleaner.py)
Incoming raw text must be stripped of standard non-functional disclosures before tokenization:
- Truncates content matching regex markers: (?i)(equal opportunity employer|benefits:|eeo statement|diversity statement|we offer:|salary range:).
- Retains only core requirements and team description to optimize LM Studio context space.

### 3.2 Pre-Flight Health Check (worker/preflight.py)
Before executing any scraping or evaluation loop:
1. Pings http://host.docker.internal:1234/v1/models via HTTP GET.
2. Asserts HTTP 200 response and validates that at least one model is active.
3. If offline, writes warning to system logs and exits cleanly with status 0 (skipping batch without error spam).

### 3.3 Page-Budget Enforced Pydantic Schemas (worker/schemas.py)
Python implementation uses Pydantic:
- TailoredBullet: String with max_length=170 representing a single concise sentence focusing on action, system, and outcome.
- TailoredExperience: Contains role_id and a list of TailoredBullet items constrained to max_items=4.

### 3.4 Deterministic Guardrail Engine (worker/validator.py)
1. Denylist Scanner: Case-insensitive word boundary regex match against all terms in tailoring_rules.forbidden_terms.
2. Metric Mutation Check: Extracts all numerical tokens (\b\d+(?:\.\d+)?%?\b). If any numeric token appears in the generated bullet that did not exist in the source bullet, validation fails.
3. Semantic Cosine Verification: Computes cosine similarity between source and generated embeddings using BAAI/bge-small-en-v1.5. If similarity is < 0.82, it indicates semantic hallucination.
4. Fallback Handling: Replaces invalid bullets with the original source bullet and logs a warning.

### 3.5 Typst Compilation & Single-Page Assertion (worker/typesetter.py)
1. Injects payload into templates/resume.typ.
2. Runs: typst compile --input data=payload.json resume.typ output.pdf
3. Validates page count via pypdf.PdfReader: len(reader.pages) must equal 1. Raises PageBudgetExceededError if page count > 1.

---

## 4. Multi-Node Distributed Leases (worker/lease.py)

To prevent multiple machines from executing scheduled batches concurrently:
```sql
INSERT INTO pipeline_leases (lock_name, locked_by, expires_at)
VALUES ('nightly_batch', %s, NOW() + INTERVAL '2 hours')
ON CONFLICT (lock_name) DO UPDATE
SET acquired_at = NOW(),
    locked_by = EXCLUDED.locked_by,
    expires_at = EXCLUDED.expires_at
WHERE pipeline_leases.expires_at < NOW();
```

If 0 rows are affected, another machine holds the active lease; the worker gracefully logs the skip and shuts down.

---

## 5. Web Application Specification (Next.js App Router)

- Authentication (auth.ts): NextAuth v5 configured with Google Provider. Rejects sign-in if email !== ALLOWED_ADMIN_EMAIL.
- Public Demo Route (app/demo/page.tsx): Unauthenticated visitors see read-only mock data with disabled mutation actions.
- Admin Dashboard (app/dashboard/page.tsx): Protected by edge middleware; queries Neon serverless driver directly.
- Secure Artifact Delivery (app/api/artifacts/[id]/route.ts): Authenticated endpoint that generates a 15-minute presigned S3/R2 GET URL using @aws-sdk/s3-request-presigner.
- Audit Snapshot Viewer: Modal component displaying the exact payload_snapshot JSON associated with any tailored match.

