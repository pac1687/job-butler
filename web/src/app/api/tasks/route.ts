import { NextResponse } from "next/server";
import { auth, isAuthorizedAdminEmail } from "@/auth";
import { getSql, withWorkerAffinity } from "@/lib/db";

export async function GET(request: Request) {
  const session = await auth();
  if (!isAuthorizedAdminEmail(session?.user?.email)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const { searchParams } = new URL(request.url);
    const idsParam = searchParams.get("ids");
    const activeOnly = searchParams.get("active") === "true";
    const sql = getSql();

    if (idsParam) {
      const ids = idsParam
        .split(",")
        .map((id) => id.trim())
        .filter(Boolean);
      if (ids.length > 0) {
        const tasks = await sql`
          SELECT id, job_id, task_type, payload, status, error_message, created_at, updated_at
          FROM job_task_queue
          WHERE id = ANY(${ids}::uuid[])
          ORDER BY created_at DESC
        `;
        return NextResponse.json({ tasks });
      }
    }

    if (activeOnly) {
      const tasks = await sql`
        SELECT id, job_id, task_type, payload, status, error_message, created_at, updated_at
        FROM job_task_queue
        WHERE status IN ('PENDING', 'PROCESSING')
        ORDER BY created_at DESC
        LIMIT 25
      `;
      return NextResponse.json({ tasks });
    }

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

  // Extract worker node affinity from cookie (persisted from ?worker=...), header, or env
  const cookieHeader = request.headers.get("cookie") || "";
  const cookieMatch = cookieHeader.match(/(?:^|;\s*)worker_node_id=([^;]+)/);
  const cookieWorker = cookieMatch ? decodeURIComponent(cookieMatch[1].trim()) : null;
  const headerWorker = request.headers.get("x-worker-node-id")?.trim() || null;
  const explicitWorker = cookieWorker || headerWorker;

  const payload = withWorkerAffinity(rawPayload, explicitWorker);
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
