"""Unit tests for Typst PDF compilation and single-page assertion in worker/typesetter.py (Task 6.3)."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch
import pytest
from pypdf import PdfWriter

from worker.typesetter import (
    PageBudgetExceededError,
    TypstCompilationError,
    TypstTypesetter,
    verify_single_page_pdf,
)


def _create_blank_pdf(path: Path, num_pages: int = 1) -> Path:
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as f:
        writer.write(f)
    return path


def test_verify_single_page_pdf_passes_for_1_page(tmp_path: Path) -> None:
    pdf_file = _create_blank_pdf(tmp_path / "one_page.pdf", num_pages=1)
    assert verify_single_page_pdf(pdf_file) == 1


def test_verify_single_page_pdf_raises_when_exceeding_1_page(tmp_path: Path) -> None:
    pdf_file = _create_blank_pdf(tmp_path / "two_pages.pdf", num_pages=2)
    with pytest.raises(PageBudgetExceededError, match="2 pages"):
        verify_single_page_pdf(pdf_file)


def test_compile_template_headless_cli_and_single_page_assertion(tmp_path: Path) -> None:
    sample_payload = {
        "basics": {
            "name": "Alex Rivera",
            "title": "Senior Software Engineer",
            "email": "alex@example.com",
            "location": "Remote",
            "links": ["https://github.com/alexrivera"],
            "summary": "Experienced backend and full-stack software engineer.",
        },
        "skills": {
            "languages": ["Python", "TypeScript"],
            "databases": ["PostgreSQL"],
        },
        "experience": [
            {
                "role_id": "role-1",
                "company": "Acme Corp",
                "title": "Senior Engineer",
                "location": "Remote",
                "dates": "2022 - Present",
                "bullets": [
                    "Built event-driven ingestion pipeline processing 2.4M daily events.",
                    "Reduced API p95 latency by 42% using Redis caching.",
                ],
            }
        ],
        "education": [
            {
                "institution": "UT Austin",
                "degree": "B.S. Computer Science",
                "dates": "2016 - 2020",
            }
        ],
        "target_job": {"company": "Linear", "title": "Product Engineer"},
        "cover_letter_paragraphs": [
            "Paragraph 1 of evidence-based cover letter.",
            "Paragraph 2 highlighting verified metrics.",
            "Paragraph 3 concluding.",
        ],
    }

    typesetter = TypstTypesetter()
    out_resume = tmp_path / "resume.pdf"
    out_cover = tmp_path / "cover_letter.pdf"

    if shutil.which("typst"):
        # Real Typst binary available on host or container
        res_path = typesetter.compile_template("resume.typ", sample_payload, out_resume)
        cov_path = typesetter.compile_template("cover_letter.typ", sample_payload, out_cover)
        assert res_path.exists()
        assert cov_path.exists()
        assert verify_single_page_pdf(res_path) == 1
        assert verify_single_page_pdf(cov_path) == 1
    else:
        # Simulate Typst CLI writing a 1-page PDF when binary isn't installed on host
        def fake_run(cmd, **kwargs):
            out_arg = Path(cmd[-1])
            _create_blank_pdf(out_arg, num_pages=1)

            class FakeResult:
                returncode = 0
                stderr = ""

            return FakeResult()

        with patch("worker.typesetter.subprocess.run", side_effect=fake_run):
            res_path = typesetter.compile_template("resume.typ", sample_payload, out_resume)
            cov_path = typesetter.compile_template("cover_letter.typ", sample_payload, out_cover)
            assert res_path.exists()
            assert cov_path.exists()


def test_compile_resume_with_auto_trim_recovers_from_overflow(tmp_path: Path) -> None:
    payload = {
        "basics": {"name": "Alex Rivera"},
        "experience": [
            {
                "role_id": "role-1",
                "company": "Acme",
                "title": "Engineer",
                "bullets": ["Bullet 1", "Bullet 2", "Bullet 3"],
            }
        ],
    }
    typesetter = TypstTypesetter()
    call_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        out_arg = Path(cmd[-1])
        # First compile produces 2 pages; second compile (after auto-trim) produces 1 page
        pages = 2 if call_count["n"] == 1 else 1
        _create_blank_pdf(out_arg, num_pages=pages)

        class FakeResult:
            returncode = 0
            stderr = ""

        return FakeResult()

    with patch("worker.typesetter.subprocess.run", side_effect=fake_run):
        result_path = typesetter.compile_resume_with_auto_trim(
            payload, tmp_path / "trimmed_resume.pdf"
        )
        assert result_path.exists()
        assert call_count["n"] == 2


def test_compile_template_raises_on_nonzero_exit(tmp_path: Path) -> None:
    typesetter = TypstTypesetter()

    class FailedResult:
        returncode = 1
        stderr = "syntax error in template"

    with patch("worker.typesetter.subprocess.run", return_value=FailedResult()):
        with pytest.raises(TypstCompilationError, match="syntax error"):
            typesetter.compile_template("resume.typ", {}, tmp_path / "fail.pdf")


def test_compile_resume_with_auto_trim_combines_two_bullets(tmp_path: Path) -> None:
    payload = {
        "basics": {"name": "Alex Rivera"},
        "experience": [
            {
                "role_id": "anpac",
                "company": "American National Property and Casualty (ANPAC)",
                "title": "Help Desk Career Development Trainee",
                "source_bullet_count": 2,
                "bullets": [
                    "Delivered remote hardware and software technical support to field insurance agents and trained staff on proprietary rating systems.",
                    "Executed endpoint disk encryption (PGP, BestCrypt) across field agent machines to safeguard sensitive policyholder data.",
                ],
                "combined_bullet": "Delivered remote hardware and software technical support to field insurance agents and trained staff on proprietary rating systems, while executing endpoint disk encryption (PGP, BestCrypt) across field agent machines to safeguard sensitive policyholder data.",
            }
        ],
    }
    typesetter = TypstTypesetter()
    captured_payloads = []

    def fake_run(cmd, **kwargs):
        data_arg = [arg for arg in cmd if arg.startswith("data=")][0]
        json_str = data_arg.split("data=", 1)[1]
        import json

        captured_payloads.append(json.loads(json_str))

        out_arg = Path(cmd[-1])
        pages = 2 if len(captured_payloads) == 1 else 1
        _create_blank_pdf(out_arg, num_pages=pages)

        class FakeResult:
            returncode = 0
            stderr = ""

        return FakeResult()

    with patch("worker.typesetter.subprocess.run", side_effect=fake_run):
        typesetter.compile_resume_with_auto_trim(payload, tmp_path / "combined_resume.pdf")

    assert len(captured_payloads) >= 2
    trimmed_bullets = captured_payloads[1]["experience"][0]["bullets"]
    assert len(trimmed_bullets) == 1
    assert "Delivered remote hardware" in trimmed_bullets[0]
    assert "disk encryption" in trimmed_bullets[0]


def test_compile_resume_with_auto_trim_produces_coherent_single_bullet(tmp_path: Path) -> None:
    # SoftVu bullets with topic headers
    payload = {
        "basics": {"name": "Alex Rivera"},
        "experience": [
            {
                "role_id": "softvu",
                "company": "SoftVu",
                "title": "Software Developer",
                "source_bullet_count": 4,
                "bullets": [
                    "Webhooks & Third-Party API Integration: Developed real-time webhooks for email event streams (CoffeeScript, Node).",
                    "Tooling & Automation: Implemented template cloning and automated HTML-to-PDF/PNG export tools (Angular 1.x, Node, Bootstrap).",
                ],
            }
        ],
    }
    typesetter = TypstTypesetter()
    captured_payloads = []

    def fake_run(cmd, **kwargs):
        data_arg = [arg for arg in cmd if arg.startswith("data=")][0]
        json_str = data_arg.split("data=", 1)[1]
        import json

        captured_payloads.append(json.loads(json_str))

        out_arg = Path(cmd[-1])
        pages = 2 if len(captured_payloads) == 1 else 1
        _create_blank_pdf(out_arg, num_pages=pages)

        class FakeResult:
            returncode = 0
            stderr = ""

        return FakeResult()

    with patch("worker.typesetter.subprocess.run", side_effect=fake_run):
        typesetter.compile_resume_with_auto_trim(payload, tmp_path / "softvu_resume.pdf")

    assert len(captured_payloads) >= 2
    trimmed_bullets = captured_payloads[1]["experience"][0]["bullets"]
    assert len(trimmed_bullets) == 1
    # Must be a coherent sentence, NEVER have mid-sentence "while tooling & Automation:"
    assert "while tooling" not in trimmed_bullets[0]
    assert "Tooling & Automation:" not in trimmed_bullets[0]
    assert "Webhooks & Third-Party API Integration:" in trimmed_bullets[0]


def test_resume_typ_renders_ai_developer_tooling_category(tmp_path: Path) -> None:
    if not shutil.which("typst"):
        pytest.skip("typst binary not found on host (runs in docker)")
    typesetter = TypstTypesetter()
    payload = {
        "basics": {
            "name": "Justin Pacubas",
            "title": "Full-Stack Engineer",
            "email": "justin@example.com",
            "location": "Remote",
            "links": ["https://linkedin.com/in/example"],
            "summary": "Full-Stack Engineer.",
        },
        "skills": {
            "languages": ["TypeScript", "Node.js"],
            "cloud": ["AWS", "Docker"],
            "ai_developer_tooling": ["AWS Kiro", "Claude (Anthropic)", "AI Developer Workflows"],
        },
        "experience": [
            {
                "role_id": "pushly",
                "company": "Pushly",
                "title": "Full-Stack Engineer",
                "location": "Remote",
                "dates": "2022 - Present",
                "bullets": [
                    "Integrated developer tooling including AI tools and workflows (AWS Kiro using Claude models).",
                ],
            }
        ],
        "education": [],
    }
    out_pdf = tmp_path / "ai_skills_resume.pdf"
    res = typesetter.compile_template("resume.typ", payload, out_pdf, enforce_single_page=True)
    assert res.exists()
    assert verify_single_page_pdf(res) == 1


