"""Unit tests for JobSynthesizer tailoring methods in worker/synthesizer.py."""

from __future__ import annotations

from typing import List
from unittest.mock import patch
from worker.schemas import JobEvaluationResult, ScrapedJob
from worker.synthesizer import (
    JobSynthesizer,
    apply_full_stack_style,
    detect_full_stack_style,
    normalize_full_stack_hyphenation,
)


def _fake_embed(texts: List[str]) -> List[List[float]]:
    job = texts[0].lower()
    vecs: List[List[float]] = []
    for t in texts:
        tl = t.lower()
        score = 0.1
        if "catalog" in job and "catalog" in tl:
            score += 0.8
        if "react" in job and "react" in tl:
            score += 0.5
        vecs.append([score, 0.2, 0.1])
    return vecs


class FakeRanker:
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return _fake_embed(texts)


def test_prioritize_skills_promotes_matching_skills_to_front() -> None:
    synthesizer = JobSynthesizer(ranker=FakeRanker())
    skills_map = {
        "languages": ["Ruby on Rails", "TypeScript", "Perl", "JavaScript (ES6+)", "SQL"],
        "databases": ["MySQL", "Redis", "PostgreSQL"],
        "ai_developer_tooling": ["AI Developer Workflows", "Claude", "AWS Kiro"],
    }
    job_desc = "We need an engineer experienced with TypeScript, Claude, and PostgreSQL to build scalable web applications."
    matched_skills = ["TypeScript", "PostgreSQL", "Claude"]

    prioritized = synthesizer.prioritize_skills(
        skills_map=skills_map,
        job_description=job_desc,
        matched_skills=matched_skills,
    )

    # TypeScript should be first in languages
    assert prioritized["languages"][0] == "TypeScript"
    # PostgreSQL should be first in databases
    assert prioritized["databases"][0] == "PostgreSQL"
    # Claude should be first in ai_developer_tooling
    assert prioritized["ai_developer_tooling"][0] == "Claude"
    # All original skills must still be present and no new skills added
    assert set(prioritized["languages"]) == set(skills_map["languages"])
    assert set(prioritized["databases"]) == set(skills_map["databases"])
    assert set(prioritized["ai_developer_tooling"]) == set(skills_map["ai_developer_tooling"])


def test_select_nearest_bullets_reorders_by_relevance() -> None:
    synthesizer = JobSynthesizer(ranker=FakeRanker())
    source_bullets = [
        "Core Reliability: Maintained microservices and resolved hotfixes.",
        "Catalogs Platform: Built new Catalogs platform from ground up with search APIs.",
    ]
    job_desc = "Looking for an engineer to architect a modern catalog system."

    ordered = synthesizer.select_nearest_bullets(
        job_description=job_desc,
        source_bullets=source_bullets,
        max_bullets=4,
    )

    # The Catalogs bullet should now be ordered first because of higher relevance
    assert len(ordered) == 2
    assert "Catalogs Platform" in ordered[0]
    assert "Core Reliability" in ordered[1]


def test_detect_and_apply_full_stack_style() -> None:
    # Hyphenated when job title explicitly uses full-stack
    assert detect_full_stack_style("Full-Stack Software Engineer") == "Full-Stack"
    assert detect_full_stack_style("Senior Full-Stack Developer") == "Full-Stack"
    assert detect_full_stack_style("Software Engineer - Full-Stack") == "Full-Stack"

    # Unhyphenated when job title uses full stack or does not use hyphens
    assert detect_full_stack_style("Full Stack Software Engineer") == "Full Stack"
    assert detect_full_stack_style("Product Engineer") == "Full Stack"
    assert detect_full_stack_style("Backend Systems Engineer") == "Full Stack"

    # apply_full_stack_style conversions
    assert (
        apply_full_stack_style("Hands-on Full-Stack Platform Engineer", "Full Stack")
        == "Hands-on Full Stack Platform Engineer"
    )
    assert (
        apply_full_stack_style("Hands-on Full Stack Platform Engineer", "Full-Stack")
        == "Hands-on Full-Stack Platform Engineer"
    )


