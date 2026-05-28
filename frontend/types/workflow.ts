export type WorkflowStatus =
  | "created"
  | "configuring"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export type ProductCategory = "SaaS / 协作工具" | "移动应用" | "硬件产品";

export interface WorkflowConfig {
  target_product: string;
  product_category: ProductCategory;
  focus_dimensions: string[];
  competitor_count: number;
  competitors: string[];
  language: string;
  extra_requirements: string;
}

export interface WorkflowDetail {
  id: string;
  title: string;
  status: WorkflowStatus;
  current_phase: string;
  config: Partial<WorkflowConfig>;
  revision_count: number;
  max_revisions?: number;
  total_tokens?: number;
  error_message?: string | null;
  pause_state?: {
    paused_by_node: string;
    pause_reason: string;
    pause_options: Array<{ value: string; label: string; target_node?: string }>;
    pause_context?: Record<string, unknown>;
    /** 暂停时 DAG state 快照（供 resume 复用 cached_review_result） */
    dag_state?: Record<string, unknown>;
    paused_at: string;
  } | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}
