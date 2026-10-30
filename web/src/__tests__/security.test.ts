jest.mock("next-auth", () => ({
  __esModule: true,
  default: () => ({
    handlers: {},
    auth: jest.fn(),
    signIn: jest.fn(),
    signOut: jest.fn(),
  }),
}));

jest.mock("next-auth/providers/google", () => ({
  __esModule: true,
  default: {},
}));

import { isAuthorizedAdminEmail, evaluateMiddlewareAccess } from "@/lib/auth-guard";
import { handleArtifactPresignRequest } from "@/app/api/artifacts/[id]/route";

describe("Next.js Auth & Artifact Route Security (Task 6.5)", () => {
  const ADMIN_EMAIL = "owner@jobbutler.dev";

  beforeEach(() => {
    process.env.ALLOWED_ADMIN_EMAIL = ADMIN_EMAIL;
  });

  test("isAuthorizedAdminEmail allows only exact case-insensitive ALLOWED_ADMIN_EMAIL", () => {
    expect(isAuthorizedAdminEmail("owner@jobbutler.dev", ADMIN_EMAIL)).toBe(true);
    expect(isAuthorizedAdminEmail("  OWNER@JobButler.dev ", ADMIN_EMAIL)).toBe(true);
    expect(isAuthorizedAdminEmail("intruder@gmail.com", ADMIN_EMAIL)).toBe(false);
    expect(isAuthorizedAdminEmail(null, ADMIN_EMAIL)).toBe(false);
    expect(isAuthorizedAdminEmail(undefined, ADMIN_EMAIL)).toBe(false);
  });

  test("Edge middleware blocks non-admin Google emails on /dashboard and /api/artifacts", () => {
    const unauthDashboard = evaluateMiddlewareAccess(
      "/dashboard",
      "visitor@gmail.com",
      ADMIN_EMAIL
    );
    expect(unauthDashboard.allowed).toBe(false);
    expect(unauthDashboard.redirectTo).toBe("/demo");

    const unauthApi = evaluateMiddlewareAccess(
      "/api/artifacts/match-123",
      "visitor@gmail.com",
      ADMIN_EMAIL
    );
    expect(unauthApi.allowed).toBe(false);
    expect(unauthApi.status).toBe(401);

    const adminDashboard = evaluateMiddlewareAccess(
      "/dashboard",
      ADMIN_EMAIL,
      ADMIN_EMAIL
    );
    expect(adminDashboard.allowed).toBe(true);
  });

  test("Presigned URL generation rejects unauthenticated or non-admin users with 401", async () => {
    const unauthRes = await handleArtifactPresignRequest(
      "match-1",
      "resume",
      null
    );
    expect(unauthRes.status).toBe(401);
    expect(unauthRes.body.error).toBe("Unauthorized");

    const nonAdminRes = await handleArtifactPresignRequest(
      "match-1",
      "resume",
      "other@example.com"
    );
    expect(nonAdminRes.status).toBe(401);
  });

  test("Presigned URL generation returns 15-minute signed R2 URL for authorized admin", async () => {
    const authorizedRes = await handleArtifactPresignRequest(
      "match-1",
      "resume",
      ADMIN_EMAIL,
      {
        lookupKeys: async () => ({
          resume_storage_key: "matches/abc/resume.pdf",
          cover_letter_storage_key: "matches/abc/cover_letter.pdf",
        }),
        presignFn: async (key) => `https://r2.example.com/${key}?X-Amz-Expires=900`,
      }
    );

    expect(authorizedRes.status).toBe(200);
    expect(authorizedRes.body.url).toContain("matches/abc/resume.pdf");
    expect(authorizedRes.body.expiresInSeconds).toBe(900);
  });
});
