"use client";

import { useRef, useState, useCallback } from "react";
import type { AgentNodeName } from "@/types/event";

const FLUSH_INTERVAL_MS = 64; // ~15fps, enough for readable streaming without render thrash

interface StreamState {
  activeNode: AgentNodeName | null;
  texts: Record<string, string>;
}

export function useNodeStream() {
  const [state, setState] = useState<StreamState>({ activeNode: null, texts: {} });
  const bufferRef = useRef<Record<string, string>>({});
  const activeRef = useRef<AgentNodeName | null>(null);
  const lastFlushRef = useRef(0);
  const rafRef = useRef<number | null>(null);

  const flush = useCallback(() => {
    rafRef.current = null;
    setState({ activeNode: activeRef.current, texts: { ...bufferRef.current } });
  }, []);

  const scheduleFlush = useCallback(() => {
    if (rafRef.current != null) return;
    const now = performance.now();
    const elapsed = now - lastFlushRef.current;
    if (elapsed >= FLUSH_INTERVAL_MS) {
      lastFlushRef.current = now;
      flush();
    } else {
      rafRef.current = requestAnimationFrame(() => {
        lastFlushRef.current = performance.now();
        flush();
      });
    }
  }, [flush]);

  const pushToken = useCallback(
    (nodeName: AgentNodeName, token: string) => {
      if (!bufferRef.current[nodeName]) bufferRef.current[nodeName] = "";
      bufferRef.current[nodeName] += token;

      if (activeRef.current !== nodeName) {
        activeRef.current = nodeName;
      }

      scheduleFlush();
    },
    [scheduleFlush]
  );

  const setActiveNode = useCallback((nodeName: AgentNodeName) => {
    // Clear previous node only if switching to a different node
    if (activeRef.current !== nodeName) {
      bufferRef.current[nodeName] = "";
      activeRef.current = nodeName;
      flush();
    }
  }, [flush]);

  return { ...state, pushToken, setActiveNode };
}
