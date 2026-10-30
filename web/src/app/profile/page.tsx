import { redirect } from "next/navigation";
import { auth, isAuthorizedAdminEmail } from "@/auth";
import { Navbar } from "@/components/Navbar";
import {
  getSql,
  type MasterProfileRecord,
  type TailoringRulesRecord,
} from "@/lib/db";
import {
  DEFAULT_MASTER_PROFILE,
  DEFAULT_TAILORING_RULES,
} from "@/lib/mock-data";
import { ProfileEditorClient } from "./ProfileEditorClient";

async function loadProfileAndRules(): Promise<{
  profile: MasterProfileRecord;
  rules: TailoringRulesRecord;
}> {
  if (!process.env.DATABASE_URL) {
    return {
      profile: DEFAULT_MASTER_PROFILE,
      rules: DEFAULT_TAILORING_RULES,
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
    return {
      profile: (profRows[0] as unknown as MasterProfileRecord) || DEFAULT_MASTER_PROFILE,
      rules: (ruleRows[0] as unknown as TailoringRulesRecord) || DEFAULT_TAILORING_RULES,
    };
  } catch {
    return {
      profile: DEFAULT_MASTER_PROFILE,
      rules: DEFAULT_TAILORING_RULES,
    };
  }
}

export default async function ProfilePage() {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    redirect("/demo");
  }

  const { profile, rules } = await loadProfileAndRules();

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar isAuthenticatedAdmin={true} userEmail={session?.user?.email} />
      <main className="max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-white">
            Master Resume &amp; Anti-Hallucination Guardrails
          </h1>
          <p className="text-sm text-slate-400">
            Manage verified source bullets, forbidden terms denylists, and strict numerical locks.
          </p>
        </div>

        <ProfileEditorClient initialProfile={profile} initialRules={rules} />
      </main>
    </div>
  );
}

