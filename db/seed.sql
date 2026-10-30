-- Seed initial default tailoring rules, job preferences, and sample master profile if none exist
INSERT INTO tailoring_rules (id, forbidden_terms, protected_metrics, max_bullets_per_role, allow_rephrasing, lock_company_names, lock_dates)
VALUES (
    1,
    '["Java", "Spring Boot", "COBOL", "Wordpress"]'::jsonb,
    '["99.99%", "42%", "120ms", "$1.2M"]'::jsonb,
    4,
    TRUE,
    TRUE,
    TRUE
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO job_preferences (id, positive_titles, negative_title_keywords, natural_language_notes, min_semantic_score)
VALUES (
    1,
    '["Full Stack Engineer", "Senior Software Engineer", "Backend Engineer", "AI Platform Engineer"]'::jsonb,
    '["Manager", "Staff", "Director", "Wordpress", "Sales"]'::jsonb,
    'Focus on TypeScript, Python, Node.js, PostgreSQL, distributed backend systems, and modern web architectures.',
    0.70
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO master_profiles (basics, skills, experience, education, is_active)
SELECT
    '{
        "name": "Alex Rivera",
        "title": "Senior Full Stack Engineer",
        "email": "alex.rivera@example.com",
        "phone": "+1 (555) 234-5678",
        "location": "San Francisco, CA (Remote)",
        "links": ["https://github.com/alexrivera", "https://linkedin.com/in/alexrivera"],
        "summary": "Full-stack software engineer with 6+ years building distributed backend services, cloud-native data pipelines, and responsive TypeScript web applications."
    }'::jsonb,
    '{
        "languages": ["TypeScript", "Python", "SQL", "Bash"],
        "frameworks": ["Next.js", "React", "FastAPI", "Node.js", "Tailwind CSS"],
        "cloud": ["AWS", "Docker", "Cloudflare R2", "Vercel", "GitHub Actions"],
        "databases": ["PostgreSQL", "Redis", "ChromaDB"]
    }'::jsonb,
    '[
        {
            "role_id": "role-1",
            "company": "Acme Cloud Systems",
            "title": "Senior Software Engineer",
            "location": "Remote",
            "dates": "2023 - Present",
            "bullets": [
                "Architected event-driven ingestion pipeline in Python and PostgreSQL processing 2.4M daily webhook events with 99.99% uptime.",
                "Reduced p95 API latency by 42% (from 210ms to 120ms) by optimizing connection pooling and Redis read-through caching.",
                "Led migration of legacy dashboard to Next.js 14 App Router and TypeScript, cutting bundle size by 35%.",
                "Implemented automated CI/CD quality gates and integration test suites achieving 88% branch coverage."
            ],
            "tags": ["Python", "PostgreSQL", "Next.js", "TypeScript", "Redis"]
        },
        {
            "role_id": "role-2",
            "company": "Nimbus Data Labs",
            "title": "Software Engineer",
            "location": "Austin, TX",
            "dates": "2020 - 2023",
            "bullets": [
                "Built multi-tenant RBAC authentication service and OAuth 2.0 SSO flows supporting 15,000+ monthly active users.",
                "Developed asynchronous document processing workers in Docker and FastAPI saving $1.2M in annual third-party API costs.",
                "Designed real-time telemetry views in React and Tailwind CSS with sub-second WebSocket updates."
            ],
            "tags": ["FastAPI", "Docker", "React", "OAuth", "TypeScript"]
        }
    ]'::jsonb,
    '[
        {
            "institution": "University of Texas at Austin",
            "degree": "B.S. in Computer Science",
            "dates": "2016 - 2020"
        }
    ]'::jsonb,
    TRUE
WHERE NOT EXISTS (SELECT 1 FROM master_profiles WHERE is_active = TRUE);

