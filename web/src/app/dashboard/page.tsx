import { redirect } from "next/navigation";
import { auth, isAuthorizedAdminEmail } from "@/auth";
import { Navbar } from "@/components/Navbar";
import { JobMatchFeed } from "@/components/JobMatchFeed";
import { getSql, type EvaluatedJobMatch } from "@/lib/db";
import { DEMO_MATCHES } from "@/lib/mock-data";
import { deleteStorageKeysFromR2 } from "@/lib/r2";
import {
  deleteMatchesAction,
  enqueueBatchDiscoveryAction,
  enqueueBatchTailorAction,
  enqueueJobUrlAction,
  updateMatchStatusAction,
} from "./actions";

async function purgeExpiredUnappliedMatches(): Promise<void> {
  try {
    const sql = getSql();
    const expired = await sql`
      SELECT
        m.id,
        m.job_id,
        m.resume_storage_key,
        m.cover_letter_storage_key
      FROM evaluated_matches m
      JOIN jobs j ON j.id = m.job_id
      WHERE m.status IN ('NEW_MATCH', 'SAVED')
        AND (
          m.created_at < NOW() - INTERVAL '7 days'
          OR j.created_at < NOW() - INTERVAL '7 days'
          OR (
            j.location ~ 'Posted [0-9]{4}-[0-9]{2}-[0-9]{2}'
            AND to_date(substring(j.location from 'Posted ([0-9]{4}-[0-9]{2}-[0-9]{2})'), 'YYYY-MM-DD') < (CURRENT_DATE - 7)
          )
        )
    `;
    if (expired.length === 0) {
      return;
    }

    const storageKeys: Array<string | null> = [];
    for (const row of expired) {
      if (row.resume_storage_key) {
        storageKeys.push(String(row.resume_storage_key));
      }
      if (row.cover_letter_storage_key) {
        storageKeys.push(String(row.cover_letter_storage_key));
      }
    }
    if (storageKeys.length > 0) {
      await deleteStorageKeysFromR2(storageKeys);
    }

    for (const row of expired) {
      const jobId = String(row.job_id);
      const matchId = String(row.id);
      await sql`DELETE FROM job_task_queue WHERE job_id = ${jobId}::uuid`;
      await sql`UPDATE jobs SET description_text = '' WHERE id = ${jobId}::uuid`;
      await sql`DELETE FROM evaluated_matches WHERE id = ${matchId}::uuid`;
    }
  } catch {
    // Non-fatal on dashboard load
  }
}

async function fetchDashboardMatches(): Promise<EvaluatedJobMatch[]> {
  if (!process.env.DATABASE_URL) {
    return DEMO_MATCHES;
  }
  try {
    await purgeExpiredUnappliedMatches();
    const sql = getSql();
    const rows = await sql`
      SELECT
        m.id,
        m.job_id,
        j.source,
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
          onRunBatchDiscovery={enqueueBatchDiscoveryAction}
          onBatchTailorJobs={enqueueBatchTailorAction}
          onDeleteMatches={deleteMatchesAction}
        />
      </main>
    </div>
  );
}

