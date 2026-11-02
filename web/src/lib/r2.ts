import {
  S3Client,
  GetObjectCommand,
  DeleteObjectCommand,
} from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { isAuthorizedAdminEmail } from "@/lib/auth-guard";
import { getSql } from "@/lib/db";

const PRESIGNED_TTL_SECONDS = 900; // 15 minutes per SPEC.md Section 5

export function sanitizeFilenamePart(text: string): string {
  if (!text) return "";
  return text
    .replace(/[\/\\:]+/g, " - ")
    .replace(/[*?"<>|]+/g, "")
    .replace(/\s+/g, " ")
    .replace(/\s*-\s*-\s*/g, " - ")
    .trim()
    .replace(/^[ -_.]+|[ -_.]+$/g, "");
}

export function generateArtifactFilename(
  type: string,
  userName: string = "Candidate",
  jobTitle: string = "Job Title",
  companyName: string = "Company"
): string {
  const safeName = sanitizeFilenamePart(userName) || "Candidate";
  const safeTitle = sanitizeFilenamePart(jobTitle) || "Job Title";
  const safeCompany = sanitizeFilenamePart(companyName) || "Company";

  if (type === "cover_letter") {
    return `${safeName} - ${safeCompany} - Cover Letter.pdf`;
  }
  return `${safeName} - ${safeTitle} - ${safeCompany}.pdf`;
}

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
  expiresInSeconds: number = PRESIGNED_TTL_SECONDS,
  filename?: string
): Promise<string> {
  const bucket =
    process.env.S3_BUCKET_NAME ||
    process.env.R2_BUCKET_NAME ||
    "job-artifacts";
  const client = createR2Client();
  const command = new GetObjectCommand({
    Bucket: bucket,
    Key: storageKey,
    ...(filename
      ? {
          ResponseContentDisposition: `inline; filename="${filename.replace(
            /"/g,
            ""
          )}"`,
        }
      : {}),
  });
  return getSignedUrl(client, command, { expiresIn: expiresInSeconds });
}

export async function deleteStorageKeysFromR2(
  rawKeys: Array<string | null | undefined>
): Promise<void> {
  const endpoint =
    process.env.S3_ENDPOINT_URL ||
    process.env.AWS_ENDPOINT_URL_S3 ||
    process.env.R2_ENDPOINT_URL ||
    "";
  if (!endpoint.startsWith("https://") || endpoint.includes("<")) {
    return;
  }

  const expandedKeys = new Set<string>();
  for (const key of rawKeys) {
    if (!key || !key.trim()) continue;
    const trimmed = key.trim();
    expandedKeys.add(trimmed);
    const slashIdx = trimmed.lastIndexOf("/");
    if (slashIdx > 0) {
      const prefix = trimmed.slice(0, slashIdx);
      expandedKeys.add(`${prefix}/resume.pdf`);
      expandedKeys.add(`${prefix}/cover_letter.pdf`);
      expandedKeys.add(`${prefix}/payload_snapshot.json`);
    }
  }

  if (expandedKeys.size === 0) return;

  const bucket =
    process.env.S3_BUCKET_NAME ||
    process.env.R2_BUCKET_NAME ||
    "job-artifacts";
  const client = createR2Client();

  await Promise.all(
    Array.from(expandedKeys).map(async (key) => {
      try {
        await client.send(
          new DeleteObjectCommand({
            Bucket: bucket,
            Key: key,
          })
        );
      } catch (err) {
        console.warn(`Failed to delete object '${key}' from S3:`, err);
      }
    })
  );
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
        SELECT m.resume_storage_key, m.cover_letter_storage_key,
               j.title as job_title, j.company as company,
               p.basics->>'name' as user_name
        FROM evaluated_matches m
        LEFT JOIN jobs j ON j.id = m.job_id
        LEFT JOIN master_profiles p ON p.is_active = TRUE
        WHERE m.id = ${id}
        LIMIT 1
      `;
      if (!rows || rows.length === 0) return null;
      return {
        resume_storage_key: rows[0].resume_storage_key as string | null,
        cover_letter_storage_key: rows[0].cover_letter_storage_key as string | null,
        job_title: (rows[0].job_title as string) || "Job Title",
        company: (rows[0].company as string) || "Company",
        user_name: (rows[0].user_name as string) || "Candidate",
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

  const rec = record as {
    job_title?: string;
    company?: string;
    user_name?: string;
  };
  const filename = generateArtifactFilename(
    artifactType,
    rec.user_name || "Candidate",
    rec.job_title || "Job Title",
    rec.company || "Company"
  );

  const presign = deps.presignFn || generatePresignedArtifactUrl;
  const signedUrl = await presign(storageKey, PRESIGNED_TTL_SECONDS, filename);

  return {
    status: 200,
    body: {
      url: signedUrl,
      expiresInSeconds: 900,
      storageKey,
      filename,
    },
  };
}

