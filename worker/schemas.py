"""Pydantic schemas enforcing page budgets, structured LLM outputs, and validation contracts."""

from __future__ import annotations

from typing import Annotated, Dict, List, Optional
from pydantic import BaseModel, Field, StringConstraints

# Page-budget enforced bullet string: <= 170 characters per SPEC.md section 3.3
TailoredBullet = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=170),
]


class TailoredExperience(BaseModel):
    """Single role entry with at most 4 tailored bullets to guarantee single-page fit."""

    role_id: str = Field(..., description="Unique identifier matching source master_profiles role_id")
    bullets: List[TailoredBullet] = Field(
        default_factory=list,
        max_length=4,
        description="Up to 4 concise, verified accomplishments (max 170 chars each)",
    )


class JobEvaluationResult(BaseModel):
    """Structured LLM evaluation of a job posting against the master profile."""

    fit_score: float = Field(
        ...,
        ge=1.0,
        le=10.0,
        description="Overall candidate fit score from 1.0 to 10.0",
    )
    matched_skills: List[str] = Field(
        default_factory=list,
        description="Verified candidate skills overlapping with job requirements",
    )
    missing_skills: List[str] = Field(
        default_factory=list,
        description="Skills requested by the job that are absent from the candidate profile",
    )
    fit_rationale: str = Field(
        ...,
        min_length=10,
        max_length=600,
        description="Concise 2-sentence explanation of technical alignment and gaps",
    )


class TailoredResumeResponse(BaseModel):
    """Structured LLM output for extractive bullet selection & constrained keyword alignment."""

    tailored_roles: List[TailoredExperience] = Field(
        default_factory=list,
        description="Tailored bullets mapped by role_id",
    )


class CoverLetterResponse(BaseModel):
    """Structured 3-paragraph evidence-based cover letter response."""

    paragraphs: List[str] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Exactly 3 evidence-based paragraphs grounded in candidate experience",
    )


class ParsedRoleEntry(BaseModel):
    role_id: str
    company: str
    title: str
    location: str = "Remote"
    dates: str
    bullets: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)


class ParsedEducationEntry(BaseModel):
    institution: str
    degree: str
    dates: str


class ParsedMasterProfile(BaseModel):
    """Schema used when parsing uploaded raw PDF/DOCX text into master_profiles."""

    basics: Dict[str, object]
    skills: Dict[str, List[str]]
    experience: List[ParsedRoleEntry]
    education: List[ParsedEducationEntry]


class ScrapedJob(BaseModel):
    """Normalized representation of a scraped job listing before DB persistence."""

    source: str
    source_id: str
    title: str
    company: str
    location: str = "Remote"
    is_remote: bool = True
    url: str
    content_hash: str
    description_text: str
    salary_range: Optional[str] = None

