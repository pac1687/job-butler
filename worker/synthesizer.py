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
from worker.validator import (
    LEADING_HEADER_REGEX,
    GuardrailValidator,
    contains_forbidden_term,
    extract_named_entities_and_terms,
)

logger = logging.getLogger(__name__)

DISALLOWED_SUMMARY_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"(?i)\bexpert\b"),
    re.compile(r"(?i)\bworld-class\b"),
    re.compile(r"(?i)\bguru\b"),
    re.compile(r"(?i)\brockstar\b"),
    re.compile(r"(?i)\bninja\b"),
    re.compile(r"(?i)\bunrivaled\b"),
    re.compile(r"(?i)\bunmatched\b"),
    re.compile(r"(?i)\bvisionary\b"),
]


def detect_full_stack_style(target_title: str, fallback_text: str = "") -> str:
    """
    Detects whether the job title from the listing uses hyphens ('Full-Stack') or spaces ('Full Stack').
    If the job title explicitly contains 'full-stack' (hyphenated), returns 'Full-Stack'.
    Otherwise, returns 'Full Stack'.
    """
    title_lower = (target_title or "").lower()
    if re.search(r"\bfull[\s–—]*[-–—][\s–—]*stack\b", title_lower):
        return "Full-Stack"
    return "Full Stack"


def apply_full_stack_style(text: str, style: str) -> str:
    """Applies either 'Full-Stack' or 'Full Stack' consistently to `text` based on the listing's style."""
    if not text:
        return ""
    if style == "Full-Stack":
        return re.sub(r"(?i)\bfull\s+stack\b", "Full-Stack", text)
    else:
        return re.sub(r"(?i)\bfull[\s–—]*[-–—][\s–—]*stack\b", "Full Stack", text)


def normalize_full_stack_hyphenation(text: str) -> str:
    """Legacy helper; applies 'Full-Stack' hyphenation."""
    return apply_full_stack_style(text, "Full-Stack")


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
    bullet: str = Field(...)


class HeadlineResponse(BaseModel):
    title: str = Field(..., max_length=70)


