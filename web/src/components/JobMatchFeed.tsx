"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import type { EvaluatedJobMatch, MatchStatus } from "@/lib/db";

interface JobMatchFeedProps {
  initialMatches: EvaluatedJobMatch[];
  readOnly?: boolean;
  onUpdateStatus?: (matchId: string, status: MatchStatus) => Promise<void>;
  onEnqueueUrl?: (url: string) => Promise<{ taskId?: string } | void>;
  onRunBatchDiscovery?: (maxJobs: number) => Promise<{ taskId?: string } | void>;
  onBatchTailorJobs?: (jobIds: string[]) => Promise<{ taskIds?: string[] } | void>;
  onDeleteMatches?: (matchIds: string[]) => Promise<void>;
}

const STATUS_OPTIONS: MatchStatus[] = ["NEW_MATCH", "SAVED", "APPLIED", "ARCHIVED"];
const BATCH_SIZE_OPTIONS: number[] = [5, 10, 15, 20, 30];

function formatJobSource(rawSource?: string | null): {
  label: string;
  className: string;
} {
  const src = (rawSource || "").trim().toLowerCase();
  switch (src) {
    case "linkedin":
      return {
        label: "LinkedIn",
        className:
          "bg-sky-950/90 text-sky-300 border border-sky-800/70",
      };
    case "indeed":
    case "jobspy":
      return {
        label: "Indeed",
        className:
          "bg-blue-950/90 text-blue-300 border border-blue-800/70",
      };
    case "remotive":
      return {
        label: "Remotive",
        className:
          "bg-purple-950/90 text-purple-300 border border-purple-800/70",
      };
    case "greenhouse":
      return {
        label: "Greenhouse",
        className:
          "bg-teal-950/90 text-teal-300 border border-teal-800/70",
      };
    case "ashby":
      return {
        label: "Ashby",
        className:
          "bg-violet-950/90 text-violet-300 border border-violet-800/70",
      };
    case "lever":
      return {
        label: "Lever",
        className:
          "bg-cyan-950/90 text-cyan-300 border border-cyan-800/70",
      };
    case "on_demand_url":
      return {
        label: "Direct URL",
        className:
          "bg-fuchsia-950/90 text-fuchsia-300 border border-fuchsia-800/70",
      };
    default:
      return {
        label: rawSource ? rawSource : "Scraped",
        className:
          "bg-slate-800 text-slate-300 border border-slate-700",
      };
  }
}

function isPostedWithinLast24Hours(match: EvaluatedJobMatch): boolean {
  const loc = match.location || "";
  const postedMatch = /Posted\s+(\d{4}-\d{2}-\d{2})/i.exec(loc);
  if (postedMatch) {
    const [year, month, day] = postedMatch[1].split("-").map(Number);
    const now = new Date();
    const todayLocal = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const postedLocal = new Date(year, month - 1, day);
    const diffDays = Math.round(
      (todayLocal.getTime() - postedLocal.getTime()) / (1000 * 60 * 60 * 24)
    );
    return diffDays >= 0 && diffDays <= 1;
  }
  if (match.created_at) {
    const createdMs = new Date(match.created_at).getTime();
    if (Number.isFinite(createdMs)) {
      return Date.now() - createdMs <= 24 * 60 * 60 * 1000;
    }
  }
  return false;
}

