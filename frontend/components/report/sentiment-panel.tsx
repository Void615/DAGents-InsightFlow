import { motion } from "framer-motion";
import { ThumbsUp, ThumbsDown, MessageCircle } from "lucide-react";
import type { UserSentimentAnalysis } from "@/types/artifact";

interface Props {
  data: UserSentimentAnalysis;
}

export function SentimentPanel({ data }: Props) {
  const products = Object.keys(data.per_product ?? {});

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-blue-500/20 bg-blue-500/5 p-5"
    >
      <div className="flex items-center gap-2 mb-4">
        <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center">
          <MessageCircle size={16} className="text-blue-400" />
        </div>
        <div>
          <p className="text-sm font-semibold text-[var(--text-primary)]">用户情感分析</p>
          <p className="text-[11px] text-[var(--text-muted)]">各产品用户评价情感分布</p>
        </div>
      </div>

      {/* Per-product sentiment bars */}
      {products.length > 0 && (
        <div className="space-y-3 mb-5">
          {products.map((product) => {
            const s = data.per_product[product];
            const total = s.positive + s.negative + s.neutral;
            const pPct = total > 0 ? Math.round((s.positive / total) * 100) : 0;
            const nPct = total > 0 ? Math.round((s.negative / total) * 100) : 0;
            const neuPct = 100 - pPct - nPct;

            return (
              <div key={product}>
                <div className="flex items-center justify-between mb-1">
                  <p className="text-xs font-medium text-[var(--text-primary)]">{product}</p>
                  <span className="text-[10px] text-[var(--text-muted)]">{total} 条评价</span>
                </div>
                <div className="flex h-2 rounded-full overflow-hidden">
                  <div
                    className="bg-emerald-500 transition-all"
                    style={{ width: `${pPct}%` }}
                    title={`好评 ${s.positive}`}
                  />
                  <div
                    className="bg-zinc-400 transition-all"
                    style={{ width: `${neuPct}%` }}
                    title={`中性 ${s.neutral}`}
                  />
                  <div
                    className="bg-rose-500 transition-all"
                    style={{ width: `${nPct}%` }}
                    title={`差评 ${s.negative}`}
                  />
                </div>
                <div className="flex gap-3 mt-0.5 text-[10px] text-[var(--text-muted)]">
                  <span className="flex items-center gap-0.5"><ThumbsUp size={10} className="text-emerald-400" /> {s.positive}</span>
                  <span className="flex items-center gap-0.5"><ThumbsDown size={10} className="text-rose-400" /> {s.negative}</span>
                  <span>中性 {s.neutral}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Common praises & complaints */}
      <div className="grid grid-cols-2 gap-4">
        {data.common_praises && data.common_praises.length > 0 && (
          <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
            <p className="text-xs font-medium text-emerald-400 mb-2 flex items-center gap-1">
              <ThumbsUp size={12} /> 普遍好评
            </p>
            <ul className="space-y-1">
              {data.common_praises.map((item, i) => (
                <li key={i} className="text-xs text-[var(--text-secondary)] leading-relaxed">{item}</li>
              ))}
            </ul>
          </div>
        )}
        {data.common_complaints && data.common_complaints.length > 0 && (
          <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-3">
            <p className="text-xs font-medium text-rose-400 mb-2 flex items-center gap-1">
              <ThumbsDown size={12} /> 普遍投诉
            </p>
            <ul className="space-y-1">
              {data.common_complaints.map((item, i) => (
                <li key={i} className="text-xs text-[var(--text-secondary)] leading-relaxed">{item}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </motion.div>
  );
}
