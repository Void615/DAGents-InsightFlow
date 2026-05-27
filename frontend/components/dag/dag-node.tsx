"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { CheckCircle2, Loader2, AlertCircle, RefreshCw } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/utils";
import type { NodeStatus } from "./dag-canvas";

interface DagNodeData {
  label: string;
  status: NodeStatus;
  message?: string;
  duration_ms?: number;
  onRetry?: () => void;
}

const STATUS_STYLES: Record<NodeStatus, { bg: string; border: string; glow: string }> = {
  idle: {
    bg: "bg-zinc-900",
    border: "border-zinc-700",
    glow: "",
  },
  active: {
    bg: "bg-blue-950/40",
    border: "border-blue-500/50",
    glow: "shadow-[0_0_20px_rgba(59,130,246,0.3)]",
  },
  completed: {
    bg: "bg-emerald-950/30",
    border: "border-emerald-500/50",
    glow: "shadow-[0_0_12px_rgba(52,211,153,0.2)]",
  },
  failed: {
    bg: "bg-rose-950/30",
    border: "border-rose-500/50",
    glow: "shadow-[0_0_12px_rgba(244,63,94,0.2)]",
  },
  rerouted: {
    bg: "bg-amber-950/30",
    border: "border-amber-500/50",
    glow: "shadow-[0_0_16px_rgba(245,158,11,0.3)]",
  },
};

function DagNodeComponent({ data }: NodeProps<DagNodeData>) {
  const { label, status, message, duration_ms, onRetry } = data;
  const style = STATUS_STYLES[status];

  return (
    <div
      className={cn(
        "min-w-[200px] rounded-xl border-2 px-4 py-3 transition-all duration-500",
        style.bg,
        style.border,
        style.glow,
        status === "active" && "animate-pulse"
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-zinc-600" />
      <div className="flex items-start gap-3">
        <div className="mt-0.5">
          {status === "active" && <Loader2 className="h-5 w-5 animate-spin text-blue-400" />}
          {status === "completed" && <CheckCircle2 className="h-5 w-5 text-emerald-400" />}
          {status === "failed" && <AlertCircle className="h-5 w-5 text-rose-400" />}
          {status === "rerouted" && <RefreshCw className="h-5 w-5 animate-spin text-amber-400" />}
          {status === "idle" && <div className="h-5 w-5 rounded-full border-2 border-zinc-600" />}
        </div>
        <div className="flex-1 min-w-0">
          <p
            className={cn(
              "text-sm font-medium whitespace-pre-line",
              status === "active" && "text-blue-300",
              status === "completed" && "text-emerald-300",
              status === "failed" && "text-rose-300",
              status === "rerouted" && "text-amber-300",
              status === "idle" && "text-zinc-500"
            )}
          >
            {label}
          </p>
          {message && (
            <p className="text-xs text-zinc-500 mt-1 font-mono truncate max-w-[180px]">{message}</p>
          )}
          {duration_ms != null && status === "completed" && (
            <p className="text-xs text-emerald-500 mt-0.5 font-mono">{formatDuration(duration_ms)}</p>
          )}
        </div>
        {status === "failed" && onRetry && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onRetry();
            }}
            className="text-xs px-2 py-1 rounded bg-rose-600/20 text-rose-300 hover:bg-rose-600/40 border border-rose-500/30"
          >
            重试
          </button>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-zinc-600" />
    </div>
  );
}

export const DagNode = memo(DagNodeComponent);
