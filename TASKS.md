# Implementation Tasks: Hybrid Cloud-Edge Job Intelligence Engine

## Phase 1: Cloud Infrastructure & Database Setup
- [x] 1.1 Provision a Neon PostgreSQL database and run the schema DDL (including pipeline_leases, master_profiles, tailoring_rules, and purge_stale_job_records()) from SPEC.md.
- [x] 1.2 Create a private Neon Object Storage bucket (job-artifacts) on your Neon branch and generate storage access keys (storage:read, storage:write).
- [x] 1.3 Create a Google Cloud Console OAuth 2.0 Client ID with redirect URIs:
  - http://localhost:3000/api/auth/callback/google
  - https://<your-project>.vercel.app/api/auth/callback/google
- [x] 1.4 Generate authentication secrets via openssl rand -base64 32 and construct .env.local for web and .env for the worker.

## Phase 2: Host LM Studio Setup & Container Foundation
- [x] 2.1 Configure LM Studio on the host machine:
  - Download and load primary model (qwen2.5-7b-instruct or meta-llama-3.1-8b-instruct at Q4_K_M).
  - Open Developer / Local Server tab, set Port to 1234, set context window to 8192, and enable "Serve on Local Network (0.0.0.0)".
  - Verify endpoint access at http://localhost:1234/v1/models.
- [x] 2.2 Create Dockerfile with multi-arch detection (TARGETARCH) to fetch and install the precompiled Typst binary for arm64 and amd64.
- [x] 2.3 Create docker-compose.yml defining the worker (batch) and queue-listener (persistent daemon) services with host.docker.internal host-gateway mapping and LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1.
- [x] 2.4 Verify container connectivity: build image and execute test script confirming HTTP access from inside Docker to LM Studio on http://host.docker.internal:1234/v1/models.

## Phase 3: Core Pipeline & Guardrail Implementation (Inside Docker)
- [x] 3.1 Implement pre-flight health check (worker/preflight.py) to verify LM Studio readiness before starting batch tasks.
- [x] 3.2 Implement distributed lease coordinator (worker/lease.py) in Neon to prevent multi-machine execution collisions.
- [x] 3.3 Implement text cleaning pre-processor (worker/cleaner.py) stripping EEO statements and legal boilerplate from job listings.
- [x] 3.4 Implement worker/collector.py:
  - Tier-1 direct API scrapers for Greenhouse (/v1/boards/{board}/jobs), Lever, and Ashby.
  - Tier-2 JobSpy fallback with jittered delays (2-5 seconds) and isolated exception handling.
  - SHA-256 deduplication checking against Neon jobs.content_hash.
- [x] 3.5 Implement worker/ranker.py:
  - Deterministic negative keyword pruning against negative_title_keywords.
  - ChromaDB vector similarity ranker using BAAI/bge-small-en-v1.5 against positive_titles and profile embeddings.
- [x] 3.6 Implement deterministic guardrail module (worker/validator.py):
  - Forbidden terms word boundary regex check.
  - Numerical metric entity extraction and subset comparison.
  - Cosine semantic similarity drift check (< 0.82 threshold).
  - Verbatim source bullet fallback mechanism.
- [x] 3.7 Implement worker/synthesizer.py:
  - Structured evaluation via LM Studio using the OpenAI Python SDK.
  - Nearest-neighbor extractive bullet selection from master_profiles.
  - Constrained keyword rephrasing prompt enforcing forbidden terms denylist and 170-character cap.
  - 3-paragraph evidence-based cover letter prompt.
- [x] 3.8 Create Typst typesetting templates & compiler (worker/typesetter.py):
  - templates/resume.typ binding external JSON via --input data=...
  - templates/cover_letter.typ.
  - Single-page PDF validation assertion using pypdf.
- [x] 3.9 Implement worker/publisher.py:
  - Boto3 client uploading compiled PDFs and payload_snapshot.json to private Cloudflare R2 bucket.
  - Transactional SQL commit to Neon jobs and evaluated_matches.
