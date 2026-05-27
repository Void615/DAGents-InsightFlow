"use client";

import Link from "next/link";
import { LoginForm } from "@/components/auth/login-form";

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950 px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-zinc-100">DAGents InsightFlow</h1>
          <p className="mt-1 text-sm text-zinc-500">登录到 AI 工作流观测台</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6">
          <LoginForm />
        </div>
        <p className="text-center text-sm text-zinc-500">
          还没有账号？{" "}
          <Link href="/auth/register" className="text-emerald-400 hover:underline">
            注册
          </Link>
        </p>
      </div>
    </div>
  );
}
