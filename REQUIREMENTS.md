# Product & System Requirements: Hybrid Cloud-Edge Job Intelligence Engine

## 1. Overview
An autonomous, privacy-preserving job discovery, scoring, and resume-tailoring platform. The architecture decouples a public Next.js web application deployed to Vercel from an egress-only background worker running in a portable Docker container on local workstation hardware (macOS Apple Silicon or Windows/Linux x86).

The containerized worker interfaces with a native host-based LLM engine (LM Studio Local Server) leveraging local GPU acceleration (Apple Silicon Metal or NVIDIA CUDA). It performs automated job scraping, vector filtering, gap analysis, extractive resume tailoring with strict anti-hallucination guardrails, Typst single-page PDF compilation, and cloud synchronization (Neon PostgreSQL & Cloudflare R2).

The system is calibrated to run comfortably on a 16GB M1 Pro MacBook Pro (Docker memory capped at 2.5 GB, 7B/8B Q4_K_M model, 8192 context window limit) with multi-node active/passive failover to Windows workstations.

---

## 2. Functional Requirements

### 2.1 Web Interface (Next.js / Vercel)
- FR-1.1 Authentication & Dual-Mode Routing:
  - Google OAuth single sign-on (SSO) via Auth.js (NextAuth v5).
  - Explicit email allowlist check matching an administrative identity (ALLOWED_ADMIN_EMAIL).
  - Read-only public demo view (/demo) for unauthenticated visitors showing sanitized mock records.
- FR-1.2 Master Resume Ingestion & Editing:
  - Upload interface supporting .pdf and .docx baseline resumes.
  - Server-side text extraction (pdf-parse / mammoth) and asynchronous schema normalization via structured LLM parsing.
  - Visual editor allowing review, manual editing, reordering, and tagging of parsed experience bullets and skills.
- FR-1.3 Tailoring Guardrails & Constraint Configuration:
  - Dynamic forbidden-terms denylist (e.g., specific technologies, frameworks, or titles that must never appear).
  - Verbatim-only mode toggle: completely disables LLM rephrasing, restricting generation to semantic selection and reordering of verified source bullets.
  - Strict metric lock toggle: strictly prohibits altering numerical values, percentages, and latencies.
- FR-1.4 Job Triage & Audit Inspection:
  - Daily feed of discovered jobs sorted by fit_score descending.
  - Display company, title, compensation range, remote designation, technical alignment, and LLM-generated fit rationale.
  - Historical Snapshot Viewer: View exact payload data and bullets compiled into each specific application version.
  - State management transitions: NEW_MATCH, SAVED, APPLIED, ARCHIVED.
  - Secure artifact viewing: Dynamic generation of short-lived presigned URLs for compiled resume and cover letter PDFs stored in Cloudflare R2.
- FR-1.5 Dynamic Search & Title Tuning:
  - Interactive positive title anchors (badges) for semantic centroid matching.
  - Negative keyword blacklist (badges) for zero-cost regex pruning.
  - Free-form natural language guidance notes injected into the evaluation prompt.
  - Minimum semantic cutoff threshold slider (default 0.70).
- FR-1.6 On-Demand Task Queue:
  - Capability to submit arbitrary job posting URLs or request resume/cover letter regeneration.
  - Enqueues records into PostgreSQL consumed asynchronously by the local worker.

### 2.2 Containerized Pipeline Worker (Docker / Python / Typst)
- FR-2.1 Portability & Host LM Studio Bridging:
  - Fully containerized worker runtime running identically across macOS, Windows, and Linux via Docker Desktop / Docker Engine.
  - Multi-architecture container build supporting both arm64 (Apple Silicon) and amd64 (x86_64).
  - Native host inference bridging to LM Studio via host.docker.internal:1234/v1 to preserve direct GPU access (Metal/CUDA) without container virtualization overhead.
  - Hardware resource constraints: Calibrated for 16GB RAM machines by restricting model sizes to 7B/8B (Q4_K_M quantization) and limiting context window to 8192 tokens.
