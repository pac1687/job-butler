import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

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

