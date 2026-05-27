"use client";

import * as React from "react";
import { cn } from "@/lib/cn";

interface TabsContextValue {
  active: string;
  setActive: (v: string) => void;
}

const TabsContext = React.createContext<TabsContextValue | null>(null);

interface TabsProps {
  defaultValue: string;
  value?: string;
  onValueChange?: (v: string) => void;
  children: React.ReactNode;
  className?: string;
}

export function Tabs({ defaultValue, value, onValueChange, children, className }: TabsProps) {
  const [internalValue, setInternalValue] = React.useState(defaultValue);
  const active = value ?? internalValue;
  const setActive = (v: string) => {
    setInternalValue(v);
    onValueChange?.(v);
  };
  return (
    <TabsContext.Provider value={{ active, setActive }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

function useTabsContext() {
  const ctx = React.useContext(TabsContext);
  if (!ctx) throw new Error("Tabs components must be used within Tabs");
  return ctx;
}

export function TabsList({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 rounded-lg bg-zinc-900 p-1 border border-zinc-800",
        className
      )}
    >
      {children}
    </div>
  );
}

export function TabsTrigger({
  value,
  children,
  className,
}: {
  value: string;
  children: React.ReactNode;
  className?: string;
}) {
  const { active, setActive } = useTabsContext();
  return (
    <button
      onClick={() => setActive(value)}
      className={cn(
        "px-4 py-2 text-sm font-medium rounded-md transition-colors",
        active === value
          ? "bg-zinc-800 text-zinc-100"
          : "text-zinc-400 hover:text-zinc-200",
        className
      )}
    >
      {children}
    </button>
  );
}

export function TabsContent({
  value,
  children,
  className,
}: {
  value: string;
  children: React.ReactNode;
  className?: string;
}) {
  const { active } = useTabsContext();
  if (active !== value) return null;
  return <div className={cn("pt-4", className)}>{children}</div>;
}