def test_generate_tailored_headline_adaptive_hyphenation() -> None:
    synthesizer = JobSynthesizer(ranker=FakeRanker())
    candidate_title = "Systems and Full-Stack Platform Engineer"

    # 1. Product Engineer (no hyphens in listing title -> unhyphenated)
    pe_style = detect_full_stack_style("Product Engineer")
    assert pe_style == "Full Stack"
    product_headline = synthesizer.generate_tailored_headline(
        "Product Engineer", candidate_title, style=pe_style
    )
    assert product_headline == "Full Stack Product Engineer"
    assert "Full-Stack" not in product_headline

    # 2. Full Stack Software Engineer (no hyphens in listing title -> unhyphenated)
    fs_style = detect_full_stack_style("Full Stack Software Engineer")
    assert fs_style == "Full Stack"
    fs_headline = synthesizer.generate_tailored_headline(
        "Full Stack Software Engineer", candidate_title, style=fs_style
    )
    assert fs_headline == "Full Stack Software Engineer"
    assert "Full-Stack" not in fs_headline

    # 3. Full-Stack Software Engineer (hyphens in listing title -> hyphenated)
    hyphen_style = detect_full_stack_style("Full-Stack Software Engineer")
    assert hyphen_style == "Full-Stack"
    hyphen_headline = synthesizer.generate_tailored_headline(
        "Full-Stack Software Engineer", candidate_title, style=hyphen_style
    )
    assert hyphen_headline == "Full-Stack Software Engineer"
    assert "Full Stack" not in hyphen_headline

    # Distinct headlines across different roles
    assert product_headline != fs_headline


def test_generate_tailored_summary_ensures_title_consistency_and_adaptive_hyphenation() -> None:
    synthesizer = JobSynthesizer(ranker=FakeRanker())
    eval_res = JobEvaluationResult(
        fit_score=8.5,
        matched_skills=["React", "Node.js"],
        missing_skills=[],
        fit_rationale="Strong alignment.",
    )
    mock_experience = [
        {
            "company": "Pushly",
            "title": "Full-Stack Engineer",
            "bullets": ["Maintained 13 core repositories across microservices and React SPAs."],
        }
    ]

    # Case A: Target listing is unhyphenated "Full Stack Software Engineer"
    job_unhyphenated = ScrapedJob(
        source="test",
        source_id="1",
        title="Full Stack Software Engineer",
        company="Acme",
        location="Remote",
        is_remote=True,
        url="https://example.com/job1",
        content_hash="abc1",
        description_text="Build web applications using TypeScript and Node.js.",
    )
    master_summary = "Hands-on Systems and Full-Stack Platform Engineer with over a decade of deep experience."
    tailored_title_unhyphenated = "Full Stack Software Engineer"
    res_unhyphenated = synthesizer.generate_tailored_summary(
        job=job_unhyphenated,
        tailored_title=tailored_title_unhyphenated,
        master_summary=master_summary,
        experience=mock_experience,
        evaluation=eval_res,
        style="Full Stack",
    )
    assert tailored_title_unhyphenated in res_unhyphenated
    assert "Full Stack Software Engineer" in res_unhyphenated
    assert "Full-Stack" not in res_unhyphenated

    # Case B: Target listing is hyphenated "Full-Stack Product Engineer"
    job_hyphenated = ScrapedJob(
        source="test",
        source_id="2",
        title="Full-Stack Product Engineer",
        company="TechnologyAdvice",
        location="Remote",
        is_remote=True,
        url="https://example.com/job2",
        content_hash="abc2",
        description_text="Build product features and data pipelines.",
    )
    tailored_title_hyphenated = "Full-Stack Product Engineer"
    res_hyphenated = synthesizer.generate_tailored_summary(
        job=job_hyphenated,
        tailored_title=tailored_title_hyphenated,
        master_summary=master_summary,
        experience=mock_experience,
        evaluation=eval_res,
        style="Full-Stack",
    )
    assert tailored_title_hyphenated in res_hyphenated
    assert "Full-Stack Product Engineer" in res_hyphenated
    assert "Full Stack" not in res_hyphenated


