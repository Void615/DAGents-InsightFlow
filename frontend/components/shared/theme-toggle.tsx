"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Sun, Moon } from "lucide-react";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  if (!mounted) return null;

  const isDark = theme === "dark";

  return (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm font-medium text-[var(--text-primary)]">主题模式</p>
        <p className="text-xs text-[var(--text-muted)] mt-0.5">
          {isDark ? "当前为深色模式" : "当前为浅色模式"}
        </p>
      </div>
      <button
        onClick={() => setTheme(isDark ? "light" : "dark")}
        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
          isDark ? "bg-emerald-500" : "bg-zinc-300"
        }`}
      >
        <span
          className={`inline-flex h-4 w-4 items-center justify-center rounded-full bg-white shadow-sm transition-transform ${
            isDark ? "translate-x-6" : "translate-x-1"
          }`}
        >
          {isDark ? <Moon size={10} className="text-zinc-700" /> : <Sun size={10} className="text-amber-500" />}
        </span>
      </button>
    </div>
  );
}
