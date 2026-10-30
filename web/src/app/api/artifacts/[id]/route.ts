import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { handleArtifactPresignRequest } from "@/lib/r2";

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