def test_generate_tailored_summary_rejects_puffed_up_superlatives() -> None:
    synthesizer = JobSynthesizer(ranker=FakeRanker())
    job = ScrapedJob(
        source="test",
        source_id="1",
        title="Full Stack Software Engineer",
        company="Acme",
        location="Remote",
        is_remote=True,
        url="https://example.com/job",
        content_hash="abc",
        description_text="Build web applications.",
    )
    master_summary = "Hands-on Systems and Full-Stack Platform Engineer with over a decade of experience."
    tailored_title = "Full Stack Software Engineer"
    eval_res = JobEvaluationResult(
        fit_score=8.5,
        matched_skills=["React", "Node.js"],
        missing_skills=[],
        fit_rationale="Strong alignment.",
    )
    mock_experience = [
        {
            "company": "Pushly",
            "title": "Full-Stack Engineer",
            "bullets": ["Maintained 13 core repositories across microservices and React SPAs."],
        }
    ]

    # Reject 'Expert in leveraging...' and fall back
    with patch.object(
        synthesizer,
        "_chat_json",
        return_value={"summary": "Expert in leveraging TypeScript, React, and Node.js to build software solutions."},
    ):
        fallback_expert = synthesizer.generate_tailored_summary(
            job=job,
            tailored_title=tailored_title,
            master_summary=master_summary,
            experience=mock_experience,
            evaluation=eval_res,
            style="Full Stack",
        )
        assert "Expert" not in fallback_expert
        assert tailored_title in fallback_expert
        assert "Full-Stack" not in fallback_expert

    # Accept grounded, matter-of-fact phrasing
    grounded_summary = f"Hands-on {tailored_title} with over a decade of experience designing scalable data workflows and web applications."
    with patch.object(synthesizer, "_chat_json", return_value={"summary": grounded_summary}):
        grounded_result = synthesizer.generate_tailored_summary(
            job=job,
            tailored_title=tailored_title,
            master_summary=master_summary,
            experience=mock_experience,
            evaluation=eval_res,
            style="Full Stack",
        )
        assert grounded_result == grounded_summary


def test_build_tailored_payload_adaptive_hyphenation_and_title_sync() -> None:
    synthesizer = JobSynthesizer(ranker=FakeRanker())
    eval_res = JobEvaluationResult(
        fit_score=9.0,
        matched_skills=["TypeScript", "React"],
        missing_skills=[],
        fit_rationale="Great fit.",
    )
    master_profile = {
        "basics": {
            "name": "JUSTIN PACUBAS",
            "title": "Systems and Full-Stack Platform Engineer",
            "summary": "Hands-on Systems and Full-Stack Platform Engineer with over a decade of deep experience.",
        },
        "skills": {
            "languages": ["TypeScript", "Node.js"],
        },
        "experience": [
            {
                "role_id": "pushly",
                "company": "Pushly",
                "title": "Full-Stack Engineer",
                "bullets": ["Core Reliability: Built scalable microservices."],
            }
        ],
    }

    # Job A: Unhyphenated title
    job_a = ScrapedJob(
        source="test",
        source_id="a",
        title="Full Stack Software Engineer",
        company="Acme",
        location="Remote",
        is_remote=True,
        url="https://example.com/job_a",
        content_hash="hash_a",
        description_text="Building applications with TypeScript.",
    )
    payload_a = synthesizer.build_tailored_payload(
        job=job_a,
        master_profile=master_profile,
        tailoring_rules={"allow_rephrasing": False},
        evaluation=eval_res,
    )
    assert payload_a["basics"]["title"] == "Full Stack Software Engineer"
    assert "Full Stack Software Engineer" in payload_a["basics"]["summary"]
    assert "Full-Stack" not in payload_a["basics"]["summary"]

    # Job B: Hyphenated title
    job_b = ScrapedJob(
        source="test",
        source_id="b",
        title="Full-Stack Product Engineer",
        company="TechCorp",
        location="Remote",
        is_remote=True,
        url="https://example.com/job_b",
        content_hash="hash_b",
        description_text="Building full-stack products.",
    )
    payload_b = synthesizer.build_tailored_payload(
        job=job_b,
        master_profile=master_profile,
        tailoring_rules={"allow_rephrasing": False},
        evaluation=eval_res,
    )
    assert payload_b["basics"]["title"] == "Full-Stack Product Engineer"
    assert "Full-Stack Product Engineer" in payload_b["basics"]["summary"]
    assert "Full Stack" not in payload_b["basics"]["summary"]


def test_combine_bullets_coherently_merges_two_accomplishments() -> None:
    synthesizer = JobSynthesizer(ranker=FakeRanker())
    b1 = "Delivered remote hardware and software technical support to field insurance agents and trained staff on proprietary rating systems."
    b2 = "Executed endpoint disk encryption (PGP, BestCrypt) across field agent machines to safeguard sensitive policyholder data."

    # Test LLM response with 'while' converted to clean semicolon coordination
    combined_llm = (
        "Delivered remote hardware and software support on proprietary rating systems, "
        "while executing endpoint disk encryption (PGP, BestCrypt) to safeguard sensitive data."
    )
    with patch.object(synthesizer, "_chat_json", return_value={"bullet": combined_llm}):
        res = synthesizer.combine_bullets(
            source_bullets=[b1, b2],
            role_title="Help Desk Career Development Trainee",
            company="ANPAC",
            job_title="Software Engineer",
        )
        assert "while" not in res
        assert "Delivered remote" in res
        assert "; executed endpoint disk encryption" in res
        assert "PGP" in res

    # Test fallback merge when LLM call fails
    with patch.object(synthesizer, "_chat_json", side_effect=RuntimeError("LLM offline")):
        res_fallback = synthesizer.combine_bullets(
            source_bullets=[b1, b2],
            role_title="Help Desk Career Development Trainee",
            company="ANPAC",
            job_title="Software Engineer",
        )
        assert "Delivered remote hardware" in res_fallback
        assert "; executed endpoint disk encryption (PGP, BestCrypt)" in res_fallback
        assert "while" not in res_fallback