- [x] 3.10 Implement worker/main.py supporting --nightly execution (with lease handling and retention purge) and --listen-queue polling with FOR UPDATE SKIP LOCKED.

## Phase 4: Workstation Scheduling & Wake Automation
- [x] 4.1 Configure OS-specific schedulers:
  - macOS: Configure sudo pmset repeat wake MTWRF 02:00:00 and create ~/Library/LaunchAgents/com.user.jobpipeline.plist triggering docker compose run --rm worker.
  - Windows: Create PowerShell setup script registering a Task Scheduler job running docker compose run --rm worker at 02:00 AM.
- [x] 4.2 Test container batch execution headlessly and verify execution logs.

## Phase 5: Web Application Development (Next.js & Vercel)
- [x] 5.1 Initialize Next.js 14+ project with TypeScript, Tailwind CSS, and @neondatabase/serverless.
- [x] 5.2 Configure Auth.js (auth.ts, middleware.ts, app/api/auth/[...nextauth]/route.ts) enforcing ALLOWED_ADMIN_EMAIL.
- [x] 5.3 Build public demo landing route (app/demo/page.tsx or / fallback) rendering static mock matches for unauthenticated visitors.
- [x] 5.4 Build authenticated triage dashboard (app/dashboard/page.tsx):
  - Feed ordered by fit_score descending.
  - Skill badges, fit rationale, external link, and secure PDF view buttons.
  - Audit Snapshot Modal: view exact JSON payload used to generate that specific resume version.
  - Status mutation actions (SAVED, APPLIED, ARCHIVED).
- [x] 5.5 Build presigned URL generator (app/api/artifacts/[id]/route.ts):
  - Server-side route verifying session and generating 15-minute presigned GET URLs from Cloudflare R2.
- [x] 5.6 Build Resume & Guardrail Management screen (app/profile/page.tsx):
  - File upload component handling PDF/DOCX parsing via pdf-parse/mammoth.
  - Enqueue structured parsing task to job_task_queue.
  - Form controls for forbidden_terms denylist chips and allow_rephrasing toggle.
- [x] 5.7 Build preference management page (app/preferences/page.tsx):
  - Interactive tag inputs for positive_titles and negative_title_keywords.
  - Textarea for natural language guidance notes.
  - Server Actions persisting changes to Neon job_preferences.
- [x] 5.8 Build on-demand task queue submission:
  - URL submission modal writing to job_task_queue.
  - Visual polling indicator tracking queue resolution.

## Phase 6: Automated Testing & Verification
- [x] 6.1 Implement tests/test_cleaner.py (pytest):
  - Verify regex stripping of EEO statements, benefits packages, and disclosures.
- [x] 6.2 Implement tests/test_validator.py (pytest):
  - Test forbidden term denylist regex detection.
  - Test numerical entity mutation rejection (e.g., source has 20%, output has 35%).
  - Test fallback to verbatim bullet when cosine similarity < 0.82.
- [x] 6.3 Implement tests/test_typesetter.py (pytest):
  - Test headless CLI compilation for resume.typ and cover_letter.typ.
  - Test single-page assertion triggering error when content exceeds 1 page.
- [x] 6.4 Implement tests/test_lease.py (pytest):
  - Test database lease acquisition, renewal, and collision rejection.
- [x] 6.5 Implement Next.js route tests (Jest / React Testing Library):
  - Test edge middleware blocking non-admin Google emails.
  - Test presigned URL generation rejection for unauthenticated users.

## Phase 7: Deployment & Production Smoke Checks
- [x] 7.1 Deploy Next.js web application to Vercel with production environment variables (DATABASE_URL, AUTH_SECRET, AUTH_GOOGLE_ID, AUTH_GOOGLE_SECRET, ALLOWED_ADMIN_EMAIL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY).
- [ ] 7.2 Run end-to-end production verification:
  - Upload a baseline resume, verify parsing.
  - Trigger ad-hoc job tailoring.
  - Confirm LM Studio inference, guardrail validation, single-page Typst PDF build, and R2 presigned delivery on the live domain.
