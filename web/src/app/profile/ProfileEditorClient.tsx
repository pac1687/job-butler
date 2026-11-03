"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import type {
  JobPreferencesRecord,
  MasterProfileRecord,
  TailoringRulesRecord,
} from "@/lib/db";
import {
  CATEGORY_LABELS,
  detectUnlistedSkillsFromBullets,
} from "@/lib/skill-sync";
import {
  saveMasterProfileDirectAction,
  updateJobPreferencesAction,
  updateTailoringRulesAction,
  uploadAndEnqueueMasterResumeAction,
} from "./actions";

interface ProfileEditorClientProps {
  initialProfile: MasterProfileRecord;
  initialRules: TailoringRulesRecord;
  initialPreferences?: JobPreferencesRecord;
}

export function ProfileEditorClient({
  initialProfile,
  initialRules,
  initialPreferences,
}: ProfileEditorClientProps) {
  const defaultProfileLocation = String(
    initialProfile?.basics?.location || ""
  ).trim();
  const initialBoardSettings = initialPreferences?.ats_boards || {};

  const [positiveTitles, setPositiveTitles] = useState<string[]>(
    initialPreferences?.positive_titles || [
      "Full Stack Engineer",
      "Senior Software Engineer",
    ]
  );
  const [newPositiveTitle, setNewPositiveTitle] = useState("");
  const [negativeKeywords, setNegativeKeywords] = useState<string[]>(
    initialPreferences?.negative_title_keywords || [
      "Manager",
      "Staff",
      "Director",
    ]
  );
  const [newNegativeKeyword, setNewNegativeKeyword] = useState("");
  const [preferredLocations, setPreferredLocations] = useState<string[]>(
    initialBoardSettings.preferred_locations &&
      initialBoardSettings.preferred_locations.length > 0
      ? initialBoardSettings.preferred_locations
      : defaultProfileLocation &&
          !defaultProfileLocation.toLowerCase().includes("remote")
        ? [defaultProfileLocation]
        : []
  );
  const [newLocation, setNewLocation] = useState("");
  const [allowRemote, setAllowRemote] = useState<boolean>(
    initialBoardSettings.allow_remote ?? true
  );
  const [maxPerCompany, setMaxPerCompany] = useState<number>(
    initialBoardSettings.max_per_company ?? 2
  );
  const [enableTier1, setEnableTier1] = useState<boolean>(
    initialBoardSettings.enable_tier1 ?? false
  );
  const [enableTier2, setEnableTier2] = useState<boolean>(
    initialBoardSettings.enable_tier2 ?? true
  );
  const [minSemanticScore, setMinSemanticScore] = useState<number>(
    Number(initialPreferences?.min_semantic_score ?? 0.7)
  );
  const [naturalLanguageNotes, setNaturalLanguageNotes] = useState<string>(
    initialPreferences?.natural_language_notes || ""
  );

  const [forbiddenTerms, setForbiddenTerms] = useState<string[]>(
    initialRules.forbidden_terms
  );
  const [newForbidden, setNewForbidden] = useState("");
  const [protectedMetrics, setProtectedMetrics] = useState<string[]>(
    initialRules.protected_metrics
  );
  const [newMetric, setNewMetric] = useState("");
  const [allowRephrasing, setAllowRephrasing] = useState<boolean>(
    initialRules.allow_rephrasing
  );
  const [maxBullets, setMaxBullets] = useState<number>(
    initialRules.max_bullets_per_role
  );
  const [experience, setExperience] = useState(initialProfile.experience);
  const [skills, setSkills] = useState<Record<string, string[]>>(
    initialProfile?.skills || {}
  );
  const [newSkillInputs, setNewSkillInputs] = useState<Record<string, string>>({});
  const [pendingSyncItems, setPendingSyncItems] = useState<
    { skill: string; category: string; enabled: boolean }[] | null
  >(null);
  const [statusBanner, setStatusBanner] = useState<string | null>(null);
  const router = useRouter();
  const [parsingTaskId, setParsingTaskId] = useState<string | null>(null);

  useEffect(() => {
    if (!parsingTaskId) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/tasks?ids=${parsingTaskId}`);
        if (!res.ok) return;
        const data = await res.json();
        const task = (data.tasks || [])[0];
        if (!task) return;

        if (task.status === "COMPLETED") {
          setStatusBanner(
            "✓ Master resume successfully parsed and updated by local worker!"
          );
          setParsingTaskId(null);
          router.refresh();
        } else if (task.status === "FAILED") {
          setStatusBanner(
            `Resume parsing failed: ${task.error_message || "worker error"}`
          );
          setParsingTaskId(null);
        }
      } catch {
        // Retry on next interval
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [parsingTaskId, router]);

  async function handleSavePreferences(e: React.FormEvent) {
    e.preventDefault();
    await updateJobPreferencesAction({
      positive_titles: positiveTitles,
      negative_title_keywords: negativeKeywords,
      natural_language_notes: naturalLanguageNotes,
      min_semantic_score: minSemanticScore,
      preferred_locations: preferredLocations,
      allow_remote: allowRemote,
      max_per_company: maxPerCompany,
      enable_tier1: enableTier1,
      enable_tier2: enableTier2,
    });
    setStatusBanner(
      "Saved discovery location filters, company diversity cap, and target title preferences."
    );
  }

  async function handleSaveGuardrails(e: React.FormEvent) {
    e.preventDefault();
    await updateTailoringRulesAction({
      forbidden_terms: forbiddenTerms,
      protected_metrics: protectedMetrics,
      max_bullets_per_role: maxBullets,
      allow_rephrasing: allowRephrasing,
    });
    setStatusBanner("Saved tailoring guardrail rules to Neon PostgreSQL.");
  }

  function handleRemoveSkill(category: string, skillToRemove: string) {
    setSkills((prev) => ({
      ...prev,
      [category]: (prev[category] || []).filter((s) => s !== skillToRemove),
    }));
  }

  function handleAddSkill(category: string) {
    const val = (newSkillInputs[category] || "").trim();
    if (!val) return;
    setSkills((prev) => ({
      ...prev,
      [category]: [...(prev[category] || []), val],
    }));
    setNewSkillInputs((prev) => ({ ...prev, [category]: "" }));
  }

  async function handleSaveSkills() {
    await saveMasterProfileDirectAction({
      basics: initialProfile.basics,
      skills,
      experience,
      education: initialProfile.education,
    });
    setStatusBanner("Saved Technical Skills inventory to Neon PostgreSQL.");
  }

  function scanBulletsAndPromptSync() {
    const allBullets = experience.flatMap((role) => role.bullets || []);
    const unlisted = detectUnlistedSkillsFromBullets(allBullets, skills);
    if (unlisted.length === 0) {
      setStatusBanner("No unlisted technologies found in experience bullets.");
      return;
    }
    setPendingSyncItems(
      unlisted.map((u) => ({
        skill: u.skill,
        category: u.suggestedCategory,
        enabled: true,
      }))
    );
  }

  async function handleSaveExperience() {
    const allBullets = experience.flatMap((role) => role.bullets || []);
    const unlisted = detectUnlistedSkillsFromBullets(allBullets, skills);
    if (unlisted.length > 0) {
      // Prompt user with sync modal
      setPendingSyncItems(
        unlisted.map((u) => ({
          skill: u.skill,
          category: u.suggestedCategory,
          enabled: true,
        }))
      );
      return;
    }

    await saveMasterProfileDirectAction({
      basics: initialProfile.basics,
      skills,
      experience,
      education: initialProfile.education,
    });
    setStatusBanner("Updated verified master resume bullets.");
  }

  async function handleConfirmSyncAndSave(syncSkills: boolean) {
    if (!pendingSyncItems) return;

    const updatedSkills: Record<string, string[]> = { ...skills };
    let addedCount = 0;

    if (syncSkills) {
      for (const item of pendingSyncItems) {
        if (!item.enabled || !item.skill.trim()) continue;
        const cat = item.category || "ai_developer_tooling";
        const currentList = updatedSkills[cat] || [];
        if (
          !currentList.some(
            (s) => s.toLowerCase() === item.skill.trim().toLowerCase()
          )
        ) {
          updatedSkills[cat] = [...currentList, item.skill.trim()];
          addedCount++;
        }
      }
      setSkills(updatedSkills);
    }

    await saveMasterProfileDirectAction({
      basics: initialProfile.basics,
      skills: updatedSkills,
      experience,
      education: initialProfile.education,
    });

    setPendingSyncItems(null);
    setStatusBanner(
      syncSkills && addedCount > 0
        ? `Saved experience bullets and synced ${addedCount} new skill${
            addedCount === 1 ? "" : "s"
          } to Technical Skills.`
        : "Saved verified master resume bullets."
    );
  }

  function handleBulletChange(roleIdx: number, bulletIdx: number, val: string) {
    setExperience((prev) =>
      prev.map((role, rIdx) =>
        rIdx === roleIdx
          ? {
              ...role,
              bullets: role.bullets.map((b, bIdx) =>
                bIdx === bulletIdx ? val : b
              ),
            }
          : role
      )
    );
  }

  function handleAddBullet(roleIdx: number) {
    setExperience((prev) =>
      prev.map((role, rIdx) =>
        rIdx === roleIdx
          ? { ...role, bullets: [...role.bullets, ""] }
          : role
      )
    );
  }

  function handleRemoveBullet(roleIdx: number, bulletIdx: number) {
    setExperience((prev) =>
      prev.map((role, rIdx) =>
        rIdx === roleIdx
          ? {
              ...role,
              bullets: role.bullets.filter((_, bIdx) => bIdx !== bulletIdx),
            }
          : role
      )
    );
  }

  return (
    <div className="space-y-8">
      {/* Sync Skills Prompt Modal (Option 1) */}
      {pendingSyncItems && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-lg w-full p-6 shadow-2xl space-y-4 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2.5">
                <span className="text-xl">⚡</span>
                <h3 className="text-base font-bold text-white">
                  Sync Detected Technologies to Skills?
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setPendingSyncItems(null)}
                className="text-slate-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              We detected {pendingSyncItems.length} technology mention
              {pendingSyncItems.length === 1 ? "" : "s"} in your updated experience bullets
              that aren’t yet in your Technical Skills section. Select which ones to add:
            </p>

            <div className="max-h-60 overflow-y-auto space-y-2.5 pr-1">
              {pendingSyncItems.map((item, idx) => (
                <div
                  key={idx}
                  className="flex items-center gap-3 bg-slate-950/80 border border-slate-800 rounded-lg p-2.5"
                >
                  <input
                    type="checkbox"
                    checked={item.enabled}
                    onChange={(e) =>
                      setPendingSyncItems((prev) =>
                        prev
                          ? prev.map((p, pIdx) =>
                              pIdx === idx ? { ...p, enabled: e.target.checked } : p
                            )
                          : null
                      )
                    }
                    className="rounded border-slate-700 bg-slate-900 text-indigo-500 focus:ring-0"
                  />
                  <div className="flex-1">
                    <input
                      type="text"
                      value={item.skill}
                      onChange={(e) =>
                        setPendingSyncItems((prev) =>
                          prev
                            ? prev.map((p, pIdx) =>
                                pIdx === idx ? { ...p, skill: e.target.value } : p
                              )
                            : null
                        )
                      }
                      className="bg-transparent border-b border-transparent focus:border-indigo-500 text-xs font-semibold text-white focus:outline-none w-full"
                    />
                  </div>
                  <select
                    value={item.category}
                    onChange={(e) =>
                      setPendingSyncItems((prev) =>
                        prev
                          ? prev.map((p, pIdx) =>
                              pIdx === idx ? { ...p, category: e.target.value } : p
                            )
                          : null
                      )
                    }
                    className="bg-slate-900 border border-slate-700 rounded text-[11px] text-slate-200 px-2 py-1 focus:outline-none"
                  >
                    <option value="ai_developer_tooling">AI &amp; Developer Tooling</option>
                    <option value="cloud">Cloud &amp; DevOps</option>
                    <option value="languages">Languages</option>
                    <option value="frameworks">Frameworks &amp; Libraries</option>
                    <option value="databases">Databases</option>
                  </select>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
              <button
                type="button"
                onClick={() => setPendingSyncItems(null)}
                className="px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => handleConfirmSyncAndSave(false)}
                className="px-3.5 py-1.5 rounded-lg text-xs font-medium bg-slate-800 text-slate-300 hover:bg-slate-700"
              >
                Skip &amp; Save Bullets Only
              </button>
              <button
                type="button"
                onClick={() => handleConfirmSyncAndSave(true)}
                className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 text-white hover:bg-indigo-500 shadow-md shadow-indigo-500/20"
              >
                Add Selected &amp; Save
              </button>
            </div>
          </div>
        </div>
      )}

      {statusBanner && (
        <div className="fixed bottom-5 right-5 z-50 max-w-sm w-full pointer-events-none px-3 sm:px-0">
          <div className="pointer-events-auto flex items-start justify-between gap-3 p-3.5 rounded-xl border border-emerald-700/80 bg-emerald-950/95 text-emerald-200 shadow-2xl backdrop-blur-md animate-in slide-in-from-bottom-3">
            <div className="flex items-center gap-2.5 text-xs font-medium">
              <span className="text-emerald-400 font-bold text-sm flex-shrink-0">✓</span>
              <span className="leading-snug">{statusBanner}</span>
            </div>
            <button
              onClick={() => setStatusBanner(null)}
              className="text-slate-400 hover:text-white text-xs font-bold ml-2 flex-shrink-0"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* 1. Resume PDF / DOCX Ingestion */}
      <section className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 space-y-4">
        <h2 className="text-lg font-bold text-white">
          1. Master Resume Ingestion (.PDF / .DOCX)
        </h2>
        <p className="text-xs text-slate-400">
          Extracts raw text server-side via pdf-parse / mammoth and enqueues a PARSE_MASTER_RESUME task for local LM Studio schema normalization.
        </p>
        <form
          action={async (formData) => {
            const res = await uploadAndEnqueueMasterResumeAction(formData);
            if (res?.taskId) {
              setParsingTaskId(res.taskId);
              setStatusBanner(
                "Uploaded resume! Local worker is parsing via LM Studio..."
              );
            } else {
              setStatusBanner(
                "Uploaded resume and enqueued PARSE_MASTER_RESUME task for local worker."
              );
            }
          }}
          className="flex flex-wrap items-center gap-4"
        >
          <input
            type="file"
            name="resumeFile"
            accept=".pdf,.docx,.txt"
            required
            className="text-xs text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-slate-800 file:text-white hover:file:bg-slate-700"
          />
          <button
            type="submit"
            className="px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-500 text-slate-950 hover:bg-emerald-400 transition"
          >
            Upload &amp; Enqueue Parsing
          </button>
        </form>
      </section>

      {/* 2. Job Discovery, Location & Company Diversity Settings */}
      <section className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 space-y-5">
        <div>
          <h2 className="text-lg font-bold text-white">
            2. Discovery Scrape, Location &amp; Diversity Filters
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Filter scraped postings to US/Global Remote or your local area, cap max matches per company so one employer cannot dominate your feed, and steer semantic ranking.
          </p>
        </div>

        <form onSubmit={handleSavePreferences} className="space-y-5">
          {/* Remote + Local Area Locations */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-2">
                Preferred Local Cities / States (For Hybrid or In-Office Roles)
              </label>
              <div className="flex flex-wrap gap-2 mb-2">
                {preferredLocations.map((loc) => (
                  <span
                    key={loc}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs bg-emerald-950/80 text-emerald-300 border border-emerald-800"
                  >
                    📍 {loc}
                    <button
                      type="button"
                      onClick={() =>
                        setPreferredLocations(
                          preferredLocations.filter((l) => l !== loc)
                        )
                      }
                      className="hover:text-white"
                    >
                      ✕
                    </button>
                  </span>
                ))}
                {preferredLocations.length === 0 && (
                  <span className="text-xs text-slate-500">
                    No local cities added (remote-only unless added)
                  </span>
                )}
              </div>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newLocation}
                  onChange={(e) => setNewLocation(e.target.value)}
                  placeholder="e.g., Austin, TX or Chicago, IL"
                  className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white flex-1"
                />
                <button
                  type="button"
                  onClick={() => {
                    if (newLocation.trim()) {
                      setPreferredLocations([
                        ...preferredLocations,
                        newLocation.trim(),
                      ]);
                      setNewLocation("");
                    }
                  }}
                  className="px-3 py-1.5 rounded-lg text-xs bg-slate-800 text-white"
                >
                  + Add Location
                </button>
              </div>
            </div>

            <div className="space-y-3 bg-slate-950/60 border border-slate-800 rounded-lg p-3.5">
              <label className="flex items-center gap-2.5 text-xs text-slate-200 cursor-pointer">
                <input
                  type="checkbox"
                  checked={allowRemote}
                  onChange={(e) => setAllowRemote(e.target.checked)}
                  className="rounded border-slate-700 bg-slate-950"
                />
                <span>
                  <strong>Include Remote Jobs (US / Global)</strong> — Automatically excludes foreign-only remote roles (e.g. UK, EMEA, India)
                </span>
              </label>

              <label className="flex items-center gap-2.5 text-xs text-slate-200 cursor-pointer">
                <input
                  type="checkbox"
                  checked={enableTier2}
                  onChange={(e) => setEnableTier2(e.target.checked)}
                  className="rounded border-slate-700 bg-slate-950"
                />
                <span>
                  <strong>Tier-2 JobSpy Discovery (LinkedIn &amp; Indeed)</strong> — Focuses on smaller &amp; mid-sized companies (filters out FAANG/mega-cap &amp; staffing spam)
                </span>
              </label>

              <label className="flex items-center gap-2.5 text-xs text-slate-400 cursor-pointer">
                <input
                  type="checkbox"
                  checked={enableTier1}
                  onChange={(e) => setEnableTier1(e.target.checked)}
                  className="rounded border-slate-700 bg-slate-950"
                />
                <span>
                  <strong>Include Tier-1 Big-Tech ATS Boards</strong> (Stripe, Cloudflare, OpenAI, Vercel, etc. — off by default)
                </span>
              </label>

              <div className="flex flex-wrap items-center gap-4 pt-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400">
                    Max Matches / Company:
                  </span>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={maxPerCompany}
                    onChange={(e) => setMaxPerCompany(Number(e.target.value))}
                    className="w-16 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400">
                    Min Vector Sim:
                  </span>
                  <input
                    type="number"
                    step={0.05}
                    min={0.4}
                    max={0.95}
                    value={minSemanticScore}
                    onChange={(e) =>
                      setMinSemanticScore(Number(e.target.value))
                    }
                    className="w-20 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs text-white"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Target Positive Titles & Negative Keywords */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-2">
                Target Role Titles (Positive Anchors)
              </label>
              <div className="flex flex-wrap gap-2 mb-2">
                {positiveTitles.map((title) => (
                  <span
                    key={title}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs bg-indigo-950/80 text-indigo-300 border border-indigo-800"
                  >
                    {title}
                    <button
                      type="button"
                      onClick={() =>
                        setPositiveTitles(
                          positiveTitles.filter((t) => t !== title)
                        )
                      }
                      className="hover:text-white"
                    >
                      ✕
                    </button>
                  </span>
                ))}
              </div>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newPositiveTitle}
                  onChange={(e) => setNewPositiveTitle(e.target.value)}
                  placeholder="Add target title (e.g., Full Stack Engineer)"
                  className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white flex-1"
                />
                <button
                  type="button"
                  onClick={() => {
                    if (newPositiveTitle.trim()) {
                      setPositiveTitles([
                        ...positiveTitles,
                        newPositiveTitle.trim(),
                      ]);
                      setNewPositiveTitle("");
                    }
                  }}
                  className="px-3 py-1.5 rounded-lg text-xs bg-slate-800 text-white"
                >
                  + Add Title
                </button>
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-2">
                Excluded Title Keywords (Deterministic Pre-Filter)
              </label>
              <div className="flex flex-wrap gap-2 mb-2">
                {negativeKeywords.map((kw) => (
                  <span
                    key={kw}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs bg-rose-950/80 text-rose-300 border border-rose-800"
                  >
                    {kw}
                    <button
                      type="button"
                      onClick={() =>
                        setNegativeKeywords(
                          negativeKeywords.filter((k) => k !== kw)
                        )
                      }
                      className="hover:text-white"
                    >
                      ✕
                    </button>
                  </span>
                ))}
              </div>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={newNegativeKeyword}
                  onChange={(e) => setNewNegativeKeyword(e.target.value)}
                  placeholder="Add excluded keyword (e.g., Manager, Principal)"
                  className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white flex-1"
                />
                <button
                  type="button"
                  onClick={() => {
                    if (newNegativeKeyword.trim()) {
                      setNegativeKeywords([
                        ...negativeKeywords,
                        newNegativeKeyword.trim(),
                      ]);
                      setNewNegativeKeyword("");
                    }
                  }}
                  className="px-3 py-1.5 rounded-lg text-xs bg-slate-800 text-white"
                >
                  + Exclude
                </button>
              </div>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-1">
              LLM Fit Scoring Guidance Notes
            </label>
            <input
              type="text"
              value={naturalLanguageNotes}
              onChange={(e) => setNaturalLanguageNotes(e.target.value)}
              placeholder="e.g., Prioritize product-focused full-stack TypeScript/Python roles; avoid pure DevOps or embedded C++."
              className="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white"
            />
          </div>

          <button
            type="submit"
            className="px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-500 text-slate-950 hover:bg-emerald-400 transition"
          >
            Save Discovery &amp; Location Preferences
          </button>
        </form>
      </section>

      {/* 3. Tailoring Guardrails & Constraint Configuration (FR-1.3) */}
      <section className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 space-y-5">
        <h2 className="text-lg font-bold text-white">
          3. Deterministic Tailoring Guardrails
        </h2>

        <form onSubmit={handleSaveGuardrails} className="space-y-5">
          {/* Forbidden Terms Denylist Chips */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-2">
              Forbidden Terms Denylist (Rejects any LLM bullet containing these tokens)
            </label>
            <div className="flex flex-wrap gap-2 mb-2">
              {forbiddenTerms.map((term) => (
                <span
                  key={term}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs bg-rose-950/80 text-rose-300 border border-rose-800"
                >
                  {term}
                  <button
                    type="button"
                    onClick={() =>
                      setForbiddenTerms(forbiddenTerms.filter((t) => t !== term))
                    }
                    className="hover:text-white"
                  >
                    ✕
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={newForbidden}
                onChange={(e) => setNewForbidden(e.target.value)}
                placeholder="Add forbidden term (e.g., Java, gRPC, COBOL)"
                className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white flex-1"
              />
              <button
                type="button"
                onClick={() => {
                  if (newForbidden.trim()) {
                    setForbiddenTerms([...forbiddenTerms, newForbidden.trim()]);
                    setNewForbidden("");
                  }
                }}
                className="px-3 py-1.5 rounded-lg text-xs bg-slate-800 text-white"
              >
                + Add Term
              </button>
            </div>
          </div>

          {/* Protected Metrics Chips */}
          <div>
            <label className="block text-xs font-semibold text-slate-300 mb-2">
              Protected Numerical Metrics (Strict Metric Lock)
            </label>
            <div className="flex flex-wrap gap-2 mb-2">
              {protectedMetrics.map((metric) => (
                <span
                  key={metric}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs bg-indigo-950/80 text-indigo-300 border border-indigo-800"
                >
                  {metric}
                  <button
                    type="button"
                    onClick={() =>
                      setProtectedMetrics(
                        protectedMetrics.filter((m) => m !== metric)
                      )
                    }
                    className="hover:text-white"
                  >
                    ✕
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={newMetric}
                onChange={(e) => setNewMetric(e.target.value)}
                placeholder="Add protected metric (e.g., 99.99%, 42%, 120ms)"
                className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white flex-1"
              />
              <button
                type="button"
                onClick={() => {
                  if (newMetric.trim()) {
                    setProtectedMetrics([...protectedMetrics, newMetric.trim()]);
                    setNewMetric("");
                  }
                }}
                className="px-3 py-1.5 rounded-lg text-xs bg-slate-800 text-white"
              >
                + Lock Metric
              </button>
            </div>
          </div>

          {/* Verbatim-Only Mode Toggle & Max Bullets */}
          <div className="flex flex-wrap items-center justify-between gap-4 pt-2 border-t border-slate-800">
            <label className="flex items-center gap-2.5 text-xs text-slate-200 cursor-pointer">
              <input
                type="checkbox"
                checked={!allowRephrasing}
                onChange={(e) => setAllowRephrasing(!e.target.checked)}
                className="rounded border-slate-700 bg-slate-950"
              />
              <span>
                <strong>Verbatim-Only Mode:</strong> Disable LLM rephrasing (use semantic selection &amp; reordering of verified source bullets only)
              </span>
            </label>

            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">Max Bullets / Role:</span>
              <input
                type="number"
                min={1}
                max={4}
                value={maxBullets}
                onChange={(e) => setMaxBullets(Number(e.target.value))}
                className="w-16 bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-white"
              />
            </div>
          </div>

          <button
            type="submit"
            className="px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-500 text-slate-950 hover:bg-emerald-400 transition"
          >
            Save Guardrail Configuration
          </button>
        </form>
      </section>

      {/* 4. Technical Skills Inventory */}
      <section className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-white">
              4. Technical Skills Inventory
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Curate the technical skills rendered on your resume and evaluated by ATS algorithms. Re-ordered dynamically during tailoring.
            </p>
          </div>
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={scanBulletsAndPromptSync}
              className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 text-indigo-300 border border-slate-700 hover:bg-slate-700 transition"
            >
              🔍 Scan Bullets for New Skills
            </button>
            <button
              type="button"
              onClick={handleSaveSkills}
              className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500 text-slate-950 hover:bg-emerald-400 transition"
            >
              Save Technical Skills
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {Object.entries(CATEGORY_LABELS).map(([catKey, catLabel]) => {
            const list = skills[catKey] || [];
            return (
              <div
                key={catKey}
                className="bg-slate-950/70 border border-slate-800 rounded-lg p-4 space-y-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-200">
                    {catLabel} ({list.length})
                  </span>
                </div>
                <div className="flex flex-wrap gap-1.5 min-h-[44px]">
                  {list.map((skill) => (
                    <span
                      key={skill}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs bg-slate-800 text-slate-200 border border-slate-700"
                    >
                      {skill}
                      <button
                        type="button"
                        onClick={() => handleRemoveSkill(catKey, skill)}
                        className="text-slate-400 hover:text-rose-300"
                        title="Remove skill"
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                  {list.length === 0 && (
                    <span className="text-xs text-slate-500 italic py-1">
                      No skills added yet
                    </span>
                  )}
                </div>
                <div className="flex gap-2 pt-1">
                  <input
                    type="text"
                    value={newSkillInputs[catKey] || ""}
                    onChange={(e) =>
                      setNewSkillInputs({ ...newSkillInputs, [catKey]: e.target.value })
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleAddSkill(catKey);
                      }
                    }}
                    placeholder={`+ Add to ${catLabel}`}
                    className="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1 text-xs text-white flex-1 focus:outline-none focus:border-indigo-500"
                  />
                  <button
                    type="button"
                    onClick={() => handleAddSkill(catKey)}
                    className="px-2.5 py-1 rounded-lg text-xs bg-slate-800 text-slate-200 hover:bg-slate-700"
                  >
                    Add
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* 5. Visual Experience Bullet Editor (FR-1.2) */}
      <section className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-white">
              5. Verified Source Experience Bullets
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Saving checks for newly introduced tools and prompts to optionally sync them into Technical Skills.
            </p>
          </div>
          <button
            onClick={handleSaveExperience}
            className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-indigo-500 text-white hover:bg-indigo-400 transition"
          >
            Save Bullet Edits
          </button>
        </div>

        <div className="space-y-4">
          {experience.map((role, rIdx) => (
            <div
              key={role.role_id || rIdx}
              className="bg-slate-950/70 border border-slate-800 rounded-lg p-4 space-y-2"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-bold text-white">
                  {role.title} — {role.company}
                </span>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-400">{role.dates}</span>
                  <button
                    type="button"
                    onClick={() => handleAddBullet(rIdx)}
                    className="px-2.5 py-1 rounded text-xs font-medium bg-slate-800 text-slate-200 hover:bg-slate-700 transition"
                  >
                    + Add Bullet
                  </button>
                </div>
              </div>
              <div className="space-y-2.5">
                {role.bullets.map((bullet, bIdx) => (
                  <div key={bIdx} className="flex items-start gap-2">
                    <div className="flex-1 space-y-1">
                      <textarea
                        rows={Math.max(2, Math.ceil((bullet || "").length / 95))}
                        value={bullet}
                        onChange={(e) =>
                          handleBulletChange(rIdx, bIdx, e.target.value)
                        }
                        className="w-full bg-slate-900 border border-slate-800 focus:border-indigo-500 focus:outline-none rounded-lg px-3 py-2 text-xs text-slate-200 leading-relaxed resize-y"
                      />
                      <div className="flex justify-end">
                        <span className="text-[11px] text-slate-500">
                          {(bullet || "").length} chars
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      title="Delete bullet"
                      onClick={() => handleRemoveBullet(rIdx, bIdx)}
                      className="mt-1.5 px-2 py-1 rounded text-xs text-slate-500 hover:text-rose-400 hover:bg-rose-950/50 transition"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

