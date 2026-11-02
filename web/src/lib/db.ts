import { neon } from "@neondatabase/serverless";

export type MatchStatus = "NEW_MATCH" | "SAVED" | "APPLIED" | "ARCHIVED";

export interface EvaluatedJobMatch {
  id: string;
  job_id: string;
  source?: string;
  title: string;
  company: string;
  location: string;
  is_remote: boolean;
  url: string;
  salary_range: string | null;
  semantic_score: number;
  fit_score: number;
  fit_rationale: string;
  matched_skills: string[];
  missing_skills: string[];
  resume_storage_key: string | null;
  cover_letter_storage_key: string | null;
  payload_snapshot: Record<string, unknown>;
  status: MatchStatus;
  created_at: string;
}

export interface TailoringRulesRecord {
  id: number;
  forbidden_terms: string[];
  protected_metrics: string[];
  max_bullets_per_role: number;
  allow_rephrasing: boolean;
  lock_company_names: boolean;
  lock_dates: boolean;
}

export interface JobPreferencesRecord {
  id: number;
  positive_titles: string[];
  negative_title_keywords: string[];
  natural_language_notes: string;
  min_semantic_score: number;
  ats_boards?: {
    greenhouse?: string[];
    lever?: string[];
    ashby?: string[];
    preferred_locations?: string[];
    allow_remote?: boolean;
    max_per_company?: number;
    enable_tier1?: boolean;
    enable_tier2?: boolean;
  };
}

export interface MasterProfileRecord {
  id: string;
  basics: Record<string, unknown>;
  skills: Record<string, string[]>;
  experience: Array<{
    role_id: string;
    company: string;
    title: string;
    location: string;
    dates: string;
    bullets: string[];
    tags?: string[];
  }>;
  education: Array<{
    institution: string;
    degree: string;
    dates: string;
  }>;
  uploaded_at: string;
}

export function getSql() {
  const url = process.env.DATABASE_URL;
  if (!url) {
    throw new Error("DATABASE_URL is not configured");
  }
  return neon(url);
}

export function getPreferredWorkerNodeId(): string | null {
  const raw = (
    process.env.PREFERRED_WORKER_NODE_ID ||
    process.env.WORKER_NODE_ID ||
    ""
  ).trim();
  return raw ? raw : null;
}

export function withWorkerAffinity(
  payload: Record<string, unknown> = {}
): Record<string, unknown> {
  const targetWorker =
    typeof payload.target_worker === "string" && payload.target_worker.trim()
      ? payload.target_worker.trim()
      : getPreferredWorkerNodeId();
  if (!targetWorker) {
    return payload;
  }
  return {
    ...payload,
    target_worker: targetWorker,
  };
}