- FR-2.2 Resilient Multi-Tier Ingestion & Cleaning:
  - Pre-flight health check pinging http://host.docker.internal:1234/v1/models before initiating any scraping.
  - Tier-1 Direct ATS Endpoints: Ingestion for Greenhouse, Lever, and Ashby open board APIs with isolated fault handling.
  - Tier-2 Aggregator Fallback: Multi-board fallback using JobSpy with exponential backoff and jittered delays (2-5 seconds).
  - Pre-processing text cleaner: Truncates non-functional boilerplate (EEO statements, benefits packages, legal disclosures).
  - SHA-256 content deduplication over normalized title, company, and stripped description text.
- FR-2.3 Vector Filtering & Semantic Ranking:
  - Embed incoming descriptions using a local sentence-transformer (BAAI/bge-small-en-v1.5) stored in an in-container ChromaDB instance.
  - Compute cosine distance against both positive title anchors and master career profile vectors.
- FR-2.4 Constrained LLM Reasoning & Page-Budget Enforcement:
  - Structural evaluation via OpenAI-compatible endpoints: generate fit score (1-10), skill overlap list, gaps, and a concise 2-sentence rationale.
  - Extractive bullet tailoring: reorder and align verified master resume bullets to job keywords without fabricating new tools, frameworks, or metrics.
  - Strict length budgets: Enforce maximum character lengths (170 characters per bullet) in Pydantic schemas to ensure single-page Typst rendering.
  - Contextual 3-paragraph evidence-based cover letter drafting.
  - Constrained JSON decoding enforced via Pydantic schemas and low temperature (0.1).
- FR-2.5 Deterministic Guardrail Validation Gate:
  - Python-level validation gate auditing generated bullets before typesetting:
    1. Denylist scanner rejecting bullets containing forbidden_terms.
    2. Numerical entity verification ensuring no metric tokens exist that were absent in source bullets.
    3. Semantic drift check ensuring cosine similarity to source bullet remains above 0.82.
    4. Automatic fallback: revert individual bullets to original verbatim source text if any check fails.
- FR-2.6 Document Compilation & Single-Page Guarantee:
  - Sub-second PDF compilation using embedded Typst musl binary.
  - Automated post-compilation check: Read generated PDF metadata; reject and adjust layout if document exceeds 1 page.
  - Egress-only upload of compiled PDFs and JSON payload snapshots to Cloudflare R2 bucket.
  - Transactional persistence of job entities, match scores, and payload snapshots to Neon PostgreSQL.
- FR-2.7 Multi-Node Coordination & Storage Maintenance:
  - Distributed lease acquisition (pipeline_leases) preventing duplicate runs when multiple workstations are online.
  - Concurrency-safe queue polling using SELECT ... FOR UPDATE SKIP LOCKED allowing multi-node worker failover.
  - Automated 30-day data retention cascade purging unsaved postings from Neon.

---

## 3. Non-Functional Requirements

- NFR-1 Security: Zero inbound ports or public IP exposure on the local machine. All database and storage operations run via egress TLS. R2 document assets are protected by authenticated presigned URLs.
- NFR-2 Zero Cloud GPU Cost: All embedding and LLM reasoning run locally in LM Studio on existing host silicon. Cloud components must stay within free-tier limits (Vercel Hobby, Neon Free Postgres, Cloudflare R2 Free Tier).
- NFR-3 Hallucination Prevention: The prompt contract strictly forbids generative creation of professional experience. All bullet content must derive extractively from verified source entries and pass deterministic AST/token validation.
- NFR-4 Performance & Efficiency: Typst PDF builds must complete in under 1 second. Container memory footprint must remain under 2.5 GB.
- NFR-5 Automated Test Coverage: Core ingestion filters, text cleaners, deterministic guardrails, Typst document compilation, and API routes must achieve >= 80% branch coverage across automated unit and integration test suites.

