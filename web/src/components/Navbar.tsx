import Link from "next/link";
import { signIn, signOut } from "@/auth";

interface NavbarProps {
  isAuthenticatedAdmin?: boolean;
  userEmail?: string | null;
}

export function Navbar({ isAuthenticatedAdmin = false, userEmail }: NavbarProps) {
  return (
    <header className="border-b border-slate-800 bg-slate-950/90 backdrop-blur sticky top-0 z-40">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <Link
            href={isAuthenticatedAdmin ? "/dashboard" : "/demo"}
            className="text-lg font-bold tracking-tight text-white flex items-center gap-2"
          >
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-emerald-400" />
            Job Butler
            <span className="text-xs font-mono uppercase px-2 py-0.5 rounded bg-slate-800 text-slate-300">
              Hybrid Edge
            </span>
          </Link>

          <nav className="hidden sm:flex items-center gap-5 text-sm font-medium text-slate-300">
            {isAuthenticatedAdmin ? (
              <>
                <Link href="/dashboard" className="hover:text-white transition">
                  Triage Feed
                </Link>
                <Link href="/profile" className="hover:text-white transition">
                  Resume &amp; Guardrails
                </Link>
                <Link href="/preferences" className="hover:text-white transition">
                  Search Tuning
                </Link>
              </>
            ) : (
              <Link href="/demo" className="hover:text-white transition">
                Public Demo Feed
              </Link>
            )}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          {isAuthenticatedAdmin ? (
            <div className="flex items-center gap-3">
              <span className="text-xs text-slate-400 hidden md:inline">
                {userEmail}
              </span>
              <form
                action={async () => {
                  "use server";
                  await signOut({ redirectTo: "/demo" });
                }}
              >
                <button
                  type="submit"
                  className="text-xs font-medium px-3 py-1.5 rounded-md border border-slate-700 text-slate-200 hover:bg-slate-800 transition"
                >
                  Sign Out
                </button>
              </form>
            </div>
          ) : (
            <form
              action={async () => {
                "use server";
                await signIn("google", { redirectTo: "/dashboard" });
              }}
            >
              <button
                type="submit"
                className="text-xs font-semibold px-3.5 py-1.5 rounded-md bg-emerald-500 text-slate-950 hover:bg-emerald-400 transition"
              >
                Admin Sign In (Google)
              </button>
            </form>
          )}
        </div>
      </div>
    </header>
  );
}
