import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";
import { evaluateMiddlewareAccess } from "@/lib/auth-guard";

export default auth((req: NextRequest & { auth?: { user?: { email?: string | null } } | null }) => {
  const userEmail = req.auth?.user?.email;
  const decision = evaluateMiddlewareAccess(req.nextUrl.pathname, userEmail);

  let response: NextResponse;
  if (decision.allowed) {
    response = NextResponse.next();
  } else if (decision.status === 401) {
    response = NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  } else {
    const demoUrl = new URL(decision.redirectTo || "/demo", req.nextUrl.origin);
    const workerParam =
      req.nextUrl.searchParams.get("worker") ||
      req.nextUrl.searchParams.get("node");
    if (workerParam) {
      demoUrl.searchParams.set("worker", workerParam.trim());
    }
    response = NextResponse.redirect(demoUrl);
  }

  // Intercept ?worker= or ?node= and persist as a 1-year cookie
  const workerParam =
    req.nextUrl.searchParams.get("worker") ||
    req.nextUrl.searchParams.get("node") ||
    "";
  const trimmedWorker = workerParam.trim();
  if (trimmedWorker) {
    response.cookies.set("worker_node_id", trimmedWorker, {
      path: "/",
      maxAge: 31536000, // 1 year
      sameSite: "lax",
    });
  }

  return response;
});

export const config = {
  matcher: [
    "/",
    "/demo/:path*",
    "/dashboard/:path*",
    "/profile/:path*",
    "/preferences/:path*",
    "/api/artifacts/:path*",
    "/api/tasks/:path*",
  ],
};
