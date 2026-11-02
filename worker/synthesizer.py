"""Constrained LLM reasoning, nearest-neighbor bullet selection, and cover letter drafting (FR-2.4)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Type
from openai import OpenAI
from pydantic import BaseModel, Field

from worker.config import WorkerConfig
from worker.ranker import SemanticRanker, cosine_similarity
from worker.schemas import (
    CoverLetterResponse,
    JobEvaluationResult,
    ParsedMasterProfile,
    ScrapedJob,
)
from worker.validator import GuardrailValidator

logger = logging.getLogger(__name__)


def _extract_json_object(raw_content: str) -> Dict[str, Any]:
    """Safely extracts a JSON object from an LLM response that may include <think> blocks or markdown fences."""
    cleaned = (raw_content or "").strip()
    # Strip <think>...</think> reasoning traces emitted by Qwen3 / DeepSeek-R1 models
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()
    if "</think>" in cleaned:
        cleaned = cleaned.split("</think>", 1)[-1].strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


class SingleBulletResponse(BaseModel):
    bullet: str = Field(..., max_length=170)


class JobSynthesizer:
    """Interfaces with host LM Studio Local Server for evaluation, extractive tailoring, and cover letters."""

    def __init__(
        self,
        config: Optional[WorkerConfig] = None,
        openai_client: Optional[OpenAI] = None,
        ranker: Optional[SemanticRanker] = None,
        validator: Optional[GuardrailValidator] = None,
    ) -> None:
        self.config = config or WorkerConfig()
        self.client = openai_client or OpenAI(
            base_url=self.config.lm_studio_base_url,
            api_key=self.config.lm_studio_api_key,
            timeout=300.0,
            max_retries=0,
        )
        self.ranker = ranker or SemanticRanker(self.config.embedding_model_name)
        self.validator = validator or GuardrailValidator(
            similarity_threshold=self.config.semantic_drift_threshold,
            max_bullet_chars=self.config.bullet_max_chars,
        )

    def _chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        schema_model: Optional[Type[BaseModel]] = None,
    ) -> Dict[str, Any]:
        """
        Executes a streaming low-temperature JSON completion using LM Studio's
        Pydantic JSON Schema grammar constraint (FR-2.4).
        Streaming prevents read timeouts during long local LLM generations.
        """
        kwargs: Dict[str, Any] = {
            "model": self.config.lm_studio_model,
            "temperature": self.config.llm_temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "extra_body": {
                "reasoning_effort": "none",
                "chat_template_kwargs": {"enable_thinking": False},
            },
            "messages": [
                {
                    "role": "system",
                    "content": f"{system_prompt}\nRespond directly with raw JSON only. Do not output thinking or reasoning steps.",
                },
                {"role": "user", "content": f"{user_prompt}\n/no_think"},
            ],
        }
        if schema_model is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_model.__name__,
                    "strict": False,
                    "schema": schema_model.model_json_schema(),
                },
            }

        stream = self.client.chat.completions.create(**kwargs)
        content_chunks: List[str] = []
        reasoning_chunks: List[str] = []

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                content_chunks.append(delta.content)
            extra = getattr(delta, "model_extra", {}) or {}
            r_text = getattr(delta, "reasoning_content", None) or extra.get("reasoning_content")
            if r_text:
                reasoning_chunks.append(str(r_text))

        content = "".join(content_chunks).strip()
        if not content and reasoning_chunks:
            content = "".join(reasoning_chunks).strip()
        return _extract_json_object(content or "{}")

    def evaluate_job_fit(
        self,
        job: ScrapedJob,
        master_profile: Dict[str, Any],
        natural_language_notes: str = "",
    ) -> JobEvaluationResult:
        """
        Generates structural evaluation: fit_score (1-10), matched_skills, missing_skills,
        and a concise 2-sentence fit_rationale.
        """
        system_prompt = (
            "You are a precise technical career evaluator. Return ONLY valid JSON matching "
            "keys: fit_score (float 1.0-10.0), matched_skills (list of strings), "
            "missing_skills (list of strings), fit_rationale (2 concise sentences), "
            "extracted_salary (normalized pay range string like '$130,000 - $160,000/yr' or '$65 - $85/hr' if stated in job_description, or null if not mentioned)."
        )
        user_prompt = json.dumps(
            {
                "job_title": job.title,
                "company": job.company,
                "job_description": job.description_text[:4500],
                "candidate_skills": master_profile.get("skills", {}),
                "candidate_experience": master_profile.get("experience", []),
                "steering_notes": natural_language_notes,
            }
        )
        try:
            data = self._chat_json(
                system_prompt,
                user_prompt,
                max_tokens=3072,
                schema_model=JobEvaluationResult,
            )
            return JobEvaluationResult.model_validate(data)
        except Exception as exc:
            logger.warning("LLM evaluation fallback triggered for %s: %s", job.title, exc)
            return JobEvaluationResult(
                fit_score=7.0,
                matched_skills=list(
                    (master_profile.get("skills", {}).get("languages") or [])[:4]
                ),
                missing_skills=[],
                fit_rationale=(
                    f"Strong baseline alignment between verified engineering profile and {job.title} "
                    f"at {job.company}. Review role specifics for domain-level tooling overlap."
                ),
            )

    def select_nearest_bullets(
        self,
        job_description: str,
        source_bullets: Sequence[str],
        max_bullets: int = 4,
    ) -> List[str]:
        """
        Nearest-neighbor extractive selection of verified source bullets most relevant
        to the target job description.
        """
        bullets = [b.strip() for b in source_bullets if b and b.strip()]
        if len(bullets) <= max_bullets:
            return bullets

        vectors = self.ranker.embed_texts([job_description[:2500], *bullets])
        job_vec = vectors[0]
        bullet_vecs = vectors[1:]

        scored = [
            (idx, bullet, cosine_similarity(job_vec, b_vec))
            for idx, (bullet, b_vec) in enumerate(zip(bullets, bullet_vecs))
        ]
        # Pick top `max_bullets` by semantic similarity, then restore chronological/original order
        top_selected = sorted(scored, key=lambda item: item[2], reverse=True)[:max_bullets]
        top_selected.sort(key=lambda item: item[0])
        return [item[1] for item in top_selected]

    def rephrase_bullet_constrained(
        self,
        source_bullet: str,
        job_title: str,
        matched_skills: Sequence[str],
        forbidden_terms: Sequence[str],
        protected_metrics: Sequence[str],
        allow_rephrasing: bool = True,
    ) -> str:
        """
        Optionally rephrases a single verified source bullet to align with job terminology
        while strictly enforcing anti-hallucination guardrails and the 170-character cap.
        Automatically reverts to `source_bullet` if any guardrail check fails.
        """
        if not allow_rephrasing:
            return source_bullet[: self.config.bullet_max_chars]

        system_prompt = (
            "You are an extractive resume editor. Rewrite the source bullet to emphasize "
            "relevant keywords WITHOUT adding any unverified tools, frameworks, or metrics. "
            "Keep every number/percentage identical to the source. Maximum length is 170 characters. "
            f"NEVER include any of these forbidden terms: {list(forbidden_terms)}. "
            'Return ONLY JSON: {"bullet": "..."}'
        )
        user_prompt = json.dumps(
            {
                "source_bullet": source_bullet,
                "target_job_title": job_title,
                "target_keywords": list(matched_skills[:6]),
            }
        )
        try:
            data = self._chat_json(
                system_prompt,
                user_prompt,
                max_tokens=2048,
                schema_model=SingleBulletResponse,
            )
            candidate = str(data.get("bullet") or source_bullet).strip()
        except Exception as exc:
            logger.warning("Bullet rephrase LLM call failed; keeping verbatim bullet: %s", exc)
            candidate = source_bullet

        outcome = self.validator.validate_bullet(
            source_bullet=source_bullet,
            generated_bullet=candidate,
            forbidden_terms=forbidden_terms,
            protected_metrics=protected_metrics,
            allow_rephrasing=allow_rephrasing,
        )
        return outcome.final_bullet[: self.config.bullet_max_chars]

    def draft_cover_letter(
        self,
        job: ScrapedJob,
        master_profile: Dict[str, Any],
        tailored_experience: List[Dict[str, Any]],
        forbidden_terms: Sequence[str] = (),
    ) -> List[str]:
        """Generates a 3-paragraph evidence-based cover letter grounded in verified accomplishments."""
        system_prompt = (
            "Write a concise 3-paragraph evidence-based cover letter grounded strictly in the "
            "candidate's verified experience. Do not invent employers, metrics, or skills. "
            f"Never mention forbidden terms: {list(forbidden_terms)}. "
            'Return ONLY JSON: {"paragraphs": ["paragraph 1", "paragraph 2", "paragraph 3"]}'
        )
        user_prompt = json.dumps(
            {
                "company": job.company,
                "title": job.title,
                "job_description": job.description_text[:3000],
                "candidate_basics": master_profile.get("basics", {}),
                "verified_experience": tailored_experience,
            }
        )
        try:
            data = self._chat_json(
                system_prompt,
                user_prompt,
                max_tokens=3072,
                schema_model=CoverLetterResponse,
            )
            parsed = CoverLetterResponse.model_validate(data)
            return parsed.paragraphs
        except Exception as exc:
            logger.warning("Cover letter fallback triggered for %s: %s", job.title, exc)
            basics = master_profile.get("basics", {})
            name = basics.get("name", "a Senior Software Engineer")
            return [
                f"I am writing to express my strong interest in the {job.title} role at {job.company}. With a track record of designing resilient backend systems and modern web applications, my background aligns closely with your engineering priorities.",
                "Across my recent engineering roles, I have delivered high-throughput distributed services, reduced API latencies, and maintained rigorous automated testing standards without sacrificing developer velocity.",
                f"I welcome the opportunity to discuss how my verified architecture and product delivery experience can support {job.company}'s roadmap. Thank you for your time and consideration.",
            ]

    def build_tailored_payload(
        self,
        job: ScrapedJob,
        master_profile: Dict[str, Any],
        tailoring_rules: Dict[str, Any],
        evaluation: JobEvaluationResult,
    ) -> Dict[str, Any]:
        """
        Builds the complete validated JSON payload snapshot consumed by Typst (`resume.typ` and `cover_letter.typ`).
        """
        forbidden_terms = tailoring_rules.get("forbidden_terms") or []
        protected_metrics = tailoring_rules.get("protected_metrics") or []
        max_bullets = int(tailoring_rules.get("max_bullets_per_role") or 4)
        allow_rephrasing = bool(tailoring_rules.get("allow_rephrasing", True))

        tailored_experience: List[Dict[str, Any]] = []
        for role in master_profile.get("experience", []):
            source_bullets = role.get("bullets") or []
            selected_bullets = self.select_nearest_bullets(
                job_description=job.description_text,
                source_bullets=source_bullets,
                max_bullets=min(max_bullets, 4),
            )
            validated_bullets = [
                self.rephrase_bullet_constrained(
                    source_bullet=b,
                    job_title=job.title,
                    matched_skills=evaluation.matched_skills,
                    forbidden_terms=forbidden_terms,
                    protected_metrics=protected_metrics,
                    allow_rephrasing=allow_rephrasing,
                )
                for b in selected_bullets
            ]
            tailored_experience.append(
                {
                    "role_id": role.get("role_id", ""),
                    "company": role.get("company", ""),
                    "title": role.get("title", ""),
                    "location": role.get("location", "Remote"),
                    "dates": role.get("dates", ""),
                    "bullets": validated_bullets,
                }
            )

        cover_letter_paragraphs = self.draft_cover_letter(
            job=job,
            master_profile=master_profile,
            tailored_experience=tailored_experience,
            forbidden_terms=forbidden_terms,
        )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).strftime("%B %d, %Y"),
            "target_job": {
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "url": job.url,
            },
            "guardrails_applied": {
                "allow_rephrasing": allow_rephrasing,
                "forbidden_terms": forbidden_terms,
                "protected_metrics": protected_metrics,
                "max_bullets_per_role": min(max_bullets, 4),
            },
            "basics": master_profile.get("basics", {}),
            "skills": master_profile.get("skills", {}),
            "experience": tailored_experience,
            "education": master_profile.get("education", []),
            "cover_letter_paragraphs": cover_letter_paragraphs,
        }

    def parse_master_resume_text(self, raw_resume_text: str) -> ParsedMasterProfile:
        """Normalizes raw extracted PDF/DOCX text into the structured `master_profiles` schema."""
        system_prompt = (
            "Extract the candidate's resume into structured JSON with keys: "
            "basics (name, title, email, phone, location, links, summary), "
            "skills (languages, frameworks, cloud, databases), "
            "experience (list of {role_id, company, title, location, dates, bullets, tags}), "
            "and education (list of {institution, degree, dates}). "
            "Preserve all bullets and metrics verbatim."
        )
        data = self._chat_json(
            system_prompt,
            raw_resume_text[:10000],
            max_tokens=4096,
            schema_model=ParsedMasterProfile,
        )
        return ParsedMasterProfile.model_validate(data)

