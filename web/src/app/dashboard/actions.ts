"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { auth, isAuthorizedAdminEmail } from "@/auth";
import { getSql, withWorkerAffinity, type MatchStatus } from "@/lib/db";
import { deleteStorageKeysFromR2 } from "@/lib/r2";

export async function updateMatchStatusAction(matchId: string, status: MatchStatus) {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    throw new Error("Unauthorized");
  }

  const sql = getSql();
  await sql`
    UPDATE evaluated_matches
    SET status = ${status}
    WHERE id = ${matchId}
  `;
  revalidatePath("/dashboard");
}

export async function enqueueJobUrlAction(url: string): Promise<{ taskId: string }> {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    throw new Error("Unauthorized");
  }

  const sql = getSql();
  const cookieStore = cookies();
  const cookieWorker = cookieStore.get("worker_node_id")?.value;
  const payload = withWorkerAffinity({ url }, cookieWorker);
  const rows = await sql`
    INSERT INTO job_task_queue (task_type, payload, status)
    VALUES ('EVALUATE_URL', ${JSON.stringify(payload)}::jsonb, 'PENDING')
    RETURNING id
  `;
  revalidatePath("/dashboard");
  return { taskId: String(rows[0]?.id || "") };
}

export async function enqueueBatchDiscoveryAction(
  maxJobs: number = 10
): Promise<{ taskId: string }> {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    throw new Error("Unauthorized");
  }

  const clampedMaxJobs = Math.min(50, Math.max(1, Math.floor(Number(maxJobs) || 10)));
  const sql = getSql();
  const cookieStore = cookies();
  const cookieWorker = cookieStore.get("worker_node_id")?.value;
  const payload = withWorkerAffinity(
    {
      mode: "BATCH_DISCOVERY",
      max_jobs: clampedMaxJobs,
    },
    cookieWorker
  );
  const rows = await sql`
    INSERT INTO job_task_queue (task_type, payload, status)
    VALUES ('EVALUATE_URL', ${JSON.stringify(payload)}::jsonb, 'PENDING')
    RETURNING id
  `;
  revalidatePath("/dashboard");
  return { taskId: String(rows[0]?.id || "") };
}

export async function enqueueBatchTailorAction(
  jobIds: string[]
): Promise<{ taskIds: string[] }> {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    throw new Error("Unauthorized");
  }

  const uniqueJobIds = Array.from(
    new Set(jobIds.map((id) => id.trim()).filter(Boolean))
  ).slice(0, 25);
  if (uniqueJobIds.length === 0) {
    return { taskIds: [] };
  }

  const sql = getSql();
  const cookieStore = cookies();
  const cookieWorker = cookieStore.get("worker_node_id")?.value;
  const payloadJson = JSON.stringify(withWorkerAffinity({}, cookieWorker));
  const taskIds: string[] = [];

  for (const jobId of uniqueJobIds) {
    const rows = await sql`
      INSERT INTO job_task_queue (job_id, task_type, payload, status)
      VALUES (${jobId}::uuid, 'REGENERATE_RESUME', ${payloadJson}::jsonb, 'PENDING')
      RETURNING id
    `;
    if (rows[0]?.id) {
      taskIds.push(String(rows[0].id));
    }
  }
  revalidatePath("/dashboard");
  return { taskIds };
}

export async function deleteMatchesAction(matchIds: string[]) {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    throw new Error("Unauthorized");
  }

  const uniqueMatchIds = Array.from(
    new Set(matchIds.map((id) => id.trim()).filter(Boolean))
  );
  if (uniqueMatchIds.length === 0) {
    return;
  }

  const sql = getSql();
  const storageKeys: Array<string | null> = [];
  const jobIds: string[] = [];

  for (const matchId of uniqueMatchIds) {
    const rows = await sql`
      SELECT id, job_id, resume_storage_key, cover_letter_storage_key
      FROM evaluated_matches
      WHERE id = ${matchId}::uuid
    `;
    for (const row of rows) {
      if (row.resume_storage_key) {
        storageKeys.push(String(row.resume_storage_key));
      }
      if (row.cover_letter_storage_key) {
        storageKeys.push(String(row.cover_letter_storage_key));
      }
      if (row.job_id) {
        jobIds.push(String(row.job_id));
      }
    }
  }

  // 1. Delete associated PDFs and payload_snapshot.json from Neon Object Storage
  await deleteStorageKeysFromR2(storageKeys);

  // 2. Delete pending/failed tasks, delete evaluated_matches rows, and slim down jobs row
  // (keeping content_hash in jobs so deleted postings are never re-scraped in future runs)
  for (const jobId of jobIds) {
    await sql`
      DELETE FROM job_task_queue WHERE job_id = ${jobId}::uuid
    `;
    await sql`
      UPDATE jobs SET description_text = '' WHERE id = ${jobId}::uuid
    `;
  }

  for (const matchId of uniqueMatchIds) {
    await sql`
      DELETE FROM evaluated_matches WHERE id = ${matchId}::uuid
    `;
  }

  revalidatePath("/dashboard");
}
