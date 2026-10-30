import type { EvaluatedJobMatch, JobPreferencesRecord, MasterProfileRecord, TailoringRulesRecord } from "./db";

export const DEMO_MATCHES: EvaluatedJobMatch[] = [
  {
    id: "demo-match-1",
    job_id: "demo-job-1",
    title: "Senior Full Stack Engineer, AI Platform",
    company: "Linearity Labs",
    location: "San Francisco, CA (Remote)",
    is_remote: true,
    url: "https://example.com/jobs/linearity-ai-platform",
    salary_range: "$185,000 - $220,000",
    semantic_score: 0.91,
    fit_score: 9.4,
    fit_rationale:
      "Direct alignment across Next.js 14 App Router, TypeScript, Python worker pipelines, and PostgreSQL performance tuning. Minor gap in Kubernetes multi-cluster federation.",
    matched_skills: ["TypeScript", "Next.js", "Python", "PostgreSQL", "Redis", "Docker"],
    missing_skills: ["Kubernetes Federation"],
    resume_storage_key: "matches/demo1/resume.pdf",
    cover_letter_storage_key: "matches/demo1/cover_letter.pdf",
    status: "NEW_MATCH",
    created_at: "2026-10-30T08:15:00Z",
    payload_snapshot: {
      generated_at: "2026-10-30T08:14:52Z",
      target_job: {
        title: "Senior Full Stack Engineer, AI Platform",
        company: "Linearity Labs",
      },
      guardrails_applied: {
        allow_rephrasing: true,
        forbidden_terms: ["Java", "Spring Boot", "COBOL"],
        protected_metrics: ["99.99%", "42%", "120ms", "$1.2M"],
        max_bullets_per_role: 4,
      },
      basics: {
        name: "Alex Rivera (Demo Profile)",
        title: "Senior Full Stack Engineer",
        email: "alex.demo@example.com",
        location: "Remote",
      },
      experience: [
        {
          role_id: "role-1",
          company: "Acme Cloud Systems",
          title: "Senior Software Engineer",
          dates: "2023 - Present",
          bullets: [
            "Architected event-driven ingestion pipeline in Python and PostgreSQL processing 2.4M daily webhook events with 99.99% uptime.",
            "Reduced p95 API latency by 42% (from 210ms to 120ms) by optimizing connection pooling and Redis read-through caching.",
            "Led migration of legacy dashboard to Next.js 14 App Router and TypeScript, cutting bundle size by 35%.",
          ],
        },
      ],
    },
  },
  {
    id: "demo-match-2",
    job_id: "demo-job-2",
    title: "Distributed Systems Backend Engineer",
    company: "Chronicle Cloud",
    location: "Remote (US)",
    is_remote: true,
    url: "https://example.com/jobs/chronicle-backend",
    salary_range: "$175,000 - $205,000",
    semantic_score: 0.86,
    fit_score: 8.8,
    fit_rationale:
      "Strong backend systems overlap with high-throughput webhook ingestion, FastAPI workers, and OAuth 2.0 RBAC security. Role emphasizes Rust storage engines as a nice-to-have.",
    matched_skills: ["Python", "FastAPI", "PostgreSQL", "Docker", "OAuth 2.0"],
    missing_skills: ["Rust"],
    resume_storage_key: "matches/demo2/resume.pdf",
    cover_letter_storage_key: "matches/demo2/cover_letter.pdf",
    status: "SAVED",
    created_at: "2026-10-29T09:00:00Z",
    payload_snapshot: {
      generated_at: "2026-10-29T08:59:10Z",
      target_job: {
        title: "Distributed Systems Backend Engineer",
        company: "Chronicle Cloud",
      },
      guardrails_applied: {
        allow_rephrasing: false,
        forbidden_terms: ["Java", "Spring Boot"],
        protected_metrics: ["99.99%", "$1.2M"],
        max_bullets_per_role: 4,
      },
      basics: {
        name: "Alex Rivera (Demo Profile)",
        title: "Senior Full Stack Engineer",
      },
      experience: [
        {
          role_id: "role-2",
          company: "Nimbus Data Labs",
          title: "Software Engineer",
          dates: "2020 - 2023",
          bullets: [
            "Built multi-tenant RBAC authentication service and OAuth 2.0 SSO flows supporting 15,000+ monthly active users.",
            "Developed asynchronous document processing workers in Docker and FastAPI saving $1.2M in annual third-party API costs.",
          ],
        },
      ],
    },
  },
];

export const DEFAULT_TAILORING_RULES: TailoringRulesRecord = {
  id: 1,
  forbidden_terms: ["Java", "Spring Boot", "COBOL", "Wordpress"],
  protected_metrics: ["99.99%", "42%", "120ms", "$1.2M"],
  max_bullets_per_role: 4,
  allow_rephrasing: true,
  lock_company_names: true,
  lock_dates: true,
};

export const DEFAULT_PREFERENCES: JobPreferencesRecord = {
  id: 1,
  positive_titles: [
    "Full Stack Engineer",
    "Senior Software Engineer",
    "Backend Engineer",
    "AI Platform Engineer",
  ],
  negative_title_keywords: ["Manager", "Staff", "Director", "Wordpress"],
  natural_language_notes:
    "Focus on TypeScript, Python, Node.js, PostgreSQL, distributed backend systems, and modern web architectures.",
  min_semantic_score: 0.7,
};

export const DEFAULT_MASTER_PROFILE: MasterProfileRecord = {
  id: "demo-profile-1",
  uploaded_at: "2026-10-28T12:00:00Z",
  basics: {
    name: "Alex Rivera",
    title: "Senior Full Stack Engineer",
    email: "alex.rivera@example.com",
    location: "San Francisco, CA (Remote)",
    summary:
      "Full-stack software engineer with 6+ years building distributed backend services, cloud-native data pipelines, and responsive TypeScript web applications.",
  },
  skills: {
    languages: ["TypeScript", "Python", "SQL", "Bash"],
    frameworks: ["Next.js", "React", "FastAPI", "Node.js", "Tailwind CSS"],
    cloud: ["AWS", "Docker", "Cloudflare R2", "Vercel"],
    databases: ["PostgreSQL", "Redis", "ChromaDB"],
  },
  experience: [
    {
      role_id: "role-1",
      company: "Acme Cloud Systems",
      title: "Senior Software Engineer",
      location: "Remote",
      dates: "2023 - Present",
      bullets: [
        "Architected event-driven ingestion pipeline in Python and PostgreSQL processing 2.4M daily webhook events with 99.99% uptime.",
        "Reduced p95 API latency by 42% (from 210ms to 120ms) by optimizing connection pooling and Redis read-through caching.",
        "Led migration of legacy dashboard to Next.js 14 App Router and TypeScript, cutting bundle size by 35%.",
        "Implemented automated CI/CD quality gates and integration test suites achieving 88% branch coverage.",
      ],
      tags: ["Python", "PostgreSQL", "Next.js", "TypeScript", "Redis"],
    },
  ],
  education: [
    {
      institution: "University of Texas at Austin",
      degree: "B.S. in Computer Science",
      dates: "2016 - 2020",
    },
  ],
};

