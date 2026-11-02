"""Typst PDF compilation wrapper with strict single-page assertion (SPEC.md Section 3.5)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
from pypdf import PdfReader

from worker.validator import merge_two_bullets

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


class PageBudgetExceededError(RuntimeError):
    """Raised when a compiled Typst PDF exceeds the strict 1-page budget."""


class TypstCompilationError(RuntimeError):
    """Raised when the Typst CLI binary fails or is missing."""


def verify_single_page_pdf(pdf_path: Path | str) -> int:
    """
    Reads the compiled PDF via pypdf.PdfReader and asserts len(reader.pages) == 1.
    Raises PageBudgetExceededError if page count > 1.
    """
    reader = PdfReader(str(pdf_path))
    page_count = len(reader.pages)
    if page_count > 1:
        raise PageBudgetExceededError(
            f"Compiled PDF '{pdf_path}' has {page_count} pages; maximum allowed is 1 page."
        )
    return page_count


class TypstTypesetter:
    """Compiles resume and cover letter PDFs via Typst CLI and enforces the 1-page guarantee."""

    def __init__(
        self,
        templates_dir: Optional[Path] = None,
        typst_bin: Optional[str] = None,
    ) -> None:
        self.templates_dir = templates_dir or DEFAULT_TEMPLATES_DIR
        self.typst_bin = typst_bin or shutil.which("typst") or "typst"

    def compile_template(
        self,
        template_name: str,
        payload: Dict[str, Any],
        output_pdf_path: Path | str,
        enforce_single_page: bool = True,
    ) -> Path:
        """
        Compiles `template_name` (e.g. 'resume.typ' or 'cover_letter.typ') with `payload`
        injected via `--input data=payload.json` and verifies the resulting PDF is 1 page.
        """
        template_path = self.templates_dir / template_name
        if not template_path.exists():
            raise FileNotFoundError(f"Typst template not found at {template_path}")

        out_path = Path(output_pdf_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp_dir:
            payload_path = Path(tmp_dir) / "payload.json"
            payload_json_str = json.dumps(payload, ensure_ascii=False)
            payload_path.write_text(payload_json_str, encoding="utf-8")

            cmd = [
                self.typst_bin,
                "compile",
                "--input",
                f"data={payload_json_str}",
                str(template_path),
                str(out_path),
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                raise TypstCompilationError(
                    f"Typst compilation failed (exit {result.returncode}): {result.stderr.strip()}"
                )

        if enforce_single_page:
            verify_single_page_pdf(out_path)

        return out_path

    def compile_resume_with_auto_trim(
        self,
        payload: Dict[str, Any],
        output_pdf_path: Path | str,
    ) -> Path:
        """
        Compiles `resume.typ` and, if `PageBudgetExceededError` occurs, progressively adjusts
        compact layout density and trims trailing bullets from older roles until the document
        fits on a single page (FR-2.6).
        """
        working_payload = json.loads(json.dumps(payload))
        max_attempts = 16
        for attempt in range(max_attempts):
            try:
                return self.compile_template(
                    "resume.typ",
                    working_payload,
                    output_pdf_path,
                    enforce_single_page=True,
                )
            except PageBudgetExceededError:
                if attempt == max_attempts - 1:
                    raise
                logger.warning(
                    "Resume exceeded 1 page on attempt %d; adjusting layout/bullets to fit 1-page budget.",
                    attempt + 1,
                )
                # Step 1: First reduce one bullet from the oldest role with >1 bullet.
                # Only combine if this role originally had exactly 2 bullets in the master profile
                # and has a verified combined_bullet (e.g. ANPAC). For roles with 3+ distinct project bullets
                # (like SoftVu), drop trailing lower-ranked bullets so each project remains clean and standalone.
                trimmed_bullet = False
                for role in reversed(working_payload.get("experience", [])):
                    bullets = role.get("bullets") or []
                    if len(bullets) > 1:
                        if (
                            len(bullets) == 2
                            and role.get("source_bullet_count", len(bullets)) == 2
                            and role.get("combined_bullet")
                        ):
                            role["bullets"] = [role["combined_bullet"]]
                        else:
                            role["bullets"] = bullets[:-1]
                        trimmed_bullet = True
                        break

                # Step 2: Escalate compact_level (tighter font & margins) as attempts progress
                current_compact = int(working_payload.get("compact_level") or 0)
                if current_compact < 2:
                    working_payload["compact_level"] = current_compact + 1

                # Step 3: If all roles are down to 1 bullet and still >1 page, drop oldest role or trim summary
                if not trimmed_bullet:
                    roles = working_payload.get("experience", [])
                    if len(roles) > 2:
                        working_payload["experience"] = roles[:-1]
                    elif working_payload.get("basics", {}).get("summary"):
                        working_payload["basics"]["summary"] = ""
        return Path(output_pdf_path)

    def compile_cover_letter_with_auto_trim(
        self,
        payload: Dict[str, Any],
        output_pdf_path: Path | str,
    ) -> Path:
        """Compiles `cover_letter.typ` and switches to compact margins/font if it exceeds 1 page."""
        working_payload = json.loads(json.dumps(payload))
        for attempt in range(3):
            try:
                return self.compile_template(
                    "cover_letter.typ",
                    working_payload,
                    output_pdf_path,
                    enforce_single_page=True,
                )
            except PageBudgetExceededError:
                if attempt == 2:
                    raise
                working_payload["compact_level"] = attempt + 1
        return Path(output_pdf_path)

