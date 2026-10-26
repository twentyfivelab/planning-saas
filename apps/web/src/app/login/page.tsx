"use client";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { api, setCsrf } from "@/lib/api";
import { t } from "@/lib/i18n";

export default function Login() {
  const router = useRouter();
  const [error, setError] = useState("");
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      const r = await api<{ csrf_token: string }>("/auth/login", { method: "POST", json: { email: f.get("email"), password: f.get("password") } });
      setCsrf(r.csrf_token); router.replace("/");
    } catch { setError(t("login.error")); }
  }
  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center p-4">
      <form onSubmit={submit} className="glass w-full space-y-3 p-6 fade-in" aria-labelledby="t">
        <h1 id="t" className="text-xl font-semibold">{t("login.title")}</h1>
        <label className="block text-sm">{t("login.email")}<input name="email" type="email" required autoComplete="username" className="input mt-1" /></label>
        <label className="block text-sm">{t("login.password")}<input name="password" type="password" required autoComplete="current-password" className="input mt-1" /></label>
        {error && <p role="alert" className="tag-bad text-sm">{error}</p>}
        <button className="btn btn-primary w-full justify-center">{t("login.submit")}</button>
      </form>
    </main>
  );
}
