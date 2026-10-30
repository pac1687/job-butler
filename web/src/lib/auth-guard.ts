const PROTECTED_PREFIXES = [
  "/dashboard",
  "/profile",
  "/preferences",
  "/api/artifacts",
  "/api/tasks",
];

export function isAuthorizedAdminEmail(
  email: string | null | undefined,
  allowedAdminEmail: string | undefined = process.env.ALLOWED_ADMIN_EMAIL
): boolean {
  if (!email || !allowedAdminEmail) {
    return false;
  }
  return email.trim().toLowerCase() === allowedAdminEmail.trim().toLowerCase();
}

export function evaluateMiddlewareAccess(
  pathname: string,
  userEmail: string | null | undefined,
  allowedAdminEmail: string | undefined = process.env.ALLOWED_ADMIN_EMAIL
): { allowed: boolean; status?: number; redirectTo?: string } {
  const isProtected = PROTECTED_PREFIXES.some((prefix) =>
    pathname.startsWith(prefix)
  );
  if (!isProtected) {
    return { allowed: true };
  }

  const isAdmin = isAuthorizedAdminEmail(userEmail, allowedAdminEmail);
  if (isAdmin) {
    return { allowed: true };
  }

  if (pathname.startsWith("/api/")) {
    return { allowed: false, status: 401 };
  }
  return { allowed: false, redirectTo: "/demo" };
}