def test_build_tailored_payload_attaches_combined_bullet_for_two_bullet_roles() -> None:
    synthesizer = JobSynthesizer(ranker=FakeRanker())
    eval_res = JobEvaluationResult(
        fit_score=8.0,
        matched_skills=["Support"],
        missing_skills=[],
        fit_rationale="Strong technical support alignment.",
    )
    master_profile = {
        "basics": {"name": "Alex Rivera", "title": "Engineer", "summary": "Engineer summary."},
        "skills": {"languages": ["Python"]},
        "experience": [
            {
                "role_id": "anpac",
                "company": "American National Property and Casualty (ANPAC)",
                "title": "Help Desk Career Development Trainee",
                "bullets": [
                    "Delivered remote hardware and software technical support to field insurance agents and trained staff on proprietary rating systems.",
                    "Executed endpoint disk encryption (PGP, BestCrypt) across field agent machines to safeguard sensitive policyholder data.",
                ],
            }
        ],
    }
    job = ScrapedJob(
        source="test",
        source_id="c",
        title="Support Engineer",
        company="Tech",
        location="Remote",
        is_remote=True,
        url="https://example.com/job_c",
        content_hash="hash_c",
        description_text="Technical support role.",
    )

    with patch.object(synthesizer, "_chat_json", side_effect=RuntimeError("use fallback")):
        payload = synthesizer.build_tailored_payload(
            job=job,
            master_profile=master_profile,
            tailoring_rules={"allow_rephrasing": False},
            evaluation=eval_res,
        )

    role_out = payload["experience"][0]
    assert "combined_bullet" in role_out
    assert "Delivered remote hardware" in role_out["combined_bullet"]
    assert "disk encryption" in role_out["combined_bullet"]


def test_consolidate_role_bullets_four_to_two_thematic() -> None:
    synthesizer = JobSynthesizer(ranker=FakeRanker())
    softvu_bullets = [
        "Webhooks & Third-Party API Integration: Developed real-time webhooks for email event streams to synchronize data with third-party CRMs (CoffeeScript, Node).",
        "Enterprise CRM Integration: Authored Salesforce packages (Apex) connecting client Salesforce orgs directly to SoftVu's automated email platform, supporting enterprise client workflows.",
        "Platform Resilience: Created request capture and replay mechanisms for scheduled maintenance windows to safeguard transaction streams; built marketing strategy data visualizations with D3.js.",
        "Tooling & Automation: Implemented template cloning and automated HTML-to-PDF/PNG export tools (Angular 1.x, Node, Bootstrap).",
    ]

    mock_llm_response = {
        "bullets": [
            "API & CRM Integration: Developed real-time webhooks for email event streams using CoffeeScript and Node; authored Apex packages connecting Salesforce orgs to automated email platforms.",
            "Platform Resilience & Tooling: Built transaction replay mechanisms for maintenance windows, D3.js data visualizations, and automated HTML export tools with Angular, Node, and Bootstrap.",
        ]
    }

    with patch.object(synthesizer, "_chat_json", return_value=mock_llm_response):
        consolidated = synthesizer.consolidate_role_bullets(
            source_bullets=softvu_bullets,
            target_count=2,
            role_title="Software Engineer",
            company="SoftVu",
            job_title="Full-Stack Engineer",
        )

    assert len(consolidated) == 2
    # Bullet 1 covers webhooks and salesforce/CRM
    assert "webhooks" in consolidated[0].lower()
    assert "apex" in consolidated[0].lower() or "crm" in consolidated[0].lower()
    # Bullet 2 covers platform resilience / D3.js / tooling
    assert "d3.js" in consolidated[1].lower() or "replay" in consolidated[1].lower() or "tools" in consolidated[1].lower()
    # Check that neither bullet uses the awkward 'while' conjunction
    for b in consolidated:
        assert "while" not in b.lower()

