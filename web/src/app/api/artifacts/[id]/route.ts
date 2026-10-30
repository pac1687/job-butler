import { NextResponse } from "next/server";
import { auth, isAuthorizedAdminEmail } from "@/auth";
import { getSql } from "@/lib/db";
import { generatePresignedArtifactUrl } from "@/lib/r2";

export async function handleArtifactPresignRequest(
  matchId: string,
  artifactType: string,
  userEmail: string | null | undefined,
  deps: {
    lookupKeys?: (id: string) => Promise<{
      resume_storage_key: string | null;
      cover_letter_storage_key: string | null;
    } | null>;
    presignFn?: (key: string) => Promise<string>;
  } = {}
): Promise<{ status: number; body: Record<string, unknown> }> {
  if (!isAuthorizedAdminEmail(userEmail)) {
    return { status: 401, body: { error: "Unauthorized" } };
  }

  const lookup =
    deps.lookupKeys ||
    (async (id: string) => {
      const sql = getSql();
      const rows = await sql`
        SELECT resume_storage_key, cover_letter_storage_key
        FROM evaluated_matches
        WHERE id = ${id}
        LIMIT 1
      `;
      if (!rows || rows.length === 0) return null;
      return {
        resume_storage_key: rows[0].resume_storage_key as string | null,
        cover_letter_storage_key: rows[0].cover_letter_storage_key as string | null,
      };
    });

  const record = await lookup(matchId);
  if (!record) {
    return { status: 404, body: { error: "Evaluated match not found" } };
  }

  const storageKey =
    artifactType === "cover_letter"
      ? record.cover_letter_storage_key
      : record.resume_storage_key;

  if (!storageKey) {
    return { status: 404, body: { error: "Artifact key not available for this match" } };
  }

  const presign = deps.presignFn || generatePresignedArtifactUrl;
  const signedUrl = await presign(storageKey);

  return {
    status: 200,
    body: {
      url: signedUrl,
      expiresInSeconds: 900,
      storageKey,
    },
  };
}

export async function GET(
  request: Request,
  { params }: { params: { id: string } }
) {
  const session = await auth();
  const { searchParams } = new URL(request.url);
  const artifactType = searchParams.get("type") || "resume";

  const result = await handleArtifactPresignRequest(
    params.id,
    artifactType,
    session?.user?.email
  );
  return NextResponse.json(result.body, { status: result.status });
}

