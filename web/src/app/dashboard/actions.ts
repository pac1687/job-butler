"use server";

import { revalidatePath } from "next/cache";
import { auth, isAuthorizedAdminEmail } from "@/auth";
import { getSql, type MatchStatus } from "@/lib/db";

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

export async function enqueueJobUrlAction(url: string) {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    throw new Error("Unauthorized");
  }

  const sql = getSql();
  await sql`
    INSERT INTO job_task_queue (task_type, payload, status)
    VALUES ('EVALUATE_URL', ${JSON.stringify({ url })}::jsonb, 'PENDING')
  `;
  revalidatePath("/dashboard");
}

