"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { Spinner } from "@/components/ui/spinner";
import { formatTime, statusLabel, statusColor } from "@/lib/utils";
import { useDeleteWorkflow } from "@/lib/use-workflow";
import { XCircle } from "lucide-react";
import type { WorkflowListItem } from "@/types/api";

interface Props {
  workflow: WorkflowListItem;
}

export function WorkflowCard({ workflow }: Props) {
  const router = useRouter();
  const deleteMutation = useDeleteWorkflow();
  const [showConfirm, setShowConfirm] = useState(false);

  const handleDelete = async () => {
    await deleteMutation.mutateAsync(workflow.id);
    setShowConfirm(false);
  };

  return (
    <>
      <Card
        className="cursor-pointer transition-all hover:border-zinc-600 hover:bg-zinc-900/80 relative group"
        onClick={() => router.push(`/workflows/${workflow.id}`)}
      >
        <button
          onClick={(e) => {
            e.stopPropagation();
            setShowConfirm(true);
          }}
          className="absolute top-1.5 right-1.5 p-1 rounded-md text-zinc-500 hover:text-zinc-300 hover:bg-zinc-700/50 opacity-0 group-hover:opacity-100 transition-all"
          title="删除"
        >
          <XCircle size={13} />
        </button>
        <CardHeader>
          <div className="flex items-center justify-between pr-6">
            <CardTitle className="truncate">{workflow.title}</CardTitle>
            <Badge className={statusColor(workflow.status)}>{statusLabel(workflow.status)}</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between text-xs text-zinc-500">
            <span>
              {workflow.status === "running"
                ? `Phase: ${workflow.current_phase}`
                : `Revision ${workflow.revision_count}`}
            </span>
            <span>{formatTime(workflow.created_at)}</span>
          </div>
        </CardContent>
      </Card>

      <Modal open={showConfirm} onClose={() => setShowConfirm(false)} title="确认删除">
        <div className="space-y-4">
          <p className="text-sm text-zinc-400">
            确定要删除 <span className="text-zinc-200 font-medium">「{workflow.title}」</span> 吗？此操作不可撤销。
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setShowConfirm(false)}>取消</Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? <Spinner size={14} /> : <XCircle size={14} />}
              删除
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
