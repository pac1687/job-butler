import { redirect } from "next/navigation";
import { auth, isAuthorizedAdminEmail } from "@/auth";
import { Navbar } from "@/components/Navbar";
import {
  getSql,
  type JobPreferencesRecord,
  type MasterProfileRecord,
  type TailoringRulesRecord,
} from "@/lib/db";
import {
  DEFAULT_MASTER_PROFILE,
  DEFAULT_PREFERENCES,
  DEFAULT_TAILORING_RULES,
} from "@/lib/mock-data";
import { ProfileEditorClient } from "./ProfileEditorClient";

async function loadProfileAndRules(): Promise<{
  profile: MasterProfileRecord;
  rules: TailoringRulesRecord;
  preferences: JobPreferencesRecord;
}> {
  if (!process.env.DATABASE_URL) {
    return {
      profile: DEFAULT_MASTER_PROFILE,
      rules: DEFAULT_TAILORING_RULES,
      preferences: DEFAULT_PREFERENCES,
    };
  }
  try {
    const sql = getSql();
    const profRows = await sql`
      SELECT id, basics, skills, experience, education, uploaded_at
      FROM master_profiles
      WHERE is_active = TRUE
      ORDER BY uploaded_at DESC
      LIMIT 1
    `;
    const ruleRows = await sql`
      SELECT id, forbidden_terms, protected_metrics, max_bullets_per_role, allow_rephrasing, lock_company_names, lock_dates
      FROM tailoring_rules
      ORDER BY id DESC
      LIMIT 1
    `;
    const prefRows = await sql`
      SELECT id, positive_titles, negative_title_keywords, natural_language_notes, min_semantic_score, ats_boards
      FROM job_preferences
      ORDER BY id DESC
      LIMIT 1
    `;
    return {
      profile: (profRows[0] as unknown as MasterProfileRecord) || DEFAULT_MASTER_PROFILE,
      rules: (ruleRows[0] as unknown as TailoringRulesRecord) || DEFAULT_TAILORING_RULES,
      preferences: (prefRows[0] as unknown as JobPreferencesRecord) || DEFAULT_PREFERENCES,
    };
  } catch {
    return {
      profile: DEFAULT_MASTER_PROFILE,
      rules: DEFAULT_TAILORING_RULES,
      preferences: DEFAULT_PREFERENCES,
    };
  }
}

export default async function ProfilePage() {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    redirect("/demo");
  }

  const { profile, rules, preferences } = await loadProfileAndRules();

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar isAuthenticatedAdmin={true} userEmail={session?.user?.email} />
      <main className="max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-white">
            Master Resume, Discovery Filters &amp; Guardrails
          </h1>
          <p className="text-sm text-slate-400">
            Configure location/remote job discovery filters, company diversity limits, anti-hallucination guardrails, and verified source bullets.
          </p>
        </div>

        <ProfileEditorClient
          initialProfile={profile}
          initialRules={rules}
          initialPreferences={preferences}
        />
      </main>
    </div>
  );
}

