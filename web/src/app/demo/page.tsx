import { Navbar } from "@/components/Navbar";
import { JobMatchFeed } from "@/components/JobMatchFeed";
import { DEMO_MATCHES } from "@/lib/mock-data";

export default function PublicDemoPage() {
  return (
    <div className="min-h-screen flex flex-col">
      <Navbar isAuthenticatedAdmin={false} />
      <main className="max-w-6xl w-full mx-auto px-4 sm:px-6 py-8 space-y-6">
        <div className="bg-amber-950/40 border border-amber-800/60 rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-base font-bold text-amber-200">
              Read-Only Public Demo Mode
            </h1>
            <p className="text-xs text-amber-300/80 mt-0.5">
              Showing sanitized mock job matches, guardrail snapshots, and fit rationales.
              Sign in with the allowlisted administrator Google account to manage live jobs and R2 PDFs.
            </p>
          </div>
          <span className="text-xs font-mono px-2.5 py-1 rounded bg-amber-900/60 text-amber-200">
            /demo (Unauthenticated)
          </span>
        </div>

        <JobMatchFeed initialMatches={DEMO_MATCHES} readOnly={true} />
      </main>
    </div>
  );
}

