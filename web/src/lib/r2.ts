import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { isAuthorizedAdminEmail } from "@/lib/auth-guard";
import { getSql } from "@/lib/db";

const PRESIGNED_TTL_SECONDS = 900; // 15 minutes per SPEC.md Section 5

export function createR2Client(): S3Client {
  const endpoint =
    process.env.S3_ENDPOINT_URL ||
    process.env.AWS_ENDPOINT_URL_S3 ||
    process.env.R2_ENDPOINT_URL;
  const accessKeyId =
    process.env.S3_ACCESS_KEY_ID ||
    process.env.AWS_ACCESS_KEY_ID ||
    process.env.R2_ACCESS_KEY_ID ||
    "";
  const secretAccessKey =
    process.env.S3_SECRET_ACCESS_KEY ||
    process.env.AWS_SECRET_ACCESS_KEY ||
    process.env.R2_SECRET_ACCESS_KEY ||
    "";
  const region =
    process.env.S3_REGION || process.env.AWS_REGION || "us-east-2";

  return new S3Client({
    region,
    endpoint,
    forcePathStyle: true, // Required by Neon Object Storage S3 endpoint
    credentials: {
      accessKeyId,
      secretAccessKey,
    },
  });
}

export async function generatePresignedArtifactUrl(
  storageKey: string,
  expiresInSeconds: number = PRESIGNED_TTL_SECONDS
): Promise<string> {
  const bucket =
    process.env.S3_BUCKET_NAME ||
    process.env.R2_BUCKET_NAME ||
    "job-artifacts";
  const client = createR2Client();
  const command = new GetObjectCommand({
    Bucket: bucket,
    Key: storageKey,
  });
  return getSignedUrl(client, command, { expiresIn: expiresInSeconds });
}

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

