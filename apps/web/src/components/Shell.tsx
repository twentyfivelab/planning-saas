"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { api, setCsrf } from "@/lib/api";
import { t } from "@/lib/i18n";

type Me = { id: string; email: string; name: string; role: string; permissions: string[]; csrf_token: string };
const MeCtx = createContext<Me | null>(null);
export const useMe = () => useContext(MeCtx)!;

const NAV: [string, string][] = [
  ["/", "nav.dashboard"], ["/planning", "nav.planning"], ["/budgets", "nav.budgets"], ["/employees", "nav.employees"],
  ["/rules", "nav.rules"], ["/generate", "nav.generate"], ["/alerts", "nav.alerts"], ["/versions", "nav.versions"],
  ["/import-export", "nav.io"],
];

export function Shell({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [open, setOpen] = useState(false);
  const path = usePathname();
  const router = useRouter();

  useEffect(() => {
    api<Me>("/auth/me").then((m) => { setCsrf(m.csrf_token); setMe(m); }).catch(() => router.replace("/login"));
    try { const th = localStorage.getItem("theme"); if (th) document.documentElement.dataset.theme = th; } catch {}
  }, [router]);

  if (!me) return <main className="p-8 muted" aria-busy="true">Chargement…</main>;
  const toggleTheme = () => {
    const cur = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = cur;
    try { localStorage.setItem("theme", cur); } catch {}
  };
  return (
    <MeCtx.Provider value={me}>
      <div className="mx-auto flex max-w-[1500px] flex-col gap-3 p-3 md:flex-row">
        <header className="glass flex items-center justify-between p-3 md:hidden">
          <strong>{t("app.name")}</strong>
          <button className="btn" aria-expanded={open} aria-controls="nav" onClick={() => setOpen(!open)}>Menu</button>
        </header>
        <nav id="nav" aria-label="Navigation principale" className={`glass p-3 md:sticky md:top-3 md:block md:h-[calc(100vh-1.5rem)] md:w-56 md:shrink-0 ${open ? "block" : "hidden"}`}>
          <p className="mb-3 hidden text-lg font-semibold md:block">{t("app.name")}</p>
          <ul className="flex flex-col gap-1">
            {NAV.map(([href, key]) => (
              <li key={href}>
                <Link href={href} onClick={() => setOpen(false)} aria-current={path === href ? "page" : undefined}
                  className={`block rounded-lg px-3 py-2 text-sm ${path === href ? "btn-primary" : "hover:bg-white/30"}`}>{t(key)}</Link>
              </li>
            ))}
          </ul>
          <div className="mt-4 flex flex-col gap-2 text-sm">
            <span className="muted">{me.name} · {me.role}</span>
            <button className="btn" onClick={toggleTheme}>{t("action.theme")}</button>
            <button className="btn" onClick={async () => { await api("/auth/logout", { method: "POST" }); router.replace("/login"); }}>Déconnexion</button>
          </div>
        </nav>
        <main className="min-w-0 flex-1 fade-in">
          <p role="note" className="glass mb-3 p-3 text-xs muted">{t("legal.banner")}</p>
          {children}
        </main>
      </div>
    </MeCtx.Provider>
  );
}

export function Card({ title, children, actions }: { title?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="glass mb-3 p-4">
      {(title || actions) && <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        {title && <h2 className="text-base font-semibold">{title}</h2>}{actions}</div>}
      {children}
    </section>
  );
}

export function Page({ children }: { children: ReactNode }) { return <>{children}</>; }
