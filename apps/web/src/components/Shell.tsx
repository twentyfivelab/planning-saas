"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, setCsrf } from "@/lib/api";
import { t } from "@/lib/i18n";
import { Icon, type IconName } from "./ui/Icon";
import { Button, Badge, Skeleton } from "./ui/primitives";
import { ThemeToggle } from "./ui/Theme";
import { ToastProvider } from "./ui/Toast";

type Me = { id: string; email: string; name: string; role: string; permissions: string[]; csrf_token: string };
const MeCtx = createContext<Me | null>(null);
export const useMe = () => useContext(MeCtx)!;

const GROUPS: { title: string; items: [string, string, IconName][] }[] = [
  { title: "Planifier", items: [["/", "nav.dashboard", "dashboard"], ["/planning", "nav.planning", "calendar"], ["/generate", "nav.generate", "sparkles"], ["/alerts", "nav.alerts", "bell"], ["/versions", "nav.versions", "history"]] },
  { title: "Données", items: [["/budgets", "nav.budgets", "wallet"], ["/employees", "nav.employees", "users"], ["/rules", "nav.rules", "shield"], ["/import-export", "nav.io", "swap"]] },
];
const ROLE_LABEL: Record<string, string> = { owner: "Propriétaire", admin: "Administrateur", manager: "Manager", planner: "Planificateur", employee: "Collaborateur", auditor: "Auditeur" };

function LegalBanner() {
  const [open, setOpen] = useState(true);
  useEffect(() => {
    // replié par défaut sur petit écran (le résumé reste visible), ouvert sur ordinateur ; le choix de l'utilisateur prime
    try { const v = localStorage.getItem("legal-collapsed"); setOpen(v === null ? window.innerWidth >= 900 : v !== "1"); } catch {}
  }, []);
  const toggle = () => { const n = !open; setOpen(n); try { localStorage.setItem("legal-collapsed", n ? "0" : "1"); } catch {} };
  return (
    <aside className="glass" role="note" aria-label="Avertissements" style={{ padding: "var(--sp-3) var(--sp-4)" }}>
      <div className="spread">
        <div className="row">
          <Icon name="alert" size={16} style={{ color: "var(--warn)" }} />
          <strong>Simulation exploratoire · non commercialisable en l'état</strong>
          <Badge tone="warn">Hypothèses non validées</Badge>
        </div>
        <Button size="sm" variant="ghost" aria-expanded={open} aria-controls="legal-detail" onClick={toggle}>{open ? "Replier" : "Détails"}</Button>
      </div>
      {open && <p id="legal-detail" className="muted" style={{ marginTop: "var(--sp-2)", fontSize: "var(--text-xs)" }}>{t("legal.banner")}</p>}
    </aside>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [open, setOpen] = useState(false);
  const path = usePathname();
  const router = useRouter();

  useEffect(() => {
    api<Me>("/auth/me").then((m) => { setCsrf(m.csrf_token); setMe(m); }).catch(() => router.replace("/login"));
  }, [router]);
  useEffect(() => setOpen(false), [path]);

  if (!me) {
    return <div className="app" aria-busy="true" role="status"><div className="glass card"><Skeleton h="2rem" w="60%" /></div><div className="page"><Skeleton h="3rem" w="40%" /><Skeleton h="10rem" /><span className="sr-only">Chargement</span></div></div>;
  }
  return (
    <MeCtx.Provider value={me}>
      <ToastProvider>
        <a href="#contenu" className="skip-link">Aller au contenu</a>
        <div className="app">
          <div className="glass topbar">
            <span className="brandmark"><span className="logo"><Icon name="calendar" size={16} /></span>{t("app.name")}</span>
            <Button iconOnly icon={open ? "x" : "menu"} label="Menu" aria-expanded={open} aria-controls="nav" onClick={() => setOpen(!open)} />
          </div>
          <nav id="nav" aria-label="Navigation principale" className="glass sidebar" data-open={open}>
            <div className="brandmark sidebar-brand"><span className="logo"><Icon name="calendar" size={16} /></span>{t("app.name")}</div>
            {GROUPS.map((g) => (
              <div key={g.title} className="nav-group">
                <p className="nav-title">{g.title}</p>
                {g.items.map(([href, key, icon]) => (
                  <Link key={href} href={href} className="nav-link" aria-current={path === href ? "page" : undefined}><Icon name={icon} />{t(key)}</Link>
                ))}
              </div>
            ))}
            <div className="stack" style={{ marginTop: "auto" }}>
              <div className="surface-2" style={{ padding: "var(--sp-3)" }}>
                <p style={{ fontWeight: 650 }}>{me.name}</p>
                <p className="muted" style={{ fontSize: "var(--text-xs)" }}>{ROLE_LABEL[me.role] ?? me.role} · {me.email}</p>
              </div>
              <ThemeToggle />
              <Button icon="logout" onClick={async () => { await api("/auth/logout", { method: "POST" }); router.replace("/login"); }}>Déconnexion</Button>
            </div>
          </nav>
          <main id="contenu" className="page" tabIndex={-1}>
            <LegalBanner />
            {children}
          </main>
        </div>
      </ToastProvider>
    </MeCtx.Provider>
  );
}

export function Page({ children }: { children: ReactNode }) { return <>{children}</>; }
