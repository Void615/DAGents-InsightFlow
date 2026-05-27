"use client";

import Link from "next/link";
import { RegisterForm } from "@/components/auth/register-form";

export default function RegisterPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950 px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-zinc-100">创建账号</h1>
          <p className="mt-1 text-sm text-zinc-500">注册 DAGents InsightFlow</p>
        </div>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6">
          <RegisterForm />
        </div>
        <p className="text-center text-sm text-zinc-500">
          已有账号？{" "}
          <Link href="/auth/login" className="text-emerald-400 hover:underline">
            登录
          </Link>
        </p>
      </div>
    </div>
  );
}