export function JobMatchFeed({
  initialMatches,
  readOnly = false,
  onUpdateStatus,
  onEnqueueUrl,
  onRunBatchDiscovery,
  onBatchTailorJobs,
  onDeleteMatches,
}: JobMatchFeedProps) {
  const [matches, setMatches] = useState<EvaluatedJobMatch[]>(initialMatches);
  const [activeFilter, setActiveFilter] = useState<string>(
    readOnly ? "ALL" : "NEW_24H"
  );
  const [pdfOnlyFilter, setPdfOnlyFilter] = useState<boolean>(false);

  // Restore filter selection and PDF toggle from localStorage on mount (e.g. staying on 'SAVED')
  useEffect(() => {
    if (readOnly) return;
    try {
      const saved = localStorage.getItem("job_butler_active_filter");
      if (
        saved &&
        (saved === "ALL" ||
          saved === "NEW_24H" ||
          STATUS_OPTIONS.includes(saved as MatchStatus))
      ) {
        setActiveFilter(saved);
      }
      const savedPdfOnly = localStorage.getItem("job_butler_pdf_only");
      if (savedPdfOnly === "true") {
        setPdfOnlyFilter(true);
      }
    } catch {}
  }, [readOnly]);

  function handleFilterSelect(nextFilter: string) {
    setActiveFilter(nextFilter);
    try {
      localStorage.setItem("job_butler_active_filter", nextFilter);
    } catch {}
  }

  function togglePdfOnlyFilter() {
    setPdfOnlyFilter((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("job_butler_pdf_only", String(next));
      } catch {}
      addToast(
        next
          ? "Filtered to roles with Tailored PDFs ready"
          : "Showing all roles in current filter",
        "info"
      );
      return next;
    });
  }

  // Viewport-fixed floating toast notification state
  const [toasts, setToasts] = useState<
    Array<{
      id: string;
      type: "loading" | "success" | "info" | "error";
      message: string;
    }>
  >([]);

  const addToast = (
    message: string,
    type: "loading" | "success" | "info" | "error" = "info",
    id?: string
  ) => {
    const toastId = id || Math.random().toString(36).substring(2, 9);
    setToasts((prev) => {
      const existing = prev.findIndex((t) => t.id === toastId);
      if (existing >= 0) {
        const copy = [...prev];
        copy[existing] = { id: toastId, type, message };
        return copy;
      }
      return [...prev, { id: toastId, type, message }];
    });

    if (type !== "loading") {
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== toastId));
      }, 5000);
    }
    return toastId;
  };

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };
  const [snapshotModalMatch, setSnapshotModalMatch] = useState<EvaluatedJobMatch | null>(null);
  const [showQueueModal, setShowQueueModal] = useState(false);
  const [customUrl, setCustomUrl] = useState("");
  const [queueMessage, setQueueMessage] = useState<string | null>(null);
  const [batchMaxJobs, setBatchMaxJobs] = useState<number>(10);
  const [runningDiscovery, setRunningDiscovery] = useState(false);
  const [selectedJobIds, setSelectedJobIds] = useState<string[]>([]);
  const [collapsedMatchIds, setCollapsedMatchIds] = useState<string[]>([]);
  const [queuedTailorJobIds, setQueuedTailorJobIds] = useState<string[]>([]);
  const [tailoringBatch, setTailoringBatch] = useState(false);
  const [deletingMatches, setDeletingMatches] = useState(false);
  const [loadingArtifactId, setLoadingArtifactId] = useState<string | null>(null);
  const router = useRouter();
  const [trackedTaskIds, setTrackedTaskIds] = useState<string[]>([]);

  // Sync state whenever server re-renders initialMatches
  useEffect(() => {
    setMatches(initialMatches);
  }, [initialMatches]);

  // On mount, check if there are tasks currently pending/processing in Neon
  useEffect(() => {
    let mounted = true;
    async function checkActiveTasks() {
      try {
        const res = await fetch("/api/tasks?active=true");
        if (!res.ok) return;
        const data = await res.json();
        const activeTasks: Array<{ id: string; job_id?: string; task_type: string }> =
          data.tasks || [];
        if (mounted && activeTasks.length > 0) {
          const ids = activeTasks.map((t) => t.id);
          setTrackedTaskIds((prev) => Array.from(new Set([...prev, ...ids])));

          const activeJobIds = activeTasks
            .filter((t) => t.task_type === "REGENERATE_RESUME" && t.job_id)
            .map((t) => String(t.job_id));
          if (activeJobIds.length > 0) {
            setQueuedTailorJobIds((prev) =>
              Array.from(new Set([...prev, ...activeJobIds]))
            );
          }
        }
      } catch {}
    }
    checkActiveTasks();
    return () => {
      mounted = false;
    };
  }, []);

  // Targeted active poller: only runs when tasks are actively tracked
  useEffect(() => {
    if (trackedTaskIds.length === 0) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/tasks?ids=${trackedTaskIds.join(",")}`);
        if (!res.ok) return;
        const data = await res.json();
        const tasks: Array<{
          id: string;
          job_id?: string;
          status: string;
          task_type: string;
          error_message?: string;
        }> = data.tasks || [];

        const finished = tasks.filter(
          (t) => t.status === "COMPLETED" || t.status === "FAILED"
        );

        if (finished.length > 0) {
          const finishedIds = new Set(finished.map((t) => t.id));
          const finishedJobIds = finished
            .map((t) => t.job_id)
            .filter(Boolean) as string[];

          if (finishedJobIds.length > 0) {
            setQueuedTailorJobIds((prev) =>
              prev.filter((id) => !finishedJobIds.includes(id))
            );
          }

          setTrackedTaskIds((prev) =>
            prev.filter((id) => !finishedIds.has(id))
          );

          // Refresh the page server data (re-queries Neon and updates initialMatches)
          router.refresh();

          const completedCount = finished.filter(
            (t) => t.status === "COMPLETED"
          ).length;
          const failedCount = finished.filter(
            (t) => t.status === "FAILED"
          ).length;

          if (completedCount > 0) {
            const msg = `✓ Local worker finished processing (${completedCount} role(s) ready)! Feed refreshed.`;
            addToast(msg, "success", "tailor-job");
          } else if (failedCount > 0) {
            const msg = `Task finished with an error. Check local worker logs.`;
            addToast(msg, "error", "tailor-job");
          }
        }
      } catch {
        // Non-fatal, retries on next tick
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [trackedTaskIds, router]);

  const fresh24hCount = matches.filter(
    (m) => m.status === "NEW_MATCH" && isPostedWithinLast24Hours(m)
  ).length;

  const totalPdfReadyCount = matches.filter(
    (m) => Boolean(m.resume_storage_key) && m.status !== "ARCHIVED"
  ).length;

  const filteredMatches = matches.filter((m) => {
    let statusMatch = false;
    if (activeFilter === "ALL") {
      statusMatch = m.status !== "ARCHIVED";
    } else if (activeFilter === "NEW_24H") {
      statusMatch = m.status === "NEW_MATCH" && isPostedWithinLast24Hours(m);
    } else {
      statusMatch = m.status === activeFilter;
    }

    if (!statusMatch) return false;

    if (pdfOnlyFilter && !m.resume_storage_key) {
      return false;
    }

    return true;
  });

  async function handleStatusChange(matchId: string, nextStatus: MatchStatus) {
    if (readOnly) return;
    setMatches((prev) =>
      prev.map((m) => (m.id === matchId ? { ...m, status: nextStatus } : m))
    );
    addToast(`Stage updated to ${nextStatus.replace("_", " ")}`, "info");
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
    let newTaskId: string | null = null;
    if (onEnqueueUrl) {
      const res = await onEnqueueUrl(customUrl.trim());
      if (res && typeof res === "object" && "taskId" in res && res.taskId) {
        newTaskId = res.taskId;
      }
    } else {
      const res = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_type: "EVALUATE_URL",
          payload: { url: customUrl.trim() },
        }),
      });
      const data = await res.json();
      if (data?.task?.id) {
        newTaskId = data.task.id;
      }
    }
    if (newTaskId) {
      setTrackedTaskIds((prev) => Array.from(new Set([...prev, newTaskId!])));
    }
    setCustomUrl("");
    const msg =
      "URL queued! Worker is scraping & scoring; feed will auto-refresh on completion.";
    setQueueMessage(msg);
    addToast(msg, "loading", "evaluate-url");
  }

  async function handleRunBatchDiscovery() {
    if (readOnly) return;
    try {
      setRunningDiscovery(true);
      let newTaskId: string | null = null;
      if (onRunBatchDiscovery) {
        const res = await onRunBatchDiscovery(batchMaxJobs);
        if (res && typeof res === "object" && "taskId" in res && res.taskId) {
          newTaskId = res.taskId;
        }
      } else {
        const res = await fetch("/api/tasks", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            task_type: "EVALUATE_URL",
            payload: { mode: "BATCH_DISCOVERY", max_jobs: batchMaxJobs },
          }),
        });
        const data = await res.json();
        if (data?.task?.id) {
          newTaskId = data.task.id;
        }
      }
      if (newTaskId) {
        setTrackedTaskIds((prev) => Array.from(new Set([...prev, newTaskId!])));
      }
      const noticeMsg = `Discovery scrape queued (max ${batchMaxJobs} jobs)! Local worker is evaluating roles; feed will auto-refresh on completion.`;
      addToast(noticeMsg, "loading", "batch-discovery");
    } finally {
      setRunningDiscovery(false);
    }
  }

  function toggleSelectJob(jobId: string) {
    if (readOnly) return;
    setSelectedJobIds((prev) =>
      prev.includes(jobId) ? prev.filter((id) => id !== jobId) : [...prev, jobId]
    );
  }

  function handleSelectAllUntailored() {
    if (readOnly) return;
    const visibleJobIds = filteredMatches.map((m) => m.job_id);
    const allSelected =
      visibleJobIds.length > 0 &&
      visibleJobIds.every((id) => selectedJobIds.includes(id));
    if (allSelected) {
      setSelectedJobIds([]);
    } else {
      setSelectedJobIds(visibleJobIds);
    }
  }

  function toggleCollapseMatch(matchId: string) {
    setCollapsedMatchIds((prev) =>
      prev.includes(matchId)
        ? prev.filter((id) => id !== matchId)
        : [...prev, matchId]
    );
  }

  function handleToggleCollapseVisible() {
    const targetIds =
      selectedJobIds.length > 0
        ? filteredMatches
            .filter((m) => selectedJobIds.includes(m.job_id))
            .map((m) => m.id)
        : filteredMatches.map((m) => m.id);
    if (targetIds.length === 0) return;

    const allTargetCollapsed = targetIds.every((id) =>
      collapsedMatchIds.includes(id)
    );
    if (allTargetCollapsed) {
      setCollapsedMatchIds((prev) =>
        prev.filter((id) => !targetIds.includes(id))
      );
    } else {
      setCollapsedMatchIds((prev) =>
        Array.from(new Set([...prev, ...targetIds]))
      );
    }
  }

  async function handleDeleteMatches(targetMatches: EvaluatedJobMatch[]) {
    if (readOnly || targetMatches.length === 0) return;
    const matchIds = targetMatches.map((m) => m.id);
    const jobIds = targetMatches.map((m) => m.job_id);
    try {
      setDeletingMatches(true);
      setMatches((prev) => prev.filter((m) => !matchIds.includes(m.id)));
      setSelectedJobIds((prev) => prev.filter((id) => !jobIds.includes(id)));
      if (onDeleteMatches) {
        await onDeleteMatches(matchIds);
      }
      const deleteMsg = `Deleted ${matchIds.length} job card(s) and purged associated PDFs from storage.`;
      addToast(deleteMsg, "info");
    } finally {
      setDeletingMatches(false);
    }
  }

  async function handleTailorJobs(jobIds: string[]) {
    if (readOnly || jobIds.length === 0) return;
    try {
      setTailoringBatch(true);
      const newIds: string[] = [];
      if (onBatchTailorJobs) {
        const res = await onBatchTailorJobs(jobIds);
        if (res && typeof res === "object" && "taskIds" in res && Array.isArray(res.taskIds)) {
          newIds.push(...res.taskIds);
        }
      } else {
        for (const jobId of jobIds) {
          const res = await fetch("/api/tasks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              job_id: jobId,
              task_type: "REGENERATE_RESUME",
              payload: {},
            }),
          });
          const data = await res.json();
          if (data?.task?.id) {
            newIds.push(data.task.id);
          }
        }
      }
      if (newIds.length > 0) {
        setTrackedTaskIds((prev) => Array.from(new Set([...prev, ...newIds])));
      }
      setQueuedTailorJobIds((prev) => Array.from(new Set([...prev, ...jobIds])));
      setSelectedJobIds((prev) => prev.filter((id) => !jobIds.includes(id)));
      const tailorMsg = `Queued ${jobIds.length} role(s) for 1-page Typst Resume & Cover Letter compilation! Feed will auto-refresh as your worker completes them.`;
      addToast(tailorMsg, "loading", "tailor-job");
    } finally {
      setTailoringBatch(false);
    }
  }

  const collapseTargetIds =
    selectedJobIds.length > 0
      ? filteredMatches
          .filter((m) => selectedJobIds.includes(m.job_id))
          .map((m) => m.id)
      : filteredMatches.map((m) => m.id);
  const areTargetCardsCollapsed =
    collapseTargetIds.length > 0 &&
    collapseTargetIds.every((id) => collapsedMatchIds.includes(id));

  return (
    <div className="space-y-4">
      {/* 1. Dedicated Discovery & URL Ingestion Bar (Anchored separately so buttons never shift) */}
      {!readOnly && (
        <div className="flex flex-wrap items-center justify-between gap-3 bg-slate-900/70 border border-slate-800 rounded-xl px-4 py-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Job Discovery &amp; Queue
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center bg-slate-950 border border-slate-700 rounded-lg overflow-hidden">
              <label
                htmlFor="batch-max-jobs"
                className="px-2.5 py-1.5 text-xs text-slate-400 border-r border-slate-800"
              >
                Max Jobs
              </label>
              <div className="relative flex items-center">
                <select
                  id="batch-max-jobs"
                  aria-label="Maximum jobs per discovery scrape"
                  value={batchMaxJobs}
                  onChange={(e) => setBatchMaxJobs(Number(e.target.value))}
                  disabled={runningDiscovery}
                  className="appearance-none bg-slate-950 pl-3 pr-8 py-1.5 text-xs font-semibold text-white focus:outline-none cursor-pointer"
                >
                  {BATCH_SIZE_OPTIONS.map((count) => (
                    <option key={count} value={count}>
                      {count}
                    </option>
                  ))}
                </select>
                <svg
                  aria-hidden="true"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  className="pointer-events-none absolute right-2.5 h-3.5 w-3.5 text-slate-400"
                >
                  <path
                    fillRule="evenodd"
                    d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                    clipRule="evenodd"
                  />
                </svg>
              </div>
            </div>
            <button
              onClick={handleRunBatchDiscovery}
              disabled={runningDiscovery}
              className="px-3.5 py-2 rounded-lg text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-50 transition"
            >
              {runningDiscovery
                ? "Queuing Scrape..."
                : `🔄 Run Discovery Scrape (${batchMaxJobs})`}
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
        </div>
      )}

      {/* 2. Stage Filter Tabs & Batch Selection / Collapse Controls */}
      <div className="bg-slate-900/50 border border-slate-800/90 rounded-xl p-3.5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => handleFilterSelect("ALL")}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                activeFilter === "ALL"
                  ? "bg-emerald-500 text-slate-950"
                  : "bg-slate-800 text-slate-300 hover:bg-slate-700"
              }`}
            >
              ALL
            </button>
            <button
              onClick={() => handleFilterSelect("NEW_24H")}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                activeFilter === "NEW_24H"
                  ? "bg-amber-400 text-slate-950"
                  : "bg-amber-950/70 text-amber-300 border border-amber-800/70 hover:bg-amber-900/70"
              }`}
            >
              🔥 NEW (&lt; 24H) ({fresh24hCount})
            </button>
            {STATUS_OPTIONS.map((status) => (
              <button
                key={status}
                onClick={() => handleFilterSelect(status)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                  activeFilter === status
                    ? "bg-emerald-500 text-slate-950"
                    : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                }`}
              >
                {status.replace("_", " ")}
              </button>
            ))}

            <div className="h-4 w-px bg-slate-700/80 mx-1 hidden sm:block" />

            {/* Additive PDF Ready Toggle */}
            <button
              onClick={togglePdfOnlyFilter}
              title="Toggle to show only jobs with PDFs ready in current view"
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition ${
                pdfOnlyFilter
                  ? "bg-indigo-600 text-white shadow-md shadow-indigo-900/40 border border-indigo-400"
                  : "bg-indigo-950/50 text-indigo-300 border border-indigo-800/60 hover:bg-indigo-900/60"
              }`}
            >
              <span className={pdfOnlyFilter ? "text-white" : "text-indigo-400 font-bold"}>
                ✓
              </span>
              PDFs Ready Only ({totalPdfReadyCount})
            </button>
          </div>
          <span className="text-xs text-slate-400">
            Showing {filteredMatches.length} of {matches.length} job{matches.length === 1 ? "" : "s"}
            {pdfOnlyFilter && " (PDFs only)"}
          </span>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 pt-2.5 border-t border-slate-800/80">
          <div className="flex flex-wrap items-center gap-2">
            {!readOnly && (
              <button
                type="button"
                onClick={handleSelectAllUntailored}
                disabled={filteredMatches.length === 0}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-slate-200 hover:bg-slate-700 border border-slate-700 disabled:opacity-40 disabled:pointer-events-none transition"
              >
                {filteredMatches.length > 0 &&
                filteredMatches.every((m) => selectedJobIds.includes(m.job_id))
                  ? "Clear Selection"
                  : "Select All Visible"}
              </button>
            )}
            <button
              type="button"
              onClick={handleToggleCollapseVisible}
              disabled={filteredMatches.length === 0}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800/80 text-slate-300 hover:bg-slate-700 border border-slate-700 disabled:opacity-40 disabled:pointer-events-none transition"
            >
              {areTargetCardsCollapsed
                ? selectedJobIds.length > 0
                  ? `▾ Expand Selected (${selectedJobIds.length})`
                  : "▾ Expand All Visible"
                : selectedJobIds.length > 0
                ? `▴ Collapse Selected (${selectedJobIds.length})`
                : "▴ Collapse All Visible"}
            </button>
          </div>

          {!readOnly && selectedJobIds.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => handleTailorJobs(selectedJobIds)}
                disabled={tailoringBatch || deletingMatches}
                className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-amber-500 text-slate-950 hover:bg-amber-400 disabled:opacity-50 transition"
              >
                {tailoringBatch
                  ? "Queuing PDFs..."
                  : `✨ Generate PDFs for Selected (${selectedJobIds.length})`}
              </button>
              <button
                type="button"
                onClick={() =>
                  handleDeleteMatches(
                    matches.filter((m) => selectedJobIds.includes(m.job_id))
                  )
                }
                disabled={deletingMatches || tailoringBatch}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-rose-950/90 text-rose-200 hover:bg-rose-900 border border-rose-800 disabled:opacity-50 transition"
              >
                {deletingMatches
                  ? "Deleting..."
                  : `🗑️ Delete Selected (${selectedJobIds.length})`}
              </button>
            </div>
          )}
        </div>
      </div>

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
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  {!readOnly && (
                    <input
                      type="checkbox"
                      aria-label={`Select ${match.title} at ${match.company} for batch PDF generation`}
                      checked={selectedJobIds.includes(match.job_id)}
                      onChange={() => toggleSelectJob(match.job_id)}
                      className="mt-1.5 h-4 w-4 shrink-0 rounded border-slate-600 bg-slate-950 text-emerald-500 focus:ring-emerald-500 cursor-pointer"
                    />
                  )}
                  <div className="flex-1 min-w-0 space-y-1.5">
                    {/* Row 1: Job Title + Company Badge */}
                    <div className="flex items-center gap-2.5 flex-wrap">
                      <h2 className="text-lg font-bold text-white leading-snug">
                        {match.title}
                      </h2>
                      <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-medium">
                        {match.company}
                      </span>
                    </div>

                    {/* Row 2: Source, Remote, <24h, Salary, and PDF Status Badges */}
                    <div className="flex items-center gap-2 flex-wrap">
                      {(() => {
                        const srcBadge = formatJobSource(match.source);
                        return (
                          <span
                            className={`text-xs px-2 py-0.5 rounded font-medium ${srcBadge.className}`}
                          >
                            {srcBadge.label}
                          </span>
                        );
                      })()}
                      {match.is_remote && (
                        <span className="text-xs px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800/60">
                          Remote
                        </span>
                      )}
                      {isPostedWithinLast24Hours(match) && (
                        <span className="text-xs px-2 py-0.5 rounded bg-amber-950/90 text-amber-300 border border-amber-800/70 font-medium">
                          🔥 &lt; 24h
                        </span>
                      )}
                      {match.salary_range && (
                        <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-amber-300 font-mono">
                          {match.salary_range}
                        </span>
                      )}
                      {match.resume_storage_key ? (
                        <span className="text-xs px-2 py-0.5 rounded bg-indigo-950/90 text-indigo-300 border border-indigo-800/60">
                          ✓ PDFs Ready
                        </span>
                      ) : queuedTailorJobIds.includes(match.job_id) ? (
                        <span className="text-xs px-2 py-0.5 rounded bg-amber-950/90 text-amber-300 border border-amber-800/60">
                          ⏳ Queued for PDF Tailoring
                        </span>
                      ) : (
                        <span className="text-xs px-2 py-0.5 rounded bg-slate-800/80 text-slate-400 border border-slate-700">
                          Discovered (No PDFs Yet)
                        </span>
                      )}
                    </div>

                    {/* Row 3: Location + Original Posting Link */}
                    <p className="text-xs text-slate-400">
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
                </div>

                {/* Fit & Semantic Score Badges (Locked to Right) */}
                <div className="flex items-center gap-3 shrink-0">
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

              {/* Collapsible LLM Fit Rationale & Skill Alignment Badges */}
              {!collapsedMatchIds.includes(match.id) && (
                <>
                  <p className="text-sm text-slate-300 leading-relaxed bg-slate-950/60 border border-slate-800/80 rounded-lg p-3">
                    {match.fit_rationale}
                  </p>

                  <div className="space-y-2">
                    <div className="flex items-start gap-2">
                      <span className="w-16 shrink-0 pt-0.5 text-xs text-slate-400">
                        Matched:
                      </span>
                      <div className="flex flex-wrap gap-1.5 flex-1 min-w-0">
                        {match.matched_skills.map((skill) => (
                          <span
                            key={skill}
                            className="text-xs px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-300 border border-emerald-800/50"
                          >
                            ✓ {skill}
                          </span>
                        ))}
                      </div>
                    </div>

                    {match.missing_skills.length > 0 && (
                      <div className="flex items-start gap-2">
                        <span className="w-16 shrink-0 pt-0.5 text-xs text-slate-400">
                          Gaps:
                        </span>
                        <div className="flex flex-wrap gap-1.5 flex-1 min-w-0">
                          {match.missing_skills.map((gap) => (
                            <span
                              key={gap}
                              className="text-xs px-2 py-0.5 rounded bg-rose-950/70 text-rose-300 border border-rose-800/50"
                            >
                              ! {gap}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </>
              )}

              {/* Action Bar: Presigned PDFs, On-Demand Tailoring, Audit Snapshot Viewer, Status Mutation */}
              <div className="pt-3 border-t border-slate-800/80 flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  {match.resume_storage_key ? (
                    <>
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
                      {!readOnly && (
                        <button
                          onClick={() => handleTailorJobs([match.job_id])}
                          disabled={tailoringBatch}
                          className="px-2.5 py-1.5 rounded-md text-xs font-medium bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 transition"
                        >
                          🔄 Regenerate PDFs
                        </button>
                      )}
                    </>
                  ) : (
                    !readOnly && (
                      <button
                        onClick={() => handleTailorJobs([match.job_id])}
                        disabled={tailoringBatch || queuedTailorJobIds.includes(match.job_id)}
                        className="px-3.5 py-1.5 rounded-md text-xs font-semibold bg-amber-500/90 hover:bg-amber-400 text-slate-950 disabled:opacity-50 transition"
                      >
                        {queuedTailorJobIds.includes(match.job_id)
                          ? "⏳ Queued for Worker..."
                          : "✨ Generate Resume & Cover Letter PDFs"}
                      </button>
                    )
                  )}
                  <button
                    type="button"
                    onClick={() => toggleCollapseMatch(match.id)}
                    className="px-2.5 py-1.5 rounded-md text-xs font-medium bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 transition"
                  >
                    {collapsedMatchIds.includes(match.id)
                      ? "▾ Expand Details"
                      : "▴ Collapse Details"}
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  <label className="text-xs text-slate-400">Stage:</label>
                  <div className="relative flex items-center">
                    <select
                      aria-label={`Status for ${match.title}`}
                      disabled={readOnly}
                      value={match.status}
                      onChange={(e) =>
                        handleStatusChange(match.id, e.target.value as MatchStatus)
                      }
                      className="appearance-none bg-slate-950 border border-slate-700 rounded-md pl-3 pr-8 py-1 text-xs text-slate-200 focus:outline-none focus:border-slate-500 disabled:opacity-50 cursor-pointer"
                    >
                      {STATUS_OPTIONS.map((st) => (
                        <option key={st} value={st}>
                          {st}
                        </option>
                      ))}
                    </select>
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                      className="pointer-events-none absolute right-2.5 h-3.5 w-3.5 text-slate-400"
                    >
                      <path
                        fillRule="evenodd"
                        d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
                        clipRule="evenodd"
                      />
                    </svg>
                  </div>
                  {!readOnly && (
                    <button
                      type="button"
                      onClick={() => handleDeleteMatches([match])}
                      disabled={deletingMatches}
                      title="Delete job card and purge associated PDFs from storage"
                      className="px-2.5 py-1 rounded-md text-xs font-medium bg-rose-950/60 hover:bg-rose-900 text-rose-300 border border-rose-800/60 disabled:opacity-50 transition"
                    >
                      🗑️ Delete
                    </button>
                  )}
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
      {/* Viewport-Fixed Floating Toast Stack (visible anywhere on screen) */}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2.5 max-w-sm w-full pointer-events-none px-3 sm:px-0">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`pointer-events-auto flex items-start justify-between gap-3 p-3.5 rounded-xl border shadow-2xl backdrop-blur-md transition-all duration-300 animate-in slide-in-from-bottom-3 ${
              toast.type === "loading"
                ? "bg-amber-950/95 border-amber-700/80 text-amber-200"
                : toast.type === "success"
                ? "bg-emerald-950/95 border-emerald-700/80 text-emerald-200"
                : toast.type === "error"
                ? "bg-rose-950/95 border-rose-700/80 text-rose-200"
                : "bg-slate-900/95 border-slate-700 text-slate-200"
            }`}
          >
            <div className="flex items-center gap-2.5 text-xs font-medium">
              {toast.type === "loading" && (
                <span className="w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse flex-shrink-0" />
              )}
              {toast.type === "success" && (
                <span className="text-emerald-400 font-bold text-sm flex-shrink-0">✓</span>
              )}
              {toast.type === "error" && (
                <span className="text-rose-400 font-bold text-sm flex-shrink-0">✕</span>
              )}
              {toast.type === "info" && (
                <span className="text-sky-400 font-bold text-sm flex-shrink-0">ℹ</span>
              )}
              <span className="leading-snug">{toast.message}</span>
            </div>
            <button
              onClick={() => removeToast(toast.id)}
              className="text-slate-400 hover:text-white text-xs font-bold ml-2 flex-shrink-0"
              aria-label="Close notification"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

