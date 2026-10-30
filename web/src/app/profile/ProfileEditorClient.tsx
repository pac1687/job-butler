"use client";

import React, { useState } from "react";
import type { MasterProfileRecord, TailoringRulesRecord } from "@/lib/db";
import {
  saveMasterProfileDirectAction,
  updateTailoringRulesAction,
  uploadAndEnqueueMasterResumeAction,
} from "./actions";

interface ProfileEditorClientProps {
  initialProfile: MasterProfileRecord;
  initialRules: TailoringRulesRecord;
}

export function ProfileEditorClient({
  initialProfile,
  initialRules,
}: ProfileEditorClientProps) {
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
  const [statusBanner, setStatusBanner] = useState<string | null>(null);

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

  async function handleSaveExperience() {
    await saveMasterProfileDirectAction({
      basics: initialProfile.basics,
      skills: initialProfile.skills,
      experience,
      education: initialProfile.education,
    });
    setStatusBanner("Updated verified master resume bullets.");
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

  return (
    <div className="space-y-8">
      {statusBanner && (
        <div className="bg-emerald-950/60 border border-emerald-800 rounded-xl p-3 text-xs text-emerald-300">
          {statusBanner}
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
            await uploadAndEnqueueMasterResumeAction(formData);
            setStatusBanner(
              "Uploaded resume and enqueued PARSE_MASTER_RESUME task for local worker."
            );
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

      {/* 2. Tailoring Guardrails & Constraint Configuration (FR-1.3) */}
      <section className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 space-y-5">
        <h2 className="text-lg font-bold text-white">
          2. Deterministic Tailoring Guardrails
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

      {/* 3. Visual Experience Bullet Editor (FR-1.2) */}
      <section className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold text-white">
            3. Verified Source Experience Bullets
          </h2>
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
                <span className="text-xs text-slate-400">{role.dates}</span>
              </div>
              <div className="space-y-2">
                {role.bullets.map((bullet, bIdx) => (
                  <input
                    key={bIdx}
                    type="text"
                    maxLength={170}
                    value={bullet}
                    onChange={(e) =>
                      handleBulletChange(rIdx, bIdx, e.target.value)
                    }
                    className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-1.5 text-xs text-slate-200"
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

