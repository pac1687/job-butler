import { NextResponse } from "next/server";
import { auth, isAuthorizedAdminEmail } from "@/auth";
import { getSql, withWorkerAffinity } from "@/lib/db";

export async function GET() {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const sql = getSql();
    const tasks = await sql`
      SELECT id, job_id, task_type, payload, status, error_message, created_at, updated_at
      FROM job_task_queue
      ORDER BY created_at DESC
      LIMIT 15
    `;
    return NextResponse.json({ tasks });
  } catch {
    return NextResponse.json({ tasks: [] });
  }
}

export async function POST(request: Request) {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await request.json();
  const taskType = body.task_type || "EVALUATE_URL";
  const rawPayload =
    body.payload && typeof body.payload === "object" ? body.payload : {};
  const payload = withWorkerAffinity(rawPayload);
  const jobId = body.job_id || null;

  const allowedTypes = [
    "PARSE_MASTER_RESUME",
    "EVALUATE_URL",
    "REGENERATE_RESUME",
    "REWRITE_COVER_LETTER",
  ];
  if (!allowedTypes.includes(taskType)) {
    return NextResponse.json({ error: "Invalid task_type" }, { status: 400 });
  }

  const sql = getSql();
  const inserted = await sql`
    INSERT INTO job_task_queue (job_id, task_type, payload, status)
    VALUES (${jobId}, ${taskType}, ${JSON.stringify(payload)}::jsonb, 'PENDING')
    RETURNING id, task_type, payload, status, created_at
  `;

  return NextResponse.json({ task: inserted[0] }, { status: 201 });
}
