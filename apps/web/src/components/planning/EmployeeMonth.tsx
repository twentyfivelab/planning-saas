"use client";
import { useEffect, useMemo, useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi } from "@/components/hooks";
import { Badge, Button, Callout, Progress } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { brandColor } from "@/lib/brand";
import { invalidate } from "@/lib/invalidate";
import { type Assignment } from "@/lib/schedule";
import { errText } from "@/lib/wfm";
import { useReassign } from "./useReassign";

type Item = { assignment_id: string; shift_id: string; period_id: string; start: string; end: string; break_minutes: number; presence_minutes: number;
  effective_minutes: number; site: string; site_name: string; brands: string[]; locked: boolean; source: string };
type Day = { date: string; weekday: number; assignments: Item[]; off: { kind: string; label: string } | null };
type MonthData = { employee: { id: string; name: string; deleted: boolean }; month: string; label: string; period: { id: string; name: string; archived: boolean } | null;
  has_plan: boolean; days: Day[]; totals: { effective_minutes: number; days_worked: number; sundays_worked: number; presence_minutes: number; break_minutes: number };
  limits: { monthly_cap_minutes: number | null; min_days_month: number | null; max_days_month: number | null } };
type Emp = { id: string; name: string; brands?: Record<string, string>; deleted_at?: string | null };

