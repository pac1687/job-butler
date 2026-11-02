# Job Butler — Neon PostgreSQL Schema DDL
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Distributed lease to prevent multi-device race conditions
CREATE TABLE IF NOT EXISTS pipeline_leases (
    lock_name TEXT PRIMARY KEY,
    acquired_at TIMESTAMPTZ DEFAULT NOW(),
    locked_by TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

-- Master user resume state extracted from uploaded documents
CREATE TABLE IF NOT EXISTS master_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    is_active BOOLEAN DEFAULT TRUE,
    basics JSONB NOT NULL,       -- name, title, contact, links, high-level summary
    skills JSONB NOT NULL,       -- categorized lists: languages, frameworks, cloud, databases
    experience JSONB NOT NULL,   -- array of roles, verified accomplishments, and tech tags
    education JSONB NOT NULL,
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- Strict guardrail configuration governing LLM synthesis
CREATE TABLE IF NOT EXISTS tailoring_rules (
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
CREATE TABLE IF NOT EXISTS job_preferences (
    id SERIAL PRIMARY KEY,
    positive_titles JSONB NOT NULL DEFAULT '["Full Stack Engineer", "Senior Software Engineer"]',
    negative_title_keywords JSONB NOT NULL DEFAULT '["Manager", "Staff", "Director", "Wordpress"]',
    natural_language_notes TEXT DEFAULT 'Focus on TypeScript, Node.js, distributed backend systems, and modern web architectures.',
    min_semantic_score NUMERIC(3, 2) DEFAULT 0.70,
    ats_boards JSONB NOT NULL DEFAULT '{"greenhouse": ["vercel", "supabase", "cloudflare"], "lever": ["linear"], "ashby": ["openai", "ramp"]}',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Master table for scraped listings
CREATE TABLE IF NOT EXISTS jobs (
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

CREATE INDEX IF NOT EXISTS idx_jobs_content_hash ON jobs(content_hash);

-- Enriched evaluation state, generated artifacts, and historical snapshots
CREATE TABLE IF NOT EXISTS evaluated_matches (
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

CREATE INDEX IF NOT EXISTS idx_matches_status_fit ON evaluated_matches(status, fit_score DESC);

-- Task queue for ad-hoc requests (supports multi-node execution)
CREATE TABLE IF NOT EXISTS job_task_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL CHECK (task_type IN ('PARSE_MASTER_RESUME', 'EVALUATE_URL', 'REGENERATE_RESUME', 'REWRITE_COVER_LETTER')),
    payload JSONB DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_task_queue_pending ON job_task_queue(status, created_at);

-- Automated 7-Day Unapplied & 30-Day Retention Cascade Function
CREATE OR REPLACE FUNCTION purge_stale_job_records() RETURNS void AS $$
BEGIN
    -- 1. Remove NEW_MATCH, SAVED, and ARCHIVED matches older than 7 days (by posted date or discovery timestamp)
    DELETE FROM evaluated_matches m
    USING jobs j
    WHERE m.job_id = j.id
      AND m.status IN ('NEW_MATCH', 'SAVED', 'ARCHIVED')
      AND (
          m.created_at < NOW() - INTERVAL '7 days'
          OR j.created_at < NOW() - INTERVAL '7 days'
          OR (
              j.location ~ 'Posted [0-9]{4}-[0-9]{2}-[0-9]{2}'
              AND to_date(substring(j.location from 'Posted ([0-9]{4}-[0-9]{2}-[0-9]{2})'), 'YYYY-MM-DD') < (CURRENT_DATE - 7)
          )
      );

    -- 2. Remove raw job records older than 30 days unless APPLIED
    DELETE FROM jobs 
    WHERE created_at < NOW() - INTERVAL '30 days'
      AND id NOT IN (
          SELECT job_id FROM evaluated_matches WHERE status = 'APPLIED'
      );
END;
$$ LANGUAGE plpgsql;

