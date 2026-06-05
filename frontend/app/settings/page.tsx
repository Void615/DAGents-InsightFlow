"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth-context";
import { AuthGuard } from "@/components/auth/auth-guard";
import { ThemeToggle } from "@/components/shared/theme-toggle";
import { ArrowLeft } from "lucide-react";

export default function SettingsPage() {
  const { user } = useAuth();

  return (
    <AuthGuard>
      <div className="min-h-screen" style={{ backgroundColor: "var(--bg-primary)" }}>
        <header className="sticky top-0 z-10 border-b border-[var(--border)] bg-[var(--bg-primary)]/80 backdrop-blur-xl">
          <div className="mx-auto flex max-w-2xl items-center justify-between px-6 py-3">
            <div className="flex items-center gap-3">
              <Link
                href="/dashboard"
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                <ArrowLeft size={18} />
              </Link>
              <h1 className="text-sm font-bold text-[var(--text-primary)]">设置</h1>
            </div>
            {user && (
              <p className="text-xs text-[var(--text-muted)]">{user.username}</p>
            )}
          </div>
        </header>

        <main className="mx-auto max-w-2xl px-6 py-8 space-y-6">
          <section className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-4">
              外观
            </h2>
            <ThemeToggle />
          </section>
        </main>
      </div>
    </AuthGuard>
  );
}
