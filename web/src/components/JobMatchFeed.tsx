"use client";

import React, { useState } from "react";
import type { EvaluatedJobMatch, MatchStatus } from "@/lib/db";

interface JobMatchFeedProps {
  initialMatches: EvaluatedJobMatch[];
  readOnly?: boolean;
  onUpdateStatus?: (matchId: string, status: MatchStatus) => Promise<void>;
  onEnqueueUrl?: (url: string) => Promise<void>;
  onRunBatchDiscovery?: () => Promise<void>;
}

const STATUS_OPTIONS: MatchStatus[] = ["NEW_MATCH", "SAVED", "APPLIED", "ARCHIVED"];

export function JobMatchFeed({
  initialMatches,
  readOnly = false,
  onUpdateStatus,
  onEnqueueUrl,
  onRunBatchDiscovery,
}: JobMatchFeedProps) {
  const [matches, setMatches] = useState<EvaluatedJobMatch[]>(initialMatches);
  const [activeFilter, setActiveFilter] = useState<string>("ALL");
  const [snapshotModalMatch, setSnapshotModalMatch] = useState<EvaluatedJobMatch | null>(null);
  const [showQueueModal, setShowQueueModal] = useState(false);
  const [customUrl, setCustomUrl] = useState("");
  const [queueMessage, setQueueMessage] = useState<string | null>(null);
  const [discoveryNotice, setDiscoveryNotice] = useState<string | null>(null);
  const [runningDiscovery, setRunningDiscovery] = useState(false);
  const [loadingArtifactId, setLoadingArtifactId] = useState<string | null>(null);

  const filteredMatches = matches.filter((m) =>
    activeFilter === "ALL" ? m.status !== "ARCHIVED" : m.status === activeFilter
  );

  async function handleStatusChange(matchId: string, nextStatus: MatchStatus) {
    if (readOnly) return;
    setMatches((prev) =>
      prev.map((m) => (m.id === matchId ? { ...m, status: nextStatus } : m))
    );
    if (onUpdateStatus) {
      await onUpdateStatus(matchId, nextStatus);
    }
  }

  async function handleOpenArtifact(matchId: string, type: "resume" | "cover_letter") {
    if (readOnly) {
      alert("Demo Mode: Artifact presigned URLs are restricted to authenticated admins.");
      return;
    }
    try {
      setLoadingArtifactId(`${matchId}:${type}`);
      const res = await fetch(`/api/artifacts/${matchId}?type=${type}`);
      const data = await res.json();
      if (!res.ok || !data.url) {
        alert(data.error || "Unable to generate presigned URL");
        return;
      }
      window.open(data.url, "_blank", "noopener,noreferrer");
    } finally {
      setLoadingArtifactId(null);
    }
  }

  async function handleQueueSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!customUrl.trim() || readOnly) return;
    setQueueMessage("Enqueuing URL for local Docker worker evaluation...");
    if (onEnqueueUrl) {
      await onEnqueueUrl(customUrl.trim());
    } else {
      await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_type: "EVALUATE_URL",
          payload: { url: customUrl.trim() },
        }),
      });
    }
    setCustomUrl("");
    setQueueMessage(
      "Queued! The local worker will scrape, score, and compile a 1-page PDF on next poll."
    );
  }

  async function handleRunBatchDiscovery() {
    if (readOnly) return;
    try {
      setRunningDiscovery(true);
      setDiscoveryNotice("Enqueuing batch job discovery scrape...");
      if (onRunBatchDiscovery) {
        await onRunBatchDiscovery();
      } else {
        await fetch("/api/tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            task_type: "EVALUATE_URL",
            payload: { mode: "BATCH_DISCOVERY", max_jobs: 5 },
          }),
        });
      }
      setDiscoveryNotice(
        "Discovery scrape queued! Your local queue-listener will fetch, rank, score, and tailor the top matching roles on its next 10s poll."
      );
    } finally {
      setRunningDiscovery(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Top Controls Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-slate-900/70 border border-slate-800 rounded-xl p-4">
        <div className="flex flex-wrap items-center gap-2">
          {["ALL", ...STATUS_OPTIONS].map((status) => (
            <button
              key={status}
              onClick={() => setActiveFilter(status)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                activeFilter === status
                  ? "bg-emerald-500 text-slate-950"
                  : "bg-slate-800 text-slate-300 hover:bg-slate-700"
              }`}
            >
              {status.replace("_", " ")}
            </button>
          ))}
        </div>

        {!readOnly && (
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={handleRunBatchDiscovery}
              disabled={runningDiscovery}
              className="px-3.5 py-2 rounded-lg text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-50 transition"
            >
              {runningDiscovery ? "Queuing Scrape..." : "🔄 Run Discovery Scrape Now"}
            </button>
            <button
              onClick={() => {
                setQueueMessage(null);
                setShowQueueModal(true);
              }}
              className="px-3.5 py-2 rounded-lg text-xs font-semibold bg-indigo-500 text-white hover:bg-indigo-400 transition"
            >
              + Submit Job URL to Worker Queue
            </button>
          </div>
        )}
      </div>

      {discoveryNotice && (
        <div className="bg-emerald-950/60 border border-emerald-800/80 text-emerald-300 rounded-xl px-4 py-3 text-xs flex items-center justify-between gap-3">
          <span>{discoveryNotice}</span>
          <button
            onClick={() => setDiscoveryNotice(null)}
            className="text-emerald-400 hover:text-white font-semibold"
          >
            ✕
          </button>
        </div>
      )}

      {/* Feed Cards */}
      {filteredMatches.length === 0 ? (
        <div className="text-center py-12 bg-slate-900/40 border border-slate-800 rounded-xl text-slate-400 text-sm">
          No evaluated job matches in this filter state.
        </div>
      ) : (
        <div className="space-y-4">
          {filteredMatches.map((match) => (
            <article
              key={match.id}
              className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 space-y-4 hover:border-slate-700 transition"
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <h2 className="text-lg font-bold text-white">{match.title}</h2>
                    <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-medium">
                      {match.company}
                    </span>
                    {match.is_remote && (
                      <span className="text-xs px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800/60">
                        Remote
                      </span>
                    )}
                    {match.salary_range && (
                      <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-amber-300 font-mono">
                        {match.salary_range}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 mt-1">
                    {match.location} &bull;{" "}
                    <a
                      href={match.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-indigo-400 hover:underline"
                    >
                      View Original Posting &rarr;
                    </a>
                  </p>
                </div>

                {/* Fit & Semantic Score Badges */}
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <div className="text-xs text-slate-400">Fit Score</div>
                    <div className="text-xl font-extrabold text-emerald-400 font-mono">
                      {Number(match.fit_score).toFixed(1)}
                      <span className="text-xs text-slate-500">/10</span>
                    </div>
                  </div>
                  <div className="text-right border-l border-slate-800 pl-3">
                    <div className="text-xs text-slate-400">Vector Sim</div>
                    <div className="text-sm font-bold text-slate-200 font-mono">
                      {(Number(match.semantic_score) * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>
              </div>

              {/* LLM Fit Rationale */}
              <p className="text-sm text-slate-300 leading-relaxed bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
                {match.fit_rationale}
              </p>

              {/* Skill Alignment Badges */}
              <div className="flex flex-wrap gap-1.5 items-center">
                <span className="text-xs text-slate-400 mr-1">Matched:</span>
                {match.matched_skills.map((skill) => (
                  <span
                    key={skill}
                    className="text-xs px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-800/50"
                  >
                    ✓ {skill}
                  </span>
                ))}
                {match.missing_skills.length > 0 && (
                  <>
                    <span className="text-xs text-slate-400 ml-2 mr-1">Gaps:</span>
                    {match.missing_skills.map((gap) => (
                      <span
                        key={gap}
                        className="text-xs px-2 py-0.5 rounded bg-rose-950/70 text-rose-300 border border-rose-800/50"
                      >
                        ! {gap}
                      </span>
                    ))}
                  </>
                )}
              </div>

              {/* Action Bar: Presigned PDFs, Audit Snapshot Viewer, Status Mutation */}
              <div className="pt-3 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => handleOpenArtifact(match.id, "resume")}
                    disabled={loadingArtifactId === `${match.id}:resume`}
                    className="px-3 py-1.5 rounded-md text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-white border border-slate-700 transition"
                  >
                    {loadingArtifactId === `${match.id}:resume`
                      ? "Signing..."
                      : "📄 Tailored Resume PDF"}
                  </button>
                  <button
                    onClick={() => handleOpenArtifact(match.id, "cover_letter")}
                    disabled={loadingArtifactId === `${match.id}:cover_letter`}
                    className="px-3 py-1.5 rounded-md text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-white border border-slate-700 transition"
                  >
                    {loadingArtifactId === `${match.id}:cover_letter`
                      ? "Signing..."
                      : "✉️ Cover Letter PDF"}
                  </button>
                  <button
                    onClick={() => setSnapshotModalMatch(match)}
                    className="px-3 py-1.5 rounded-md text-xs font-semibold bg-slate-900 hover:bg-slate-800 text-indigo-300 border border-indigo-800/60 transition"
                  >
                    🔍 Audit Snapshot JSON
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  <label className="text-xs text-slate-400">Stage:</label>
                  <select
                    aria-label={`Status for ${match.title}`}
                    disabled={readOnly}
                    value={match.status}
                    onChange={(e) =>
                      handleStatusChange(match.id, e.target.value as MatchStatus)
                    }
                    className="bg-slate-950 border border-slate-700 rounded-md px-2.5 py-1 text-xs text-slate-200 disabled:opacity-50"
                  >
                    {STATUS_OPTIONS.map((st) => (
                      <option key={st} value={st}>
                        {st}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* Audit Snapshot Viewer Modal (FR-1.4 / SPEC.md Section 5) */}
      {snapshotModalMatch && (
        <div className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-xl max-w-3xl w-full max-h-[85vh] flex flex-col overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-white">
                  Historical Payload Snapshot — {snapshotModalMatch.company}
                </h3>
                <p className="text-xs text-slate-400">
                  Exact Guardrail-Verified JSON Compiled by Typst
                </p>
              </div>
              <button
                onClick={() => setSnapshotModalMatch(null)}
                className="text-slate-400 hover:text-white text-sm font-semibold px-2 py-1"
              >
                ✕ Close
              </button>
            </div>
            <div className="p-5 overflow-y-auto font-mono text-xs text-emerald-300 bg-slate-950">
              <pre className="whitespace-pre-wrap break-words">
                {JSON.stringify(snapshotModalMatch.payload_snapshot, null, 2)}
              </pre>
            </div>
          </div>
        </div>
      )}

      {/* On-Demand Task Queue Submission Modal (FR-1.6) */}
      {showQueueModal && (
        <div className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-xl max-w-lg w-full p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-white">
                Enqueue Ad-Hoc Job URL for Tailoring
              </h3>
              <button
                onClick={() => setShowQueueModal(false)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleQueueSubmit} className="space-y-3">
              <div>
                <label className="block text-xs text-slate-300 mb-1">
                  Job Posting URL (Greenhouse, Lever, Ashby, or Company Career Page)
                </label>
                <input
                  type="url"
                  required
                  value={customUrl}
                  onChange={(e) => setCustomUrl(e.target.value)}
                  placeholder="https://boards.greenhouse.io/company/jobs/12345"
                  className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 text-sm text-white"
                />
              </div>
              {queueMessage && (
                <p className="text-xs text-emerald-400 bg-emerald-950/50 border border-emerald-800 rounded p-2">
                  {queueMessage}
                </p>
              )}
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowQueueModal(false)}
                  className="px-3 py-1.5 rounded-lg text-xs text-slate-300 bg-slate-800"
                >
                  Close
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500 text-slate-950 hover:bg-emerald-400"
                >
                  Enqueue Task
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