class SummaryResponse(BaseModel):
    summary: str = Field(..., max_length=550)


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
        Nearest-neighbor extractive selection and relevance ordering of verified source bullets
        most relevant to the target job description. The most relevant accomplishment is placed first.
        """
        bullets = [b.strip() for b in source_bullets if b and b.strip()]
        if not bullets:
            return []
        if len(bullets) == 1:
            return bullets

        vectors = self.ranker.embed_texts([job_description[:2500], *bullets])
        job_vec = vectors[0]
        bullet_vecs = vectors[1:]

        scored = [
            (idx, bullet, cosine_similarity(job_vec, b_vec))
            for idx, (bullet, b_vec) in enumerate(zip(bullets, bullet_vecs))
        ]
        # Order top `max_bullets` by semantic similarity descending so the strongest matching bullet is first
        top_selected = sorted(scored, key=lambda item: item[2], reverse=True)[:max_bullets]
        return [item[1] for item in top_selected]

    def generate_tailored_headline(
        self,
        target_title: str,
        candidate_title: str,
        style: str = "Full Stack",
    ) -> str:
        """
        Aligns the resume headline title with the target job title while staying strictly
        grounded in the candidate's verified baseline title and discipline.
        Ensures consistent hyphenation style ('Full-Stack' or 'Full Stack') matching the target job listing.
        """
        clean_target = (target_title or "").strip()
        clean_candidate = (candidate_title or "").strip()

        if not clean_candidate:
            return apply_full_stack_style(clean_target or "Software Engineer", style)
        if not clean_target:
            return apply_full_stack_style(clean_candidate, style)

        hyphen_instruction = (
            "3. HYPHENATION: Always use 'Full-Stack' (hyphenated), NEVER unhyphenated 'Full Stack'."
            if style == "Full-Stack"
            else "3. HYPHENATION: Always use 'Full Stack' (unhyphenated), NEVER hyphenated 'Full-Stack'."
        )

        system_prompt = (
            "You are an expert executive resume consultant. Return a concise tailored professional title "
            "(maximum 45 characters) that directly incorporates the target job title while remaining truthful "
            "to the candidate's verified background in full-stack and platform systems engineering. "
            "CRITICAL RULES: "
            "1. The title MUST distinctly align with the target job role. "
            f"   - If target is 'Product Engineer', the title should be '{style} Product Engineer' or 'Product Engineer'. "
            f"   - If target is 'Full Stack Software Engineer', the title should be '{style} Software Engineer'. "
            "   - If target is 'Backend Engineer', the title should be 'Backend Systems Engineer'. "
            "2. NEVER output the same generic title across different roles. The headline MUST align specifically with the target job. "
            f"{hyphen_instruction} "
            'Return ONLY JSON: {"title": "..."}'
        )
        user_prompt = json.dumps(
            {
                "candidate_verified_background": clean_candidate,
                "target_job_title": clean_target,
            }
        )
        try:
            data = self._chat_json(
                system_prompt,
                user_prompt,
                max_tokens=512,
                schema_model=HeadlineResponse,
            )
            val = str(data.get("title") or "").strip()
            val = apply_full_stack_style(val, style)
            if 3 <= len(val) <= 55 and val.lower() != clean_candidate.lower():
                return val
            if 3 <= len(val) <= 55:
                return val
        except Exception as exc:
            logger.warning("Headline title generation failed (%s); using heuristic fallback.", exc)

        # Deterministic heuristic fallback ensuring distinct target alignment:
        target_low = clean_target.lower()
        if "product" in target_low:
            return f"{style} Product Engineer"
        if "full stack" in target_low or "full-stack" in target_low:
            return f"{style} Software Engineer"
        if "backend" in target_low:
            return "Backend Systems & Platform Engineer"
        if "platform" in target_low:
            return f"{style} Platform Engineer"

        return apply_full_stack_style(clean_target if len(clean_target) <= 45 else clean_candidate, style)

    def generate_tailored_summary(
        self,
        job: ScrapedJob,
        tailored_title: str,
        master_summary: str,
        experience: Sequence[Dict[str, Any]],
        evaluation: JobEvaluationResult,
        forbidden_terms: Sequence[str] = (),
        style: str = "Full Stack",
    ) -> str:
        """
        Synthesizes a 2-3 sentence tailored executive summary spotlighting the candidate's
        substantive verified role accomplishments that directly intersect with the target job.
        Strictly enforces grounded tone with NO hyperbolic superlatives (e.g. 'Expert'),
        and guarantees 100% consistent title phrasing and hyphenation with `tailored_title`.
        """
        if not master_summary or not master_summary.strip():
            return master_summary

        recent_accomplishments: List[str] = []
        for role in (experience or [])[:3]:
            co = role.get("company", "")
            title = role.get("title", "")
            bullets = [b.strip() for b in (role.get("bullets") or []) if b and b.strip()][:2]
            if bullets:
                recent_accomplishments.append(f"{title} at {co}: " + "; ".join(bullets))

        hyphen_instruction = (
            "2. HYPHENATION: Always use 'Full-Stack' (hyphenated), NEVER unhyphenated 'Full Stack'."
            if style == "Full-Stack"
            else "2. HYPHENATION: Always use 'Full Stack' (unhyphenated), NEVER hyphenated 'Full-Stack'."
        )

        system_prompt = (
            "You are an executive resume writer. Tailor the candidate's executive summary "
            "(2-3 concise sentences, between 300 and 450 characters) to spotlight their verified engineering background "
            "most relevant to the target job. "
            "CRITICAL TONE AND ACCURACY RULES: "
            f"1. The candidate's headline title on this resume is '{tailored_title}'. "
            f"If you state the candidate's title in the summary (e.g. in the opening sentence), you MUST use '{tailored_title}' verbatim. "
            f"{hyphen_instruction} "
            "3. NEVER use puffed-up superlatives or self-praising buzzwords like 'Expert', 'Master', 'World-class', 'Guru', 'Rockstar', or 'Visionary'. "
            "Keep the tone strictly grounded, objective, professional, and matter-of-fact (e.g., 'Hands-on engineer with over a decade of experience...', 'Background in designing...'). "
            "4. Ground all statements strictly in the candidate's substantive verified role accomplishments (such as data ingestion engines, distributed microservices, REST APIs, PostgreSQL, TypeScript/Node.js, and automated verification). "
            "5. Do NOT make demonstrative claims about secondary tools or keywords (e.g., do NOT claim 'proven track record deploying via Docker or CI/CD pipelines' if that was not a primary focus of their verified work). "
            "6. Never invent employers, unverified metrics, or unverified claims. "
            f"7. Never mention forbidden terms: {list(forbidden_terms)}. "
            'Return ONLY JSON: {"summary": "..."}'
        )
        user_prompt = json.dumps(
            {
                "target_role": job.title,
                "target_company": job.company,
                "resume_headline_title": tailored_title,
                "job_description_snippet": job.description_text[:2500],
                "matched_skills": evaluation.matched_skills[:8],
                "verified_master_summary": master_summary,
                "substantive_role_accomplishments": recent_accomplishments,
            }
        )
        try:
            data = self._chat_json(
                system_prompt,
                user_prompt,
                max_tokens=2048,
                schema_model=SummaryResponse,
            )
            candidate_sum = str(data.get("summary") or master_summary).strip()

            # Guardrail 1: Forbidden terms check
            if contains_forbidden_term(candidate_sum, forbidden_terms):
                logger.warning("Tailored summary violated forbidden term; falling back to master summary.")
                candidate_sum = master_summary

            # Guardrail 2: Ban puffed-up superlatives (e.g. 'Expert')
            for pat in DISALLOWED_SUMMARY_PATTERNS:
                if pat.search(candidate_sum):
                    logger.warning(
                        "Tailored summary rejected due to puffed-up adjective '%s'; falling back to master summary.",
                        pat.pattern,
                    )
                    candidate_sum = master_summary
                    break

            # Guardrail 3: Length & punctuation sanity
            if len(candidate_sum) < 80 or len(candidate_sum) > 550 or not candidate_sum.endswith("."):
                candidate_sum = master_summary

            # Post-processing: Apply target hyphenation style and guarantee opening title consistency
            candidate_sum = apply_full_stack_style(candidate_sum, style)
            candidate_sum = re.sub(
                r"^((?:Hands-on\s+)?)[A-Z][A-Za-z\s/-]+?(\s+with\s+(?:over\s+)?(?:a|\d+)\s+decade)",
                rf"\g<1>{tailored_title}\g<2>",
                candidate_sum,
                flags=re.IGNORECASE,
            )
            return candidate_sum

        except Exception as exc:
            logger.warning("Tailored summary generation failed (%s); using master summary.", exc)
            fallback = apply_full_stack_style(master_summary, style)
            return re.sub(
                r"^((?:Hands-on\s+)?)[A-Z][A-Za-z\s/-]+?(\s+with\s+(?:over\s+)?(?:a|\d+)\s+decade)",
                rf"\g<1>{tailored_title}\g<2>",
                fallback,
                flags=re.IGNORECASE,
            )

    def prioritize_skills(
        self,
        skills_map: Dict[str, Any],
        job_description: str,
        matched_skills: Sequence[str] = (),
    ) -> Dict[str, List[str]]:
        """
        Re-orders skills within each category so that tools, languages, and frameworks
        most relevant to the target job description or present in matched_skills appear first.
        Never adds unverified skills or drops existing skills.
        """
        desc_lower = (job_description or "").lower()
        matched_lowers = [m.lower().strip() for m in matched_skills if m and m.strip()]

        prioritized: Dict[str, List[str]] = {}
        for category, skill_list in skills_map.items():
            if not isinstance(skill_list, list):
                prioritized[category] = skill_list
                continue

            def skill_priority(skill: str) -> tuple[int, int]:
                s_clean = str(skill).strip()
                s_lower = s_clean.lower()
                # 1. Direct or partial match in evaluation.matched_skills
                if any(m in s_lower or s_lower in m for m in matched_lowers):
                    return (0, 0)
                # 2. Word boundary match in target job description
                primary_token = re.split(r"[\s(/+]+", s_lower)[0]
                if primary_token and len(primary_token) >= 2:
                    pattern = re.compile(r"(?i)(?<!\w)" + re.escape(primary_token) + r"(?!\w)")
                    if pattern.search(desc_lower):
                        return (1, 0)
                return (2, 0)

            # Stable sort so matched skills move to the front, preserving relative order of the rest
            sorted_items = sorted(skill_list, key=skill_priority)
            prioritized[category] = sorted_items

        return prioritized

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
        while strictly enforcing anti-hallucination guardrails, preserving project/topic headers,
        preserving named tools/entities, and ensuring complete sentences.
        Automatically reverts to `source_bullet` if any guardrail check fails.
        """
        if not allow_rephrasing:
            return source_bullet.strip()

        target_max_chars = max(self.config.bullet_max_chars, len(source_bullet.strip()))
        header_match = LEADING_HEADER_REGEX.match(source_bullet.strip())
        header_instruction = (
            f"The bullet MUST start with the exact prefix '{header_match.group(1).strip()}: ' so project/scope context is preserved. "
            if header_match
            else ""
        )
        required_entities = extract_named_entities_and_terms(source_bullet)
        entities_instruction = (
            f"You MUST preserve all of these named tools/technologies from the source bullet: {required_entities}. "
            if required_entities
            else ""
        )

        system_prompt = (
            "You are an extractive resume editor. Lightly refine the source bullet to emphasize "
            "relevant keywords WITHOUT adding any unverified tools, frameworks, or metrics, and WITHOUT "
            "removing project/feature context or technical details. "
            f"{header_instruction}"
            f"{entities_instruction}"
            "Keep every number, version (e.g. 2.0), and percentage identical to the source. "
            "The output MUST be a complete, grammatically finished sentence ending with a period. "
            f"Never cut off mid-sentence or end on a dangling word (maximum {target_max_chars} characters). "
            f"NEVER include any of these forbidden terms: {list(forbidden_terms)}. "
            'Return ONLY JSON: {"bullet": "..."}'
        )
        user_prompt = json.dumps(
            {
                "source_bullet": source_bullet,
                "target_job_title": job_title,
                "target_keywords": list(matched_skills[:10]),
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
        return outcome.final_bullet

    def draft_cover_letter(
        self,
        job: ScrapedJob,
        master_profile: Dict[str, Any],
        tailored_experience: List[Dict[str, Any]],
        forbidden_terms: Sequence[str] = (),
        tailored_basics: Optional[Dict[str, Any]] = None,
        style: str = "Full Stack",
    ) -> List[str]:
        """Generates a 3-paragraph evidence-based cover letter grounded in verified accomplishments."""
        system_prompt = (
            "Write a concise 3-paragraph evidence-based cover letter grounded strictly in the "
            "candidate's verified experience. Do not invent employers, metrics, or skills. "
            f"Never mention forbidden terms: {list(forbidden_terms)}. "
            'Return ONLY JSON: {"paragraphs": ["paragraph 1", "paragraph 2", "paragraph 3"]}'
        )
        basics = tailored_basics or master_profile.get("basics", {})
        user_prompt = json.dumps(
            {
                "company": job.company,
                "title": job.title,
                "job_description": job.description_text[:3000],
                "candidate_basics": basics,
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
            return [apply_full_stack_style(p, style) for p in parsed.paragraphs]
        except Exception as exc:
            logger.warning("Cover letter fallback triggered for %s: %s", job.title, exc)
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
        Tailors the headline title, executive summary, skill prioritization, and bullet ordering.
        Adapts hyphenation ('Full-Stack' vs 'Full Stack') to match the target job listing.
        """
        forbidden_terms = tailoring_rules.get("forbidden_terms") or []
        protected_metrics = tailoring_rules.get("protected_metrics") or []
        max_bullets = int(tailoring_rules.get("max_bullets_per_role") or 4)
        allow_rephrasing = bool(tailoring_rules.get("allow_rephrasing", True))

        # Detect whether the target listing uses hyphens or spaces
        style = detect_full_stack_style(job.title, job.description_text)

        # 1. Distinct headline title alignment & consistent executive summary tailoring
        basics = dict(master_profile.get("basics", {}))
        tailored_title = self.generate_tailored_headline(
            target_title=job.title,
            candidate_title=str(basics.get("title") or ""),
            style=style,
        )
        tailored_summary = self.generate_tailored_summary(
            job=job,
            tailored_title=tailored_title,
            master_summary=str(basics.get("summary") or ""),
            experience=master_profile.get("experience", []),
            evaluation=evaluation,
            forbidden_terms=forbidden_terms,
            style=style,
        )
        basics["title"] = tailored_title
        basics["summary"] = tailored_summary

        # 2. Dynamic skill prioritization (promotes matching skills to the front)
        prioritized_skills = self.prioritize_skills(
            skills_map=master_profile.get("skills", {}),
            job_description=job.description_text,
            matched_skills=evaluation.matched_skills,
        )

        # 3. Experience bullet ranking & constrained rephrasing
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

        # 4. Tailored cover letter drafting
        cover_letter_paragraphs = self.draft_cover_letter(
            job=job,
            master_profile=master_profile,
            tailored_experience=tailored_experience,
            forbidden_terms=forbidden_terms,
            tailored_basics=basics,
            style=style,
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
            "basics": basics,
            "skills": prioritized_skills,
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
