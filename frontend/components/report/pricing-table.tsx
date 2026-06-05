import { motion } from "framer-motion";
import { DollarSign } from "lucide-react";
import type { PricingComparison } from "@/types/artifact";

interface Props {
  data: PricingComparison;
}

export function PricingTable({ data }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-5"
    >
      <div className="flex items-center gap-2 mb-4">
        <div className="w-8 h-8 rounded-lg bg-amber-500/10 flex items-center justify-center">
          <DollarSign size={16} className="text-amber-400" />
        </div>
        <div>
          <p className="text-sm font-semibold text-[var(--text-primary)]">定价对比</p>
          <p className="text-[11px] text-[var(--text-muted)]">各产品定价层级与亮点</p>
        </div>
      </div>

      {data.summary && (
        <p className="text-xs text-[var(--text-secondary)] mb-4 leading-relaxed">{data.summary}</p>
      )}

      <div className="grid gap-3">
        {(data.plans ?? []).map((plan, i) => (
          <div key={i} className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <p className="text-sm font-semibold text-[var(--text-primary)] mb-2">{plan.product}</p>
            <div className="space-y-2">
              {(plan.tiers ?? []).map((tier, j) => (
                <div key={j} className="flex items-start gap-3 text-xs">
                  <div className="shrink-0 min-w-[72px] text-right">
                    <p className="font-medium text-[var(--text-primary)]">{tier.name}</p>
                    {tier.price > 0 && (
                      <p className="text-emerald-400 font-mono">¥{tier.price}</p>
                    )}
                  </div>
                  <div className="flex-1 text-[var(--text-secondary)] leading-relaxed">
                    {(tier.highlights ?? []).join(" · ")}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </motion.div>
  );
}
