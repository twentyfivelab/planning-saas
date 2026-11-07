"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Fragment, createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { API_BASE, api, setCsrf } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { useApi, useMonthState } from "./hooks";
import { STATUS_TONE, periodHref, type PeriodRow } from "@/lib/periods";
import { t } from "@/lib/i18n";
import { Icon, type IconName } from "./ui/Icon";
import { Button, Badge, Skeleton } from "./ui/primitives";
import { ThemeToggle } from "./ui/Theme";
import { ToastProvider } from "./ui/Toast";

type Me = { id: string; email: string; name: string; role: string; permissions: string[]; csrf_token: string; employee_id?: string | null };
const MeCtx = createContext<Me | null>(null);
export const useMe = () => useContext(MeCtx)!;

// [adresse, libellé, icône, permission requise]
const GROUPS: { title: string; items: [string, string, IconName, string][] }[] = [
  { title: "Planifier", items: [["/", "nav.dashboard", "dashboard", "planning.read"], ["/planning", "nav.planning", "calendar", "planning.read"], ["/generate", "nav.generate", "sparkles", "planning.read"], ["/simulations", "nav.simulations", "swap", "planning.read"], ["/alerts", "nav.alerts", "bell", "planning.read"], ["/versions", "nav.versions", "history", "planning.read"]] },
  { title: "Clients et équipes", items: [["/clients", "nav.clients", "briefcase", "referential.read"], ["/catalog", "nav.catalog", "briefcase", "planning.read"], ["/employees", "nav.employees", "users", "employees.read"]] },
  { title: "Suivi", items: [["/brand", "nav.brand", "calendar", "planning.brand-only"], ["/time", "nav.time", "clock", "planning.brand"], ["/budgets", "nav.budgets", "wallet", "planning.read"], ["/finance", "nav.finance", "wallet", "reports.read"]] },
  { title: "Paramètres", items: [["/rules", "nav.rules", "shield", "planning.read"], ["/settings", "nav.settings", "sparkles", "planning.read"], ["/import-export", "nav.io", "swap", "planning.read"]] },
  { title: "Mon espace", items: [["/me", "nav.me", "calendar", "self.read"]] },
];
const ROLE_LABEL: Record<string, string> = { owner: "Propriétaire", admin: "Administrateur", manager: "Manager", planner: "Planificateur", brand_manager: "Responsable de marque", employee: "Collaborateur", auditor: "Auditeur" };
const allowed = (me: Me, href: string, perm: string) => {
  if (href === "/me") return me.role === "employee" || !!me.employee_id; // espace personnel : uniquement un compte relié à une fiche
  return perm === "planning.brand-only" ? me.permissions.includes("planning.brand") && !me.permissions.includes("planning.read") : me.permissions.includes(perm);
};

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

/** Historique permanent des plannings mensuels (liste issue de la base, statut réel). */
function PlanningHistory({ path }: { path: string }) {
  const ps = useApi<PeriodRow[]>("/periods");
  const [month, setMonth] = useMonthState();
  const router = useRouter();
  const rows = ps.data ?? [];
  return (
    <div className="nav-group nav-history" aria-label="Historique des plannings">
      <div className="spread"><p className="nav-title">Historique des plannings</p>
        <Link href="/plannings/new" className="nav-mini" aria-label="Générer un nouveau planning"><Icon name="plus" size={14} /></Link></div>
      {rows.length === 0 && <p className="help" style={{ padding: "0 var(--sp-3)" }}>Aucun planning pour l&apos;instant.</p>}
      <ul className="history-nav">
        {rows.map((p) => {
          const cur = (path === "/planning" || path.startsWith("/plannings")) && month === p.start_date.slice(0, 7);
          return (
            <li key={p.id}>
              <a href={periodHref(p)} className="nav-link nav-period" aria-current={cur ? "page" : undefined}
                onClick={(e) => { e.preventDefault(); setMonth(p.start_date.slice(0, 7)); router.push(periodHref(p)); }}>
                <span>{p.name}</span><Badge tone={STATUS_TONE[p.status]}>{p.status_label}</Badge>
              </a>
            </li>);
        })}
      </ul>
    </div>
  );
}

/** Pastille du nombre de notifications non lues (jamais une notification par modification : regroupées à la publication). */
function UnreadBadge() {
  const q = useApi<{ unread: number }>("/notifications?unread=true&limit=1");
  return q.data?.unread ? <Badge tone="accent" aria-label={`${q.data.unread} notification(s) non lue(s)`}>{q.data.unread}</Badge> : null;
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
  // un collaborateur ou un responsable de marque arrive sur son espace, pas sur le tableau de bord de planification
  useEffect(() => { if (me && path === "/" && !me.permissions.includes("planning.read")) router.replace(me.permissions.includes("planning.brand") ? "/brand" : "/me"); }, [me, path, router]);
  // Synchronisation entre managers : flux temps réel (Server-Sent Events) — chaque modification validée ailleurs est annoncée en
  // moins d'une seconde. Filet de sécurité : empreinte `/revision` interrogée toutes les 6 s seulement si le flux est coupé.
  useEffect(() => {
    if (!me) return;
    let last: string | null = null, dirty = false, live = false, stop = false;
    // jamais de rechargement sous les yeux de l'utilisateur pendant qu'une fenêtre est ouverte : on attend sa fermeture
    const flush = () => { if (dirty && !document.querySelector("dialog[open]")) { dirty = false; invalidate(); } };
    const tick = async () => {
      if (document.hidden || stop) return;
      try {
        const r = await api<{ revision: string }>("/revision");
        if (last !== null && r.revision !== last) dirty = true;
        last = r.revision;
      } catch { /* hors ligne : on réessaie */ }
      flush();
    };
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/events`, { withCredentials: true });
      es.addEventListener("ready", () => { live = true; });
      es.addEventListener("change", () => { dirty = true; flush(); void tick(); });
      es.onerror = () => { live = false; };
    } catch { es = null; }
    void tick();
    const poll = setInterval(() => { if (!live) void tick(); else flush(); }, 6000);
    const closeWatch = setInterval(flush, 500); // applique dès la fermeture d'une fenêtre
    const vis = () => { if (!document.hidden) void tick(); };
    document.addEventListener("visibilitychange", vis);
    return () => { stop = true; es?.close(); clearInterval(poll); clearInterval(closeWatch); document.removeEventListener("visibilitychange", vis); };
  }, [me]);

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
            {GROUPS.map((g, i) => { const items = g.items.filter(([href, , , perm]) => allowed(me, href, perm)); return items.length === 0 ? null : (
              <Fragment key={g.title}>
                <div className="nav-group">
                  <p className="nav-title">{g.title}</p>
                  {items.map(([href, key, icon]) => (
                    <Link key={href} href={href} className="nav-link" aria-current={path === href ? "page" : undefined}><Icon name={icon} />{t(key)}{href === "/me" && <UnreadBadge />}</Link>
                  ))}
                </div>
                {i === 0 && me.permissions.includes("planning.read") && <PlanningHistory path={path} />}
              </Fragment>
            ); })}
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
