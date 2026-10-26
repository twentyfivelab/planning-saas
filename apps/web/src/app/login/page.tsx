"use client";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { Button, Callout, Field, Input } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import { ThemeToggle } from "@/components/ui/Theme";
import { api, setCsrf } from "@/lib/api";
import { t } from "@/lib/i18n";

export default function Login() {
  const router = useRouter();
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setBusy(true); setError("");
    const f = new FormData(e.currentTarget);
    try {
      const r = await api<{ csrf_token: string }>("/auth/login", { method: "POST", json: { email: f.get("email"), password: f.get("password") } });
      setCsrf(r.csrf_token); router.replace("/");
    } catch { setError(t("login.error")); setBusy(false); }
  }
  return (
    <main style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: "var(--sp-4)" }}>
      <div className="stack" style={{ width: "min(26rem, 100%)", gap: "var(--sp-4)" }}>
        <form onSubmit={submit} className="glass-raised card rise stack" aria-labelledby="t" style={{ gap: "var(--sp-4)" }}>
          <div className="brandmark"><span className="logo"><Icon name="calendar" size={16} /></span>{t("app.name")}</div>
          <div><h1 id="t" className="title" style={{ fontSize: "var(--text-xl)" }}>{t("login.title")}</h1><p className="muted">Planification automatique sous contraintes.</p></div>
          <Field label={t("login.email")}>{(p) => <Input {...p} name="email" type="email" required autoComplete="username" />}</Field>
          <Field label={t("login.password")}>{(p) => <Input {...p} name="password" type="password" required autoComplete="current-password" />}</Field>
          {error && <Callout kind="bad">{error}</Callout>}
          <Button type="submit" variant="primary" disabled={busy}>{busy ? "Connexion…" : t("login.submit")}</Button>
        </form>
        <div className="row" style={{ justifyContent: "space-between" }}><ThemeToggle /><span className="help">Aide à la décision · non commercialisable en l&apos;état</span></div>
      </div>
    </main>
  );
}
