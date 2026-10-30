"use server";

import { revalidatePath } from "next/cache";
import { auth, isAuthorizedAdminEmail } from "@/auth";
import { getSql } from "@/lib/db";

export async function updatePreferencesAction(payload: {
  positive_titles: string[];
  negative_title_keywords: string[];
  natural_language_notes: string;
  min_semantic_score: number;
}) {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    throw new Error("Unauthorized");
  }

  const sql = getSql();
  await sql`
    INSERT INTO job_preferences (
      id,
      positive_titles,
      negative_title_keywords,
      natural_language_notes,
      min_semantic_score,
      updated_at
    )
    VALUES (
      1,
      ${JSON.stringify(payload.positive_titles)}::jsonb,
      ${JSON.stringify(payload.negative_title_keywords)}::jsonb,
      ${payload.natural_language_notes},
      ${payload.min_semantic_score},
      NOW()
    )
    ON CONFLICT (id) DO UPDATE
    SET positive_titles = EXCLUDED.positive_titles,
        negative_title_keywords = EXCLUDED.negative_title_keywords,
        natural_language_notes = EXCLUDED.natural_language_notes,
        min_semantic_score = EXCLUDED.min_semantic_score,
        updated_at = NOW()
  `;
  revalidatePath("/preferences");
}

