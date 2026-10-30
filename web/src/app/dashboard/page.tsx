import { redirect } from "next/navigation";
import { auth, isAuthorizedAdminEmail } from "@/auth";
import { Navbar } from "@/components/Navbar";
import { JobMatchFeed } from "@/components/JobMatchFeed";
import { getSql, type EvaluatedJobMatch } from "@/lib/db";
import { DEMO_MATCHES } from "@/lib/mock-data";
import { enqueueJobUrlAction, updateMatchStatusAction } from "./actions";

async function fetchDashboardMatches(): Promise<EvaluatedJobMatch[]> {
  if (!process.env.DATABASE_URL) {
    return DEMO_MATCHES;
  }
  try {
    const sql = getSql();
    const rows = await sql`
      SELECT
        m.id,
        m.job_id,
        j.title,
        j.company,
        j.location,
        j.is_remote,
        j.url,
        j.salary_range,
        m.semantic_score,
        m.fit_score,
        m.fit_rationale,
        m.matched_skills,
        m.missing_skills,
        m.resume_storage_key,
        m.cover_letter_storage_key,
        m.payload_snapshot,
        m.status,
        m.created_at
      FROM evaluated_matches m
      JOIN jobs j ON j.id = m.job_id
      ORDER BY m.fit_score DESC, m.created_at DESC
      LIMIT 100
    `;
    return rows as unknown as EvaluatedJobMatch[];
  } catch {
    return DEMO_MATCHES;
  }
}

export default async function DashboardPage() {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    redirect("/demo");
  }

  const matches = await fetchDashboardMatches();

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar
        isAuthenticatedAdmin={true}
        userEmail={session?.user?.email}
      />
      <main className="max-w-6xl w-full mx-auto px-4 sm:px-6 py-8 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">
              Job Triage &amp; Audit Dashboard
            </h1>
            <p className="text-sm text-slate-400">
              Ranked by local LLM fit_score descending. Inspect payload snapshots or generate 15-minute presigned R2 PDF links.
            </p>
          </div>
        </div>

        <JobMatchFeed
          initialMatches={matches}
          readOnly={false}
          onUpdateStatus={updateMatchStatusAction}
          onEnqueueUrl={enqueueJobUrlAction}
        />
      </main>
    </div>
  );
}

