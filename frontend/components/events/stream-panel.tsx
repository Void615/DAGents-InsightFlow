"use client";

import { useEffect, useRef } from "react";
import type { AgentNodeName } from "@/types/event";

const NODE_LABELS: Record<string, string> = {
  information_collection: "CollectionAgent",
  analysis: "AnalysisAgent",
  report_writing: "ReportAgent",
  review: "ReviewAgent",
};

interface Props {
  activeNode: AgentNodeName | null;
  texts: Record<string, string>;
}

export function StreamPanel({ activeNode, texts }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [texts]);

  const text = activeNode ? texts[activeNode] || "" : "";

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {activeNode && (
        <div className="px-3 py-2 border-b border-[var(--border)] bg-[var(--bg-elevated)] flex items-center gap-2">
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-400" />
          </span>
          <span className="text-xs font-medium text-[var(--text-primary)]">
            {NODE_LABELS[activeNode] || activeNode}
          </span>
          <span className="text-[10px] text-[var(--text-muted)]">streaming...</span>
        </div>
      )}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
        {text ? (
          <span className="text-[var(--text-secondary)]">{text}</span>
        ) : (
          <span className="text-[var(--text-muted)] italic">
            {activeNode
              ? "Waiting for output..."
              : "DAG execution started. LLM output will appear here as nodes execute."}
          </span>
        )}
        {activeNode && text && (
          <span className="inline-block w-2 h-3.5 bg-emerald-400/80 ml-0.5 animate-pulse align-middle" />
        )}
      </div>
    </div>
  );
}
