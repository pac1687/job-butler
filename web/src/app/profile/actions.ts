"use server";

import { revalidatePath } from "next/cache";
import { auth, isAuthorizedAdminEmail } from "@/auth";
import { getSql } from "@/lib/db";

export async function uploadAndEnqueueMasterResumeAction(formData: FormData) {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    throw new Error("Unauthorized");
  }

  const file = formData.get("resumeFile") as File | null;
  if (!file) {
    throw new Error("No resume file uploaded");
  }

  const arrayBuffer = await file.arrayBuffer();
  const buffer = Buffer.from(arrayBuffer);
  const fileName = file.name.toLowerCase();
  let extractedText = "";
  let fileBase64: string | null = null;

  if (fileName.endsWith(".pdf")) {
    try {
      const pdfParse = (await import("pdf-parse")).default;
      const parsed = await pdfParse(buffer);
      extractedText = (parsed.text || "").trim();
    } catch (err) {
      // pdf-parse uses legacy pdf.js v1.10.100 which can throw "bad XRef entry" on modern PDFs;
      // fall back to sending base64 bytes so the Python worker extracts text via pypdf v5+.
      console.warn("pdf-parse failed, delegating PDF extraction to worker pypdf:", err);
    }
    if (!extractedText) {
      fileBase64 = buffer.toString("base64");
    }
  } else if (fileName.endsWith(".docx")) {
    const mammoth = await import("mammoth");
    const result = await mammoth.extractRawText({ buffer });
    extractedText = result.value;
  } else {
    extractedText = buffer.toString("utf-8");
  }

  const sql = getSql();
  await sql`
    INSERT INTO job_task_queue (task_type, payload, status)
    VALUES (
      'PARSE_MASTER_RESUME',
      ${JSON.stringify({
        filename: file.name,
        raw_text: extractedText,
        file_base64: fileBase64,
      })}::jsonb,
      'PENDING'
    )
  `;
  revalidatePath("/profile");
}

export async function updateTailoringRulesAction(payload: {
  forbidden_terms: string[];
  protected_metrics: string[];
  max_bullets_per_role: number;
  allow_rephrasing: boolean;
}) {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    throw new Error("Unauthorized");
  }

  const sql = getSql();
  await sql`
    INSERT INTO tailoring_rules (id, forbidden_terms, protected_metrics, max_bullets_per_role, allow_rephrasing, updated_at)
    VALUES (
      1,
      ${JSON.stringify(payload.forbidden_terms)}::jsonb,
      ${JSON.stringify(payload.protected_metrics)}::jsonb,
      ${payload.max_bullets_per_role},
      ${payload.allow_rephrasing},
      NOW()
    )
    ON CONFLICT (id) DO UPDATE
    SET forbidden_terms = EXCLUDED.forbidden_terms,
        protected_metrics = EXCLUDED.protected_metrics,
        max_bullets_per_role = EXCLUDED.max_bullets_per_role,
        allow_rephrasing = EXCLUDED.allow_rephrasing,
        updated_at = NOW()
  `;
  revalidatePath("/profile");
}

export async function saveMasterProfileDirectAction(profile: {
  basics: Record<string, unknown>;
  skills: Record<string, string[]>;
  experience: unknown[];
  education: unknown[];
}) {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    throw new Error("Unauthorized");
  }

  const sql = getSql();
  await sql`UPDATE master_profiles SET is_active = FALSE WHERE is_active = TRUE`;
  await sql`
    INSERT INTO master_profiles (is_active, basics, skills, experience, education)
    VALUES (
      TRUE,
      ${JSON.stringify(profile.basics)}::jsonb,
      ${JSON.stringify(profile.skills)}::jsonb,
      ${JSON.stringify(profile.experience)}::jsonb,
      ${JSON.stringify(profile.education)}::jsonb
    )
  `;
  revalidatePath("/profile");
}
