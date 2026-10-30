"use client";

import React, { useState } from "react";
import type { JobPreferencesRecord } from "@/lib/db";
import { updatePreferencesAction } from "./actions";

interface PreferencesFormClientProps {
  initialPreferences: JobPreferencesRecord;
}

export function PreferencesFormClient({
  initialPreferences,
}: PreferencesFormClientProps) {
  const [positiveTitles, setPositiveTitles] = useState<string[]>(
    initialPreferences.positive_titles
  );
  const [newPositive, setNewPositive] = useState("");

  const [negativeKeywords, setNegativeKeywords] = useState<string[]>(
    initialPreferences.negative_title_keywords
  );
  const [newNegative, setNewNegative] = useState("");

  const [notes, setNotes] = useState<string>(
    initialPreferences.natural_language_notes
  );
  const [minScore, setMinScore] = useState<number>(
    Number(initialPreferences.min_semantic_score || 0.7)
  );
  const [savedNotice, setSavedNotice] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await updatePreferencesAction({
      positive_titles: positiveTitles,
      negative_title_keywords: negativeKeywords,
      natural_language_notes: notes,
      min_semantic_score: minScore,
    });
    setSavedNotice("Search tuning preferences persisted to Neon PostgreSQL.");
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-slate-900/80 border border-slate-800 rounded-xl p-6 space-y-6"
    >
      {savedNotice && (
        <div className="bg-emerald-950/60 border border-emerald-800 rounded-lg p-3 text-xs text-emerald-300">
          {savedNotice}
        </div>
      )}

      {/* Positive Title Anchors */}
      <div>
        <label className="block text-sm font-bold text-white mb-1">
          Positive Title Anchors (Semantic Centroids)
        </label>
        <p className="text-xs text-slate-400 mb-3">
          Embedded via BAAI/bge-small-en-v1.5 in ChromaDB to rank incoming job descriptions.
        </p>
        <div className="flex flex-wrap gap-2 mb-3">
          {positiveTitles.map((title) => (
            <span
              key={title}
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs bg-emerald-950/80 text-emerald-300 border border-emerald-800"
            >
              {title}
              <button
                type="button"
                onClick={() =>
                  setPositiveTitles(positiveTitles.filter((t) => t !== title))
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
            value={newPositive}
            onChange={(e) => setNewPositive(e.target.value)}
            placeholder="Add target title (e.g., Senior Backend Engineer)"
            className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white flex-1"
          />
          <button
            type="button"
            onClick={() => {
              if (newPositive.trim()) {
                setPositiveTitles([...positiveTitles, newPositive.trim()]);
                setNewPositive("");
              }
            }}
            className="px-3 py-1.5 rounded-lg text-xs bg-slate-800 text-white"
          >
            + Add Anchor
          </button>
        </div>
      </div>

      {/* Negative Keyword Blacklist */}
      <div>
        <label className="block text-sm font-bold text-white mb-1">
          Negative Title Keyword Blacklist (Zero-Cost Regex Pruning)
        </label>
        <p className="text-xs text-slate-400 mb-3">
          Listings whose title matches any blacklisted token are pruned before vector or LLM evaluation.
        </p>
        <div className="flex flex-wrap gap-2 mb-3">
          {negativeKeywords.map((kw) => (
            <span
              key={kw}
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs bg-rose-950/80 text-rose-300 border border-rose-800"
            >
              {kw}
              <button
                type="button"
                onClick={() =>
                  setNegativeKeywords(negativeKeywords.filter((k) => k !== kw))
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
            value={newNegative}
            onChange={(e) => setNewNegative(e.target.value)}
            placeholder="Add negative keyword (e.g., Manager, Director, Wordpress)"
            className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white flex-1"
          />
          <button
            type="button"
            onClick={() => {
              if (newNegative.trim()) {
                setNegativeKeywords([...negativeKeywords, newNegative.trim()]);
                setNewNegative("");
              }
            }}
            className="px-3 py-1.5 rounded-lg text-xs bg-slate-800 text-white"
          >
            + Add Blacklist Token
          </button>
        </div>
      </div>

      {/* Minimum Semantic Cutoff Slider */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-sm font-bold text-white">
            Minimum Semantic Similarity Cutoff
          </label>
          <span className="text-sm font-mono font-bold text-emerald-400">
            {minScore.toFixed(2)}
          </span>
        </div>
        <input
          type="range"
          min={0.5}
          max={0.95}
          step={0.01}
          value={minScore}
          onChange={(e) => setMinScore(Number(e.target.value))}
          className="w-full accent-emerald-400"
        />
      </div>

      {/* Natural Language Steering Notes */}
      <div>
        <label className="block text-sm font-bold text-white mb-1">
          Natural Language Evaluation Guidance Notes
        </label>
        <p className="text-xs text-slate-400 mb-2">
          Injected directly into the local LM Studio evaluation prompt.
        </p>
        <textarea
          rows={4}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-xs text-slate-200"
        />
      </div>

      <button
        type="submit"
        className="px-5 py-2 rounded-lg text-xs font-semibold bg-emerald-500 text-slate-950 hover:bg-emerald-400 transition"
      >
        Save Search &amp; Ranking Preferences
      </button>
    </form>
  );
}

