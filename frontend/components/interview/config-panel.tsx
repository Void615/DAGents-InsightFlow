"use client";

import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { motion, AnimatePresence } from "framer-motion";
import { Check, Plus, X, ChevronDown, Pencil } from "lucide-react";
import { useState } from "react";
import type { WorkflowConfig } from "@/types/workflow";

interface Props {
  config: Partial<WorkflowConfig>;
  isComplete: boolean;
  isStarting: boolean;
  newCompetitor: string;
  /** 本地校验：target_product + product_category 是否都已填写 */
  canStart: boolean;
  /** 后端 /start 失败信息（如 ConfigIncompleteError 等），非 null 时高亮显示 */
  startError: string | null;
  onNewCompetitorChange: (v: string) => void;
  onAddCompetitor: () => void;
  onRemoveCompetitor: (name: string) => void;
  onConfigChange: (field: string, value: unknown) => void;
  onStart: () => void;
  /** 解锁访谈对话（isComplete 翻回 false），用于配置不满意时继续修订 */
  onResumeEditing: () => void;
}

export function ConfigPanel({
  config,
  isComplete,
  isStarting,
  newCompetitor,
  canStart,
  startError,
  onNewCompetitorChange,
  onAddCompetitor,
  onRemoveCompetitor,
  onConfigChange,
  onStart,
  onResumeEditing,
}: Props) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const toggle = (k: string) => setCollapsed((p) => ({ ...p, [k]: !p[k] }));

  return (
    <div className="flex flex-col h-full space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
            实时配置看板
            {!isComplete && (
              <span className="flex gap-1">
                {[0, 1, 2].map((i) => (
                  <motion.span
                    key={i}
                    className="w-1 h-1 rounded-full bg-emerald-400"
                    animate={{ opacity: [0.3, 1, 0.3] }}
                    transition={{ duration: 1, delay: i * 0.2, repeat: Infinity }}
                  />
                ))}
              </span>
            )}
          </h2>
          <p className="text-xs text-[var(--text-muted)]">AI 从对话中提取的结构化配置</p>
        </div>
        {isComplete && (
          <motion.span
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="shrink-0 w-6 h-6 rounded-full bg-emerald-500/20 border border-emerald-500/30 flex items-center justify-center"
          >
            <Check size={12} className="text-emerald-400" />
          </motion.span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto space-y-3 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)]/60 backdrop-blur-xl p-4">
        <FieldSection label="分析标题" collapsed={collapsed.title} onToggle={() => toggle("title")}>
          <Input
            value={typeof config.target_product === "string" ? config.target_product : ""}
            onChange={(e) => onConfigChange("target_product", e.target.value)}
            placeholder="等待 AI 提取..."
            className="h-9 text-sm bg-[var(--bg-elevated)] border-[var(--border)]"
          />
        </FieldSection>

        <FieldSection label="产品品类" collapsed={collapsed.category} onToggle={() => toggle("category")}>
          <div className="flex gap-1.5 flex-wrap">
            {(["SaaS / 协作工具", "移动应用", "硬件产品"] as const).map((cat) => (
              <button
                key={cat}
                onClick={() => onConfigChange("product_category", cat)}
                className={`px-3 py-1.5 rounded-lg text-xs border transition-all ${
                  config.product_category === cat
                    ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-400"
                    : "border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--text-secondary)]"
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
        </FieldSection>

        <FieldSection label="竞品" collapsed={collapsed.competitors} onToggle={() => toggle("competitors")}>
          <div className="flex flex-wrap gap-1.5">
            {(config.competitors ?? []).map((c) => (
              <Badge key={c} className="gap-1 bg-[var(--bg-elevated)] text-[var(--text-secondary)] border-[var(--border)]">
                {c}
                <X className="h-3 w-3 cursor-pointer hover:text-rose-400" onClick={() => onRemoveCompetitor(c)} />
              </Badge>
            ))}
            {(!config.competitors || config.competitors.length === 0) && (
              <span className="text-xs text-[var(--text-muted)] italic">等待 AI 提取...</span>
            )}
          </div>
          <div className="flex gap-1.5 mt-2">
            <Input value={newCompetitor} onChange={(e) => onNewCompetitorChange(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onAddCompetitor()}
              placeholder="追加竞品" className="h-8 text-xs bg-[var(--bg-elevated)] border-[var(--border)]"
            />
            <Button size="sm" variant="ghost" onClick={onAddCompetitor}><Plus size={12} /></Button>
          </div>
        </FieldSection>

        <FieldSection label="分析维度" collapsed={collapsed.dimensions} onToggle={() => toggle("dimensions")}>
          <div className="flex flex-wrap gap-1.5">
            {(config.focus_dimensions ?? []).map((d) => (
              <Badge key={d} variant="success">{d}</Badge>
            ))}
            {(!config.focus_dimensions || config.focus_dimensions.length === 0) && (
              <span className="text-xs text-[var(--text-muted)] italic">等待 AI 提取...</span>
            )}
          </div>
        </FieldSection>
      </div>

      {/* /start 错误内联回显 */}
      {startError && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {startError}
        </div>
      )}

      <AnimatePresence>
        {/* 显示 Start 按钮的条件：LLM 已发出完成哨兵，或本地校验已通过（允许无 sentinel 也能启动） */}
        {(isComplete || canStart) && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            className="space-y-2"
          >
            <Button
              onClick={onStart}
              disabled={isStarting || !canStart}
              className="w-full py-5 text-sm font-semibold rounded-2xl bg-emerald-500 hover:bg-emerald-600 text-white shadow-[0_0_24px_var(--accent-glow)] transition-all duration-300 hover:shadow-[0_0_36px_var(--accent-glow)] disabled:bg-zinc-700 disabled:shadow-none disabled:cursor-not-allowed"
            >
              {isStarting ? (
                <span className="flex items-center gap-2"><Spinner size={14} /> 启动 LangGraph 引擎...</span>
              ) : (
                <span className="flex items-center gap-2"><Check size={16} /> 确认配置并启动分析</span>
              )}
            </Button>
            {!canStart && (
              <p className="text-[11px] text-amber-400/80 text-center">
                请先补全产品名称和品类
              </p>
            )}
            {isComplete && (
              <Button
                variant="ghost"
                onClick={onResumeEditing}
                className="w-full h-8 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              >
                <Pencil size={12} className="mr-1" /> 继续编辑访谈
              </Button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function FieldSection({
  label,
  children,
  collapsed,
  onToggle,
}: {
  label: string;
  children: React.ReactNode;
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  return (
    <div>
      <button onClick={onToggle} className="flex items-center gap-1 mb-1.5 w-full text-left group">
        <ChevronDown
          size={10}
          className={`text-[var(--text-muted)] transition-transform ${collapsed ? "-rotate-90" : ""}`}
        />
        <p className="text-[11px] text-[var(--text-muted)] uppercase tracking-wider font-medium">{label}</p>
      </button>
      {!collapsed && children}
    </div>
  );
}
