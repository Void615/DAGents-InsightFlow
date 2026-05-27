"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { useWorkflows } from "@/lib/use-workflow";
import { AuthGuard } from "@/components/auth/auth-guard";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Badge } from "@/components/ui/badge";
import { WorkflowCard } from "@/components/dashboard/workflow-card";
import { CreateWorkflowDialog } from "@/components/dashboard/create-workflow-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { Plus, LogOut } from "lucide-react";
import type { WorkflowStatus } from "@/types/workflow";

const STATUS_FILTERS: Array<{ label: string; value: WorkflowStatus | "all" }> = [
  { label: "全部", value: "all" },
  { label: "运行中", value: "running" },
  { label: "配置中", value: "configuring" },
  { label: "已完成", value: "completed" },
  { label: "失败", value: "failed" },
];

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const { data: workflows, isLoading } = useWorkflows();
  const [statusFilter, setStatusFilter] = useState<WorkflowStatus | "all">("all");
  const [showCreate, setShowCreate] = useState(false);

  const filtered = (workflows ?? []).filter(
    (w) => statusFilter === "all" || w.status === statusFilter
  );

  return (
    <AuthGuard>
      <div className="min-h-screen bg-zinc-950">
        <header className="border-b border-zinc-800/80 bg-zinc-950/50 backdrop-blur-md sticky top-0 z-10">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
            <div>
              <h1 className="text-lg font-bold text-zinc-100">DAGents InsightFlow</h1>
              {user && <p className="text-xs text-zinc-500">{user.username}</p>}
            </div>
            <div className="flex items-center gap-3">
              <Button variant="primary" size="sm" onClick={() => setShowCreate(true)}>
                <Plus size={14} />
                新建分析
              </Button>
              <Button variant="ghost" size="sm" onClick={logout}>
                <LogOut size={14} />
              </Button>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-6xl px-6 py-8">
          <div className="mb-6 flex items-center gap-2 flex-wrap">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setStatusFilter(f.value)}
                className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${
                  statusFilter === f.value
                    ? "bg-zinc-800 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          {isLoading ? (
            <div className="flex justify-center py-20">
              <Spinner size={24} />
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              title={statusFilter === "all" ? "还没有分析项目" : "没有匹配的工作流"}
              description="点击「新建分析」创建第一个竞品分析任务"
              action={
                <Button variant="primary" onClick={() => setShowCreate(true)}>
                  <Plus size={14} /> 新建分析
                </Button>
              }
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((w) => (
                <WorkflowCard key={w.id} workflow={w} />
              ))}
            </div>
          )}
        </main>

        <CreateWorkflowDialog open={showCreate} onClose={() => setShowCreate(false)} />
      </div>
    </AuthGuard>
  );
}
