"use client";
import { useEffect, useMemo, useState } from "react";
import { useApi } from "@/components/hooks";
import { Badge, Button, Callout, EmptyState, Field, Input, Select, SkeletonCard } from "@/components/ui/primitives";
import { api } from "@/lib/api";

export type HistoryItem = { id: string; at: string; at_label: string; kind: string; kind_label: string; title: string; lines: string[]; by: string;
  period_id: string | null; period: string | null; shift_days: string[]; shift_day_label: string | null; employees: { id: string; name: string }[];
  brands: string[]; sites: string[]; forced: boolean; reason: string | null; details: { title: string; lines: string[]; shift_day_label: string | null }[] };
type Resp = { timezone: string; items: HistoryItem[]; next: string | null; kinds: { key: string; label: string }[];
  facets: { users: { id: string; name: string }[]; employees: { id: string; name: string }[]; sites: { code: string; name: string }[]; brands: string[] } };
type Filters = { from: string; to: string; employee_id: string; site: string; brand: string; user_id: string; kind: string };
const EMPTY: Filters = { from: "", to: "", employee_id: "", site: "", brand: "", user_id: "", kind: "" };
const TONE: Record<string, "ok" | "bad" | "info" | "warn" | "neutral" | "accent"> = { add: "ok", remove: "bad", replace: "info", swap: "info", bulk: "info", hours: "warn",
  lock: "neutral", generation: "accent", restore: "accent", publish: "ok", version: "neutral" };

/** Historique des modifications (journal d'audit, présenté en langage simple). Date de modification en tête, date du shift à part ;
 *  heures dans le fuseau de l'entreprise (fourni par le serveur). Filtres simples ; « Afficher plus » pour remonter dans le temps. */
export function HistoryFeed({ periodId, employeeId, filters = true, limit = 30 }: { periodId?: string; employeeId?: string; filters?: boolean; limit?: number }) {
  const [f, setF] = useState<Filters>({ ...EMPTY, employee_id: employeeId ?? "" });
  useEffect(() => { setF((x) => ({ ...x, employee_id: employeeId ?? "" })); }, [employeeId]);
  const qs = useMemo(() => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (periodId) p.set("period_id", periodId);
    for (const [k, v] of Object.entries(f)) if (v) p.set(k, v);
    return p.toString();
  }, [f, periodId, limit]);
  const q = useApi<Resp>(`/history?${qs}`);
  const [more, setMore] = useState<HistoryItem[]>([]); const [next, setNext] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  useEffect(() => { setMore([]); setNext(q.data?.next ?? null); }, [q.data]);
  const set = (k: keyof Filters, v: string) => setF((x) => ({ ...x, [k]: v }));
  async function loadMore() {
    if (!next) return;
    setBusy(true);
    try { const r = await api<Resp>(`/history?${qs}&before=${encodeURIComponent(next)}`); setMore((m) => [...m, ...r.items]); setNext(r.next); }
    finally { setBusy(false); }
  }
  const items = [...(q.data?.items ?? []), ...more];
  const fc = q.data?.facets;
  const active = Object.entries(f).some(([k, v]) => v && !(k === "employee_id" && v === employeeId));
  return (
    <div className="stack" data-testid="history-feed">
      {filters && (
        <div className="toolbar" role="search" aria-label="Filtres de l'historique">
          <Field label="Du">{(p) => <Input {...p} type="date" value={f.from} onChange={(e) => set("from", e.target.value)} />}</Field>
          <Field label="Au">{(p) => <Input {...p} type="date" value={f.to} onChange={(e) => set("to", e.target.value)} />}</Field>
          {!employeeId && <Field label="Collaborateur">{(p) => <Select {...p} value={f.employee_id} onChange={(e) => set("employee_id", e.target.value)}><option value="">Tous</option>{fc?.employees.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</Select>}</Field>}
          <Field label="Site">{(p) => <Select {...p} value={f.site} onChange={(e) => set("site", e.target.value)}><option value="">Tous</option>{fc?.sites.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}</Select>}</Field>
          <Field label="Marque">{(p) => <Select {...p} value={f.brand} onChange={(e) => set("brand", e.target.value)}><option value="">Toutes</option>{fc?.brands.map((b) => <option key={b}>{b}</option>)}</Select>}</Field>
          <Field label="Utilisateur">{(p) => <Select {...p} value={f.user_id} onChange={(e) => set("user_id", e.target.value)}><option value="">Tous</option>{fc?.users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</Select>}</Field>
          <Field label="Type d'action">{(p) => <Select {...p} value={f.kind} onChange={(e) => set("kind", e.target.value)}><option value="">Tous</option>{q.data?.kinds.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}</Select>}</Field>
          {active && <Button size="sm" variant="ghost" onClick={() => setF({ ...EMPTY, employee_id: employeeId ?? "" })}>Effacer les filtres</Button>}
        </div>
      )}
      {q.error ? <Callout kind="bad" title="Chargement impossible">{q.error}</Callout> : !q.data ? <SkeletonCard lines={4} /> : !items.length ? (
        <EmptyState icon="history" title="Aucune modification">{active ? "Aucune modification ne correspond à ces filtres." : "Les ajouts, remplacements, échanges, changements d'horaires, générations, restaurations et publications apparaîtront ici."}</EmptyState>
      ) : (
        <>
          <ol className="history-list" aria-label="Historique des modifications">
            {items.map((r) => (
              <li key={r.id} className="history-item" data-testid="history-event" data-kind={r.kind}>
                <div className="row"><Badge tone={TONE[r.kind] ?? "neutral"}>{r.kind_label}</Badge>{r.forced && <Badge tone="warn" icon="alert">Dérogation</Badge>}</div>
                <p className="history-title"><strong><time dateTime={r.at}>{r.at_label}</time> — {r.title}</strong></p>
                {r.lines.map((l, i) => <p key={i} className="history-line">{l}</p>)}
                <p className="help">Effectué par : {r.by}{r.shift_day_label ? <> · Date du shift : {r.shift_day_label}</> : null}{r.period ? <> · Planning : {r.period}</> : null}{r.reason ? <> · Motif : {r.reason}</> : null}</p>
                {r.details.length > 0 && (
                  <details className="history-details"><summary>Voir le détail ({r.details.length})</summary>
                    <ul>{r.details.map((d, i) => <li key={i}>{d.shift_day_label ? <strong>{d.shift_day_label} : </strong> : null}{d.lines.join(" · ")}</li>)}</ul>
                  </details>)}
              </li>))}
          </ol>
          {next && <div className="row"><Button onClick={loadMore} disabled={busy} aria-busy={busy}>Afficher plus</Button></div>}
          <p className="help">Heures affichées dans le fuseau de l&apos;entreprise ({q.data.timezone}). Les informations non enregistrées par les anciennes versions de l&apos;application sont indiquées comme telles.</p>
        </>
      )}
    </div>
  );
}
