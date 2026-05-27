"use client";

import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Check, Loader2, Plus, X } from "lucide-react";
import type { WorkflowConfig } from "@/types/workflow";

interface Props {
  config: Partial<WorkflowConfig>;
  isComplete: boolean;
  isStarting: boolean;
  newCompetitor: string;
  onNewCompetitorChange: (v: string) => void;
  onAddCompetitor: () => void;
  onRemoveCompetitor: (name: string) => void;
  onConfigChange: (field: string, value: unknown) => void;
  onStart: () => void;
}

export function ConfigPanel({
  config,
  isComplete,
  isStarting,
  newCompetitor,
  onNewCompetitorChange,
  onAddCompetitor,
  onRemoveCompetitor,
  onConfigChange,
  onStart,
}: Props) {
  return (
    <div className="flex flex-col h-full space-y-5">
      <div>
        <h2 className="text-sm font-semibold text-zinc-200 mb-1 flex items-center gap-2">
          实时配置看板
          {!isComplete && <Loader2 className="h-3 w-3 animate-spin text-emerald-400" />}
        </h2>
        <p className="text-xs text-zinc-500">AI 从对话中提取的结构化配置</p>
      </div>

      <Card className="flex-1 overflow-y-auto">
        <CardContent className="space-y-5 py-4">
          <Section label="分析标题">
            <Input
              value={typeof config.target_product === "string" ? config.target_product : ""}
              onChange={(e) => onConfigChange("target_product", e.target.value)}
              placeholder="输入目标产品名称"
              className="h-9 text-sm"
            />
          </Section>

          <Section label="产品品类">
            <div className="flex gap-1.5 flex-wrap">
              {(["SaaS / 协作工具", "移动应用", "硬件产品"] as const).map((cat) => (
                <button
                  key={cat}
                  onClick={() => onConfigChange("product_category", cat)}
                  className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                    config.product_category === cat
                      ? "border-blue-500/50 bg-blue-500/10 text-blue-400"
                      : "border-zinc-700 text-zinc-500 hover:border-zinc-600"
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>
          </Section>

          <Section label="竞品">
            <div className="flex flex-wrap gap-1.5">
              {(config.competitors ?? []).map((c) => (
                <Badge key={c} className="gap-1">
                  {c}
                  <X
                    className="h-3 w-3 cursor-pointer hover:text-rose-400"
                    onClick={() => onRemoveCompetitor(c)}
                  />
                </Badge>
              ))}
            </div>
            <div className="flex gap-1.5 mt-2">
              <Input
                value={newCompetitor}
                onChange={(e) => onNewCompetitorChange(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onAddCompetitor()}
                placeholder="追加竞品"
                className="h-8 text-xs"
              />
              <Button size="sm" variant="ghost" onClick={onAddCompetitor}>
                <Plus size={12} />
              </Button>
            </div>
          </Section>

          <Section label="分析维度">
            <div className="flex flex-wrap gap-1.5">
              {(config.focus_dimensions ?? []).map((d) => (
                <Badge key={d} variant="success">
                  {d}
                </Badge>
              ))}
            </div>
          </Section>

          <Section label="竞品数量">
            <Input
              type="number"
              min={1}
              max={10}
              value={config.competitor_count ?? 5}
              onChange={(e) => onConfigChange("competitor_count", parseInt(e.target.value) || 5)}
              className="h-8 text-sm w-24"
            />
          </Section>
        </CardContent>
      </Card>

      <Button
        onClick={onStart}
        disabled={!isComplete || isStarting}
        variant={isComplete ? "primary" : "default"}
        className={`w-full py-5 text-sm font-medium transition-all duration-300 ${
          isComplete ? "font-semibold" : "opacity-50"
        }`}
      >
        {isStarting ? (
          <span className="flex items-center gap-2"><Spinner size={14} /> 启动 LangGraph 引擎...</span>
        ) : (
          <span className="flex items-center gap-2"><Check size={16} /> 确认配置并启动分析</span>
        )}
      </Button>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] text-zinc-500 uppercase tracking-wider mb-1.5 font-medium">{label}</p>
      {children}
    </div>
  );
}
