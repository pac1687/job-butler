"use client";

import React, { useEffect, useState } from "react";

export function ActiveWorkerBadge() {
  const [workerId, setWorkerId] = useState<string | null>(null);

  useEffect(() => {
    // Check URL parameters first (?worker=... or ?node=...)
    const params = new URLSearchParams(window.location.search);
    const fromUrl = (params.get("worker") || params.get("node") || "").trim();

    if (fromUrl) {
      document.cookie = `worker_node_id=${encodeURIComponent(
        fromUrl
      )}; path=/; max-age=31536000; SameSite=Lax`;
      try {
        localStorage.setItem("worker_node_id", fromUrl);
      } catch {}
      setWorkerId(fromUrl);
      return;
    }

    // Otherwise check cookie
    const match = document.cookie.match(/(?:^|;\s*)worker_node_id=([^;]+)/);
    if (match) {
      const val = decodeURIComponent(match[1]).trim();
      setWorkerId(val);
      try {
        localStorage.setItem("worker_node_id", val);
      } catch {}
      return;
    }

    // Fallback to localStorage
    try {
      const stored = localStorage.getItem("worker_node_id");
      if (stored) {
        setWorkerId(stored.trim());
      }
    } catch {}
  }, []);

  if (!workerId) return null;

  return (
    <span
      title={`Active processing node: tasks triggered from this browser will be claimed by '${workerId}'`}
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-medium bg-emerald-950/80 border border-emerald-700/60 text-emerald-300 select-none"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
      node: {workerId}
    </span>
  );
}

