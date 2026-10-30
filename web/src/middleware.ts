import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";
import { evaluateMiddlewareAccess } from "@/lib/auth-guard";

export { evaluateMiddlewareAccess };

export default auth((req: NextRequest & { auth?: { user?: { email?: string | null } } | null }) => {
  const userEmail = req.auth?.user?.email;
  const decision = evaluateMiddlewareAccess(req.nextUrl.pathname, userEmail);

  if (decision.allowed) {
    return NextResponse.next();
  }
  if (decision.status === 401) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const demoUrl = new URL(decision.redirectTo || "/demo", req.nextUrl.origin);
  return NextResponse.redirect(demoUrl);
});

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/profile/:path*",
    "/preferences/:path*",
    "/api/artifacts/:path*",
    "/api/tasks/:path*",
  ],
};