const DOW = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const hm = (m: number) => `${Math.floor(m / 60)} h${m % 60 ? ` ${String(m % 60).padStart(2, "0")}` : ""}`;
const shiftMonth = (key: string, delta: number) => { const [y, m] = key.split("-").map(Number); const d = new Date(Date.UTC(y, m - 1 + delta, 1)); return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`; };
const todayKey = () => { const p = new Intl.DateTimeFormat("fr-CH", { timeZone: "Europe/Zurich", year: "numeric", month: "2-digit" }).formatToParts(new Date()); return `${p.find((x) => x.type === "year")!.value}-${p.find((x) => x.type === "month")!.value}`; };
const todayIso = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Zurich" }).format(new Date());
const dayLong = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("fr-CH", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

/** Planning mensuel d'un collaborateur : lecture des données du planning existant (aucune copie, rien n'est créé en consultant).
 *  `initialMonth` : mois consulté dans le planning général, ou mois en cours depuis la liste des collaborateurs. */
export function EmployeeMonthModal({ employee, initialMonth, onClose, emps }: { employee: { id: string; name: string } | null; initialMonth?: string; onClose: () => void; emps?: Emp[] }) {
  const me = useMe(); const toast = useToast();
  const [month, setMonth] = useState(initialMonth ?? todayKey());
  const [sel, setSel] = useState<{ day: Day; item: Item } | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false); const [to, setTo] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { setMonth(initialMonth ?? todayKey()); setSel(null); }, [employee?.id, initialMonth]);
  useEffect(() => { setSel(null); setConfirmRemove(false); }, [month]);
  const data = useApi<MonthData>(employee ? `/employees/${employee.id}/month?month=${month}` : null);
  const d = data.data;
  const canEdit = me.permissions.includes("planning.edit") && !!d?.period && !d.period.archived;
  const lead = d ? (d.days[0]?.weekday ?? 0) : 0;
  const cap = d?.limits.monthly_cap_minutes ?? null;
  const today = todayIso();
  const allEmps = useApi<Emp[]>(employee && !emps ? "/employees" : null);
  const everyone = emps ?? allEmps.data ?? [];
  const pool = everyone.filter((e) => !e.deleted_at && e.id !== employee?.id);
  // Réaffectation : même point d'entrée que le planning général (confirmation, contrôles, dérogations, rappel « À régulariser »)
  const sched = useApi<{ assignments: Assignment[] }>(sel && d?.period ? `/periods/${d.period.id}/schedule` : null);
  const reassign = useReassign({ all: sched.data?.assignments ?? [], emps: everyone, refresh: () => { setSel(null); setTo(""); data.reload(); sched.reload(); invalidate(); },
    getSchedule: async () => (await api<{ assignments: Assignment[] }>(`/periods/${d!.period!.id}/schedule`)).assignments });
  const target = sel ? sched.data?.assignments.find((a) => a.assignment_id === sel.item.assignment_id) : undefined;
  const eligible = useMemo(() => (sel ? pool.filter((e) => sel.item.brands.every((b) => b in (e.brands ?? {}))) : []), [sel, pool]);

  async function act(fn: () => Promise<unknown>, msg: string) {
    setBusy(true);
    try { await fn(); toast.push(msg, "ok"); setSel(null); setConfirmRemove(false); data.reload(); invalidate(); }
    catch (e) { toast.push(errText(e), "bad"); }
    finally { setBusy(false); }
  }
  if (!employee) return null;
  const cell = (x: Day) => (
    <div key={x.date} className="emonth-cell" data-weekend={x.weekday >= 5 || undefined} data-today={x.date === today || undefined} data-off={x.off?.kind}
      role="gridcell" aria-label={`${dayLong(x.date)}${x.assignments.length ? `, ${x.assignments.length} shift(s)` : x.off ? `, ${x.off.label}` : ", sans affectation"}`}>
      <div className="emonth-date"><span>{Number(x.date.slice(8))}</span><span className="emonth-dow">{DOW[x.weekday]}</span></div>
      {x.off && <Badge tone={x.off.kind === "conge" ? "info" : "warn"}>{x.off.label}</Badge>}
      {x.assignments.map((a) => (
        <button key={a.assignment_id} type="button" className="emonth-shift" style={{ ["--c" as string]: brandColor(a.brands[0] ?? "") }}
          aria-pressed={sel?.item.assignment_id === a.assignment_id} onClick={() => setSel({ day: x, item: a })}>
          <strong className="num">{a.start}–{a.end}</strong>
          <span>{a.site_name}</span>
          <span className="faint">{a.brands.join(" / ")}{a.break_minutes ? ` · pause ${a.break_minutes} min` : ""}{a.locked ? " · verrouillé" : ""}</span>
        </button>
      ))}
      {!x.assignments.length && !x.off && <span className="faint emonth-empty">—</span>}
    </div>
  );
  return (
    <Modal open onClose={onClose} title={`Planning de ${employee.name}`} description="Données du planning existant ; consulter ou changer de mois ne modifie rien.">
      <div className="stack emonth" data-testid="employee-month">
        <div className="spread">
          <div className="row" role="group" aria-label="Navigation entre les mois">
            <Button iconOnly icon="chevL" label="Mois précédent" onClick={() => setMonth(shiftMonth(month, -1))} />
            <strong className="emonth-title" aria-live="polite" data-testid="employee-month-label">{d?.label ?? "…"}</strong>
            <Button iconOnly icon="chevR" label="Mois suivant" onClick={() => setMonth(shiftMonth(month, 1))} />
            <Button size="sm" onClick={() => setMonth(todayKey())} disabled={month === todayKey()}>Aujourd&apos;hui</Button>
          </div>
          {d?.period && <Badge tone="neutral">{d.period.name}{d.period.archived ? " · archivé" : ""}</Badge>}
        </div>
        {data.error && <Callout kind="bad">{data.error}</Callout>}
        {!d ? <div className="skeleton" style={{ height: "18rem" }} aria-hidden="true" /> : (
          <>
            {!d.has_plan && <Callout kind="info" title={`Aucun planning pour ${d.label}`}>Aucun planning n&apos;a été créé pour ce mois. Rien n&apos;est créé automatiquement en consultant ; les indisponibilités connues restent affichées.</Callout>}
            <div className="emonth-totals" data-testid="employee-month-totals">
              <div className="glass-pink emonth-kpi"><span className="label">Travail effectif</span><strong className="num" data-testid="em-effective">{hm(d.totals.effective_minutes)}</strong>
                {cap ? <><Progress value={Math.min(100, (100 * d.totals.effective_minutes) / cap)} label="Heures sur le plafond mensuel" /><span className="help">Plafond applicable : {hm(cap)} (règle de l&apos;entreprise)</span></> : <span className="help">Aucun plafond mensuel</span>}</div>
              <div className="glass-pink emonth-kpi"><span className="label">Jours travaillés</span><strong className="num" data-testid="em-days">{d.totals.days_worked}</strong>
                <span className="help">{d.limits.min_days_month || d.limits.max_days_month ? `Fiche : min ${d.limits.min_days_month ?? "—"} · max ${d.limits.max_days_month ?? "—"}` : "Une journée compte une fois"}</span></div>
              <div className="glass-pink emonth-kpi"><span className="label">Dimanches travaillés</span><strong className="num" data-testid="em-sundays">{d.totals.sundays_worked}</strong>
                <span className="help">Présence {hm(d.totals.presence_minutes)} · pauses {hm(d.totals.break_minutes)}</span></div>
            </div>
            <div className="emonth-legend help"><Badge tone="warn">Indisponible</Badge> <Badge tone="info">Congé</Badge> <span>— : sans affectation</span></div>
            <div className="emonth-grid" role="grid" aria-label={`Calendrier de ${d.label}`}>
              {DOW.map((x) => <div key={x} className="emonth-head" role="columnheader">{x}</div>)}
              {Array.from({ length: lead }, (_, i) => <div key={`b${i}`} className="emonth-blank" aria-hidden="true" />)}
              {d.days.map(cell)}
            </div>
            {sel && (
              <section className="glass-raised card stack" aria-label="Détail de l'affectation" data-testid="employee-month-detail">
                <h3 className="h2" style={{ margin: 0 }}>{dayLong(sel.day.date)}</h3>
                <dl className="facts">
                  <div><dt>Horaires</dt><dd className="num">{sel.item.start}–{sel.item.end}</dd></div>
                  <div><dt>Pause</dt><dd>{sel.item.break_minutes} min</dd></div>
                  <div><dt>Travail effectif</dt><dd>{hm(sel.item.effective_minutes)}</dd></div>
                  <div><dt>Site</dt><dd>{sel.item.site_name}</dd></div>
                  <div><dt>Marque(s)</dt><dd>{sel.item.brands.join(" / ") || "—"}</dd></div>
                  <div><dt>Statut</dt><dd>{sel.item.locked ? "Verrouillée" : "Non verrouillée"}{sel.item.source === "manual" ? " · modifiée à la main" : ""}</dd></div>
                </dl>
                {canEdit ? (
                  <div className="stack" style={{ gap: "var(--sp-2)" }}>
                    <div className="row" style={{ alignItems: "flex-end" }}>
                      <label className="field" style={{ minWidth: "14rem" }}><span className="label">Réaffecter à</span>
                        <select className="select" value={to} onChange={(e) => setTo(e.target.value)} disabled={sel.item.locked}>
                          <option value="">Choisir…</option>{eligible.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
                        </select></label>
                      <Button variant="primary" disabled={!to || sel.item.locked || busy || !target} onClick={() => target && reassign.request(target, to)}>Réaffecter…</Button>
                      <Button disabled={busy} onClick={() => act(() => api(`/assignments/${sel.item.assignment_id}/${sel.item.locked ? "unlock" : "lock"}`, { method: "POST" }), sel.item.locked ? "Affectation déverrouillée." : "Affectation verrouillée.")}>{sel.item.locked ? "Déverrouiller" : "Verrouiller"}</Button>
                      <Button variant="danger" disabled={busy} onClick={() => setConfirmRemove(true)}>Retirer</Button>
                    </div>
                    {sel.item.locked && <p className="help">Affectation verrouillée : déverrouillez-la pour la réaffecter.</p>}
                    {confirmRemove && <Callout kind="warn" title="Retirer cette affectation ?">
                      <p style={{ margin: 0 }}>Le shift redeviendra disponible et apparaîtra dans les besoins non couverts.</p>
                      <div className="row" style={{ marginTop: "var(--sp-2)" }}><Button onClick={() => setConfirmRemove(false)}>Annuler</Button>
                        <Button variant="danger" disabled={busy} onClick={() => act(() => api(`/assignments/${sel.item.assignment_id}?force=${sel.item.locked}`, { method: "DELETE" }), "Affectation retirée.")}>Retirer</Button></div>
                    </Callout>}
                  </div>
                ) : <p className="help">{d.period?.archived ? "Planning archivé : consultation seulement." : "Votre rôle permet la consultation seulement."}</p>}
              </section>
            )}
          </>
        )}
        <div className="row modal-actions"><Button variant="primary" onClick={onClose}>Fermer</Button></div>
        {reassign.dialog}
      </div>
    </Modal>
  );
}
