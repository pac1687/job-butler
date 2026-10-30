import { redirect } from "next/navigation";
import { auth, isAuthorizedAdminEmail } from "@/auth";
import { Navbar } from "@/components/Navbar";
import { getSql, type JobPreferencesRecord } from "@/lib/db";
import { DEFAULT_PREFERENCES } from "@/lib/mock-data";
import { PreferencesFormClient } from "./PreferencesFormClient";

async function loadJobPreferences(): Promise<JobPreferencesRecord> {
  if (!process.env.DATABASE_URL) {
    return DEFAULT_PREFERENCES;
  }
  try {
    const sql = getSql();
    const rows = await sql`
      SELECT id, positive_titles, negative_title_keywords, natural_language_notes, min_semantic_score
      FROM job_preferences
      ORDER BY id DESC
      LIMIT 1
    `;
    return (rows[0] as unknown as JobPreferencesRecord) || DEFAULT_PREFERENCES;
  } catch {
    return DEFAULT_PREFERENCES;
  }
}

export default async function PreferencesPage() {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    redirect("/demo");
  }

  const prefs = await loadJobPreferences();

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar isAuthenticatedAdmin={true} userEmail={session?.user?.email} />
      <main className="max-w-4xl w-full mx-auto px-4 sm:px-6 py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-white">
            Dynamic Search &amp; Title Tuning
          </h1>
          <p className="text-sm text-slate-400">
            Configure positive vector centroids, negative regex blacklists, and natural language LLM guidance.
          </p>
        </div>

        <PreferencesFormClient initialPreferences={prefs} />
      </main>
    </div>
  );
}

