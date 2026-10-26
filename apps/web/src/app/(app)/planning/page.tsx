"use client";
import { useEffect, useMemo, useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, Field, Input, PageHead, Progress, SearchInput, Select, SkeletonCard } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { ShiftCard } from "@/components/ui/ShiftCard";
import { useToast } from "@/components/ui/Toast";
import { useReassign } from "@/components/planning/useReassign";
import { api } from "@/lib/api";
import { brandColor, brandVars } from "@/lib/brand";
import { budgetProgress, plannedByBrand, splitShares, type BudgetRow } from "@/lib/metrics";
import {
  DOW_SHORT, KIND_LABEL, addDays, conflictsBySlot, dayLabel, daysBetween, defaultWeek, filterAssignments, fmtHM, mainBrand, shiftKind, timeShort,
  weekOf, weekdayIdx, type Assignment, type ShiftKind,
} from "@/lib/schedule";

type Schedule = { assignments: Assignment[]; uncovered: { shift_id: string; slot_key: string; day: string; site: string; start: string; end: string }[] };
type Emp = { id: string; code: string; name: string; brands?: Record<string, string> };
const VIEWS = [["month", "Mois"], ["week", "Semaine"], ["day", "Jour"], ["employee", "Collaborateur"], ["brand", "Marque / site"]] as const;
type View = (typeof VIEWS)[number][0];
const KIND_ICON = { open: "sunrise", day: "briefcase", close: "sunset" } as const;
type Drag = { id: string; day: string; from: string } | null;
type Target = { emp: string; day: string; state: "ok" | "bad" } | null;

export default function PlanningPage() {
  const me = useMe();
  const toast = useToast();
  const canEdit = me.permissions.includes("planning.edit");
  const { periods, period, setId, loading: pLoading } = usePeriod();
  const sched = useApi<Schedule>(period ? `/periods/${period.id}/schedule` : null);
  const confl = useApi<{ hard_violations: string[] }>(period ? `/periods/${period.id}/conflicts` : null);
  const emps = useApi<Emp[]>("/employees");
  const budgets = useApi<BudgetRow[]>("/budgets");

  const [view, setView] = useState<View>("week");
  const [focusState, setFocus] = useState("");
  const [text, setText] = useState(""); const [site, setSite] = useState(""); const [brand, setBrand] = useState(""); const [empF, setEmpF] = useState("");
  const [sel, setSel] = useState<Assignment | null>(null);
  const [drag, setDrag] = useState<Drag>(null); const [target, setTarget] = useState<Target>(null);

  const days = useMemo(() => (period ? daysBetween(period.start_date, period.end_date) : []), [period]);
  useEffect(() => { if (days.length) setFocus(defaultWeek(days)); }, [days]);
  const focus = focusState || defaultWeek(days);
  const all = useMemo(() => sched.data?.assignments ?? [], [sched.data]);
  const list = useMemo(() => filterAssignments(all, { text, site, brand, employee: empF }), [all, text, site, brand, empF]);
  const alertMap = useMemo(() => conflictsBySlot(confl.data?.hard_violations ?? [], all), [confl.data, all]);
  const sites = useMemo(() => [...new Set(all.map((a) => a.site))].sort(), [all]);
  const brands = useMemo(() => [...new Set(all.flatMap((a) => Object.keys(a.allocations)))].sort(), [all]);
    const filtersActive = !!(text || site || brand || empF);
  const week = useMemo(() => weekOf(focus), [focus]);
  const inPeriod = (d: string) => days.includes(d);
  const refresh = () => { sched.reload(); confl.reload(); };

  const reassign = useReassign({ all, emps: emps.data ?? [], refresh, getSchedule: async () => (await api<Schedule>(`/periods/${period!.id}/schedule`)).assignments });

  async function toggleLock(a: Assignment) {
    await api(`/assignments/${a.assignment_id}/${a.locked ? "unlock" : "lock"}`, { method: "POST" });
    toast.push(a.locked ? "Affectation déverrouillée." : "Affectation verrouillée : elle sera conservée lors d'une réoptimisation.", "ok"); setSel(null); refresh();
  }
  async function editTimes(a: Assignment, f: FormData) {
    try {
      const r = await api<{ conflicts: string[] }>(`/shifts/${a.shift_id}`, { method: "PATCH", json: { start_time: f.get("s"), end_time: f.get("e"), break_minutes: Number(f.get("b")) } });
      toast.push(r.conflicts.length ? `Horaire modifié — ${r.conflicts.length} conflit(s) à vérifier.` : "Horaire modifié ; durées recalculées par le serveur.", r.conflicts.length ? "warn" : "ok"); setSel(null); refresh();
    } catch (e: any) { toast.push(String(e.message), "bad"); }
  }
  async function saveVersion() {
    await api(`/periods/${period!.id}/versions`, { method: "POST" }); toast.push("Version enregistrée (voir « Versions »).", "ok");
  }

  // --- glisser-déposer : retour visuel survol / dépôt valide / refus ---
  const cardProps = (a: Assignment, size: "sm" | "lg" = "sm", showEmployee = false) => ({
    a, size, showEmployee, alerts: alertMap.get(a.assignment_id) ?? [], dragging: drag?.id === a.assignment_id,
    draggable: canEdit && !a.locked, onOpen: setSel, onDragStart: (x: Assignment) => setDrag({ id: x.assignment_id, day: x.day, from: x.employee_id }), onDragEnd: () => { setDrag(null); setTarget(null); },
  });
  const cellDnD = (empId: string, day: string) => ({
    "data-drop": target && target.emp === empId && target.day === day ? target.state : drag ? "idle" : undefined,
    onDragOver: (e: React.DragEvent) => {
      if (!drag) return; e.preventDefault();
      const state = drag.day === day ? "ok" : "bad"; e.dataTransfer.dropEffect = state === "ok" ? "move" : "none";
      if (!target || target.emp !== empId || target.day !== day || target.state !== state) setTarget({ emp: empId, day, state });
    },
    onDragLeave: () => setTarget(null),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault(); const d = drag; setDrag(null); setTarget(null); if (!d) return;
      const a = all.find((x) => x.assignment_id === d.id); if (!a || d.from === empId) return;
      if (d.day !== day) { toast.push("Un shift ne change pas de jour par glisser-déposer : modifiez son horaire depuis la fiche.", "warn"); return; }
      reassign.request(a, empId);
    },
  });

  const loading = pLoading || sched.loading && !sched.data;
  const err = sched.error || emps.error;

  return (
    <>
      <PageHead eyebrow={period ? `${dayLabel(period.start_date)} → ${dayLabel(period.end_date)}` : "Planning"} title="Planning">
        <Button icon="undo" disabled={!reassign.canUndo} onClick={reassign.undo}>Annuler</Button>
        <Button icon="redo" disabled={!reassign.canRedo} onClick={reassign.redo}>Rétablir</Button>
        {canEdit && <Button variant="primary" icon="history" onClick={saveVersion} disabled={!period}>Enregistrer une version</Button>}
      </PageHead>

      <Card>
        <div className="toolbar" role="search" aria-label="Filtres du planning">
          <Field label="Période">{(p) => <Select {...p} value={period?.id ?? ""} onChange={(e) => setId(e.target.value)}>{periods.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select>}</Field>
          <Field label="Recherche">{(p) => <SearchInput {...p} placeholder="Rechercher…" value={text} onChange={(e) => setText(e.target.value)} />}</Field>
          <Field label="Site">{(p) => <Select {...p} value={site} onChange={(e) => setSite(e.target.value)}><option value="">Tous les sites</option>{sites.map((s) => <option key={s}>{s}</option>)}</Select>}</Field>
          <Field label="Marque">{(p) => <Select {...p} value={brand} onChange={(e) => setBrand(e.target.value)}><option value="">Toutes les marques</option>{brands.map((s) => <option key={s}>{s}</option>)}</Select>}</Field>
          <Field label="Collaborateur">{(p) => <Select {...p} value={empF} onChange={(e) => setEmpF(e.target.value)}><option value="">Tous les collaborateurs</option>{emps.data?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</Select>}</Field>
        </div>
        <div className="spread" style={{ marginTop: "var(--sp-4)" }}>
          <div className="seg" role="tablist" aria-label="Vues du planning">
            {VIEWS.map(([v, l]) => <button key={v} type="button" role="tab" aria-selected={view === v} className="btn" onClick={() => setView(v)}>{l}</button>)}
          </div>
          <div className="row">
            {(view === "week" || view === "day") && days.length > 0 && (
              <>
                <Button iconOnly icon="chevL" label={view === "week" ? "Semaine précédente" : "Jour précédent"} onClick={() => setFocus(addDays(focus, view === "week" ? -7 : -1))} disabled={!inPeriod(addDays(focus, view === "week" ? -7 : -1)) && view === "day"} />
                <strong className="num" aria-live="polite" style={{ minWidth: "9.5rem", textAlign: "center" }}>
                  {view === "week" ? `${dayLabel(week[0])} – ${dayLabel(week[6])}` : dayLabel(focus)}
                </strong>
                <Button iconOnly icon="chevR" label={view === "week" ? "Semaine suivante" : "Jour suivant"} onClick={() => setFocus(addDays(focus, view === "week" ? 7 : 1))} disabled={!inPeriod(addDays(focus, view === "week" ? 7 : 1)) && view === "day"} />
                <Button size="sm" onClick={() => setFocus(defaultWeek(days))}>Début de période</Button>
              </>
            )}
            {!loading && <span className="muted num" aria-live="polite">{list.length} affectation{list.length > 1 ? "s" : ""}{filtersActive ? " (filtré)" : ""}</span>}
            {filtersActive && <Button size="sm" variant="ghost" icon="x" onClick={() => { setText(""); setSite(""); setBrand(""); setEmpF(""); }}>Réinitialiser</Button>}
          </div>
        </div>
      </Card>

      <Legend brands={brands} />

      {(confl.data?.hard_violations.length ?? 0) > 0 && (
        <Callout kind="warn" title={`${confl.data!.hard_violations.length} conflit(s) de contraintes dures`}>
          Les cartes concernées sont entourées en orange. <a href="/alerts" style={{ textDecoration: "underline" }}>Voir le détail</a>
        </Callout>
      )}
      {!!sched.data?.uncovered.length && <Callout kind="warn" title={`${sched.data.uncovered.length} shift(s) non couvert(s)`}>{sched.data.uncovered.slice(0, 6).map((u) => `${dayLabel(u.day)} ${u.site} ${timeShort(u.start)}`).join(" · ")}</Callout>}

      {err ? <ErrorState message={err} onRetry={() => { sched.reload(); emps.reload(); }} /> : loading ? <SkeletonCard lines={6} /> : !all.length ? (
        <Card><EmptyState icon="calendar" title="Aucun planning pour cette période" action={<a className="btn btn-primary" href="/generate"><Icon name="sparkles" size={16} />Générer le planning</a>}>Lancez une génération (simulation exploratoire tant que les données sont incomplètes) ou saisissez des affectations.</EmptyState></Card>
      ) : (
        <Card>
          {view === "month" && <MonthView days={days} list={list} alertMap={alertMap} onPickDay={(d) => { setFocus(d); setView("day"); }} />}
          {view === "week" && <WeekView week={week} inPeriod={inPeriod} list={list} emps={(emps.data ?? []).filter((e) => !empF || e.id === empF)} cardProps={cardProps} cellDnD={cellDnD} dragging={!!drag} />}
          {view === "day" && <DayView day={focus} list={list.filter((a) => a.day === focus)} uncovered={(sched.data?.uncovered ?? []).filter((u) => u.day === focus).length} cardProps={cardProps} emps={emps.data ?? []} canEdit={canEdit} onChange={reassign.request} />}
          {view === "employee" && <EmployeeView days={days} list={list} emps={emps.data ?? []} cardProps={cardProps} />}
          {view === "brand" && <BrandView days={days} list={list} budgets={budgets.data ?? []} />}
        </Card>
      )}

      {reassign.dialog}
      <ShiftModal a={sel} onClose={() => setSel(null)} canEdit={canEdit} emps={emps.data ?? []} alerts={sel ? alertMap.get(sel.assignment_id) ?? [] : []}
        onReassign={(a, to) => { setSel(null); reassign.request(a, to); }} onLock={toggleLock} onTimes={editTimes} />
    </>
  );
}

function Legend({ brands }: { brands: string[] }) {
  return (
    <div className="glass" style={{ padding: "var(--sp-3) var(--sp-4)" }} role="group" aria-label="Légende">
      <div className="legend">
        <strong style={{ color: "var(--fg)" }}>Légende</strong>
        {brands.length > 0 && <div className="legend-group" aria-label="Marques">{brands.map((b) => <span key={b} className="legend-item"><i className="dot" style={{ ["--c" as string]: brandColor(b) }} />{b}</span>)}</div>}
        <div className="legend-group" aria-label="Types de shifts">{(Object.keys(KIND_LABEL) as ShiftKind[]).map((k) => <span key={k} className="legend-item"><Icon name={KIND_ICON[k]} size={14} />{KIND_LABEL[k]}</span>)}</div>
        <div className="legend-group" aria-label="États">
          <span className="legend-item"><Icon name="lock" size={14} />Verrouillé</span>
          <span className="legend-item"><Icon name="alert" size={14} style={{ color: "var(--warn)" }} />Conflit</span>
          <span className="legend-item"><span className="splitbar" style={{ width: "2rem" }}><span style={{ ["--share" as string]: 1, ["--c" as string]: brandColor("Cellcosmet") }} /><span style={{ ["--share" as string]: 1, ["--c" as string]: brandColor("Nuxe") }} /></span>Répartition co-branding</span>
        </div>
      </div>
    </div>
  );
}

type CardProps = (a: Assignment, size?: "sm" | "lg", showEmployee?: boolean) => React.ComponentProps<typeof ShiftCard>;

function MonthView({ days, list, alertMap, onPickDay }: { days: string[]; list: Assignment[]; alertMap: Map<string, string[]>; onPickDay: (d: string) => void }) {
  if (!days.length) return null;
  const lead = weekdayIdx(days[0]);
  const cells: (string | null)[] = [...Array(lead).fill(null), ...days];
  while (cells.length % 7) cells.push(null);
  const byDay = new Map<string, Assignment[]>();
  list.forEach((a) => byDay.set(a.day, [...(byDay.get(a.day) ?? []), a]));
  return (
    <><p className="help cal-hint" style={{ marginBottom: "var(--sp-2)" }}>Faites défiler horizontalement pour voir toute la semaine.</p><div className="cal-scroll"><div className="month" role="grid" aria-label="Vue mensuelle">
      {DOW_SHORT.map((d) => <div key={d} className="cal-h" role="columnheader">{d}</div>)}
      {cells.map((d, i) => {
        if (!d) return <div key={i} className="month-cell" data-empty="true" role="gridcell" />;
        const items = byDay.get(d) ?? [];
        const brandCount = new Map<string, number>(); items.forEach((a) => { const b = mainBrand(a.allocations); brandCount.set(b, (brandCount.get(b) ?? 0) + 1); });
        const alerts = items.filter((a) => alertMap.has(a.assignment_id)).length;
        const mins = items.reduce((s, a) => s + a.effective_minutes, 0);
        return (
          <div key={d} className="month-cell" role="gridcell">
            <div className="month-day"><button type="button" onClick={() => onPickDay(d)} aria-label={`Ouvrir ${dayLabel(d)}`}>{Number(d.slice(8))}</button>{alerts > 0 && <Icon name="alert" size={12} style={{ color: "var(--warn)" }} />}</div>
            {items.length > 0 && <>
              <p className="num" style={{ fontSize: "var(--text-xs)", fontWeight: 650 }}>{items.length} shifts · {fmtHM(mins)}</p>
              <div className="stack" style={{ gap: "2px" }}>{[...brandCount].map(([b, n]) => <span key={b} className="badge" style={{ ...brandVars(b), background: "var(--soft)", color: "var(--ink)", justifyContent: "space-between" }}><span>{b}</span><b className="num">{n}</b></span>)}</div>
            </>}
          </div>
        );
      })}
    </div></div></>
  );
}

function WeekView({ week, inPeriod, list, emps, cardProps, cellDnD, dragging }: { week: string[]; inPeriod: (d: string) => boolean; list: Assignment[]; emps: Emp[]; cardProps: CardProps; cellDnD: (e: string, d: string) => any; dragging: boolean }) {
  const cols = `minmax(6.5rem, 9rem) repeat(7, minmax(7.5rem, 1fr)) 4rem`;
  const today = new Date().toISOString().slice(0, 10);
  return (
    <>
      {dragging && <p className="help" role="status" style={{ marginBottom: "var(--sp-2)" }}>Déposez sur la ligne d'un autre collaborateur, le même jour. Vert : dépôt possible · Rouge : jour différent.</p>}
      <p className="help cal-hint" style={{ marginBottom: "var(--sp-2)" }}>Faites défiler horizontalement pour voir toute la semaine.</p>
      <div className="cal-scroll"><div className="cal" style={{ gridTemplateColumns: cols }} role="table" aria-label="Vue hebdomadaire">
        <div className="cal-h" role="columnheader" style={{ textAlign: "left" }}>Collaborateur</div>
        {week.map((d) => <div key={d} className="cal-h" role="columnheader" data-today={d === today}>{DOW_SHORT[weekdayIdx(d)]} {Number(d.slice(8))}</div>)}
        <div className="cal-h" role="columnheader">Heures</div>
        {emps.map((e) => {
          const mine = list.filter((a) => a.employee_id === e.id && week.includes(a.day));
          const mins = mine.reduce((s, a) => s + a.effective_minutes, 0);
          return (
            <div key={e.id} style={{ display: "contents" }} role="row">
              <div className="cal-name" role="rowheader">{e.name}</div>
              {week.map((d) => (
                <div key={d} className="cal-cell" role="cell" data-off={!inPeriod(d) || undefined} {...cellDnD(e.id, d)} aria-label={`${e.name}, ${dayLabel(d)}`}>
                  {mine.filter((a) => a.day === d).map((a) => <ShiftCard key={a.assignment_id} {...cardProps(a)} />)}
                </div>
              ))}
              <div className="cal-cell num" role="cell" style={{ alignItems: "center", justifyContent: "center", fontWeight: 650 }}>{mins ? fmtHM(mins) : "–"}</div>
            </div>
          );
        })}
      </div></div>
    </>
  );
}

const T0 = 6, T1 = 23;
function DayView({ day, list, uncovered, cardProps, emps, canEdit, onChange }: { day: string; list: Assignment[]; uncovered: number; cardProps: CardProps; emps: Emp[]; canEdit: boolean; onChange: (a: Assignment, to: string) => void }) {
  const kinds: Record<ShiftKind, number> = { open: 0, day: 0, close: 0 };
  list.forEach((a) => kinds[shiftKind(a.start, a.end)]++);
  const rows = [...new Map(list.map((a) => [a.employee_id, a.employee])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const hr = (t: string) => Number(t.slice(0, 2)) + Number(t.slice(3, 5)) / 60;
  return (
    <div className="stack">
      <div className="row">
        <Badge tone="accent">{list.length} shifts</Badge>
        {(Object.keys(kinds) as ShiftKind[]).map((k) => <Badge key={k} icon={KIND_ICON[k]}>{KIND_LABEL[k]} : {kinds[k]}</Badge>)}
        {uncovered > 0 && <Badge tone="warn" icon="alert">{uncovered} non couvert(s)</Badge>}
      </div>
      {list.length === 0 ? <EmptyState icon="calendar" title="Aucun shift ce jour">Aucune affectation ne correspond à ce jour et à ces filtres.</EmptyState> : (
        <div className="cal-scroll"><div className="timeline" role="table" aria-label={`Vue journalière, ${dayLabel(day)}`}>
          <div className="cal-h" style={{ textAlign: "left" }}>Collaborateur</div>
          <div className="tl-axis" aria-hidden="true">{Array.from({ length: T1 - T0 }, (_, i) => <span key={i}>{T0 + i}h</span>)}</div>
          {rows.map(([id, name]) => (
            <div key={id} style={{ display: "contents" }} role="row">
              <div className="cal-name" role="rowheader">{name}</div>
              <div className="tl-lane" role="cell" style={{ backgroundSize: `calc(100% / ${T1 - T0}) 100%` }}>
                {list.filter((a) => a.employee_id === id).map((a) => (
                  <div key={a.assignment_id} className="tl-bar" style={{ ["--l" as string]: `${((hr(a.start) - T0) / (T1 - T0)) * 100}%`, ["--w" as string]: `${((hr(a.end) - hr(a.start)) / (T1 - T0)) * 100}%` }}>
                    <ShiftCard {...cardProps(a)} />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div></div>
      )}
      {list.length > 0 && (
        <div className="table-wrap"><table className="table table-cards">
          <caption>Réaffectation rapide (chaque changement demande une confirmation)</caption>
          <thead><tr><th>Shift</th><th>Site</th><th>Collaborateur</th></tr></thead>
          <tbody>{list.map((a) => (
            <tr key={a.assignment_id}>
              <td className="cell-main num nowrap">{timeShort(a.start)}–{timeShort(a.end)}</td>
              <td data-label="Site">{a.site}</td>
              <td data-label="Collaborateur">
                <Select aria-label={`Collaborateur pour ${a.site} ${timeShort(a.start)}–${timeShort(a.end)}`} value={a.employee_id} disabled={!canEdit || a.locked} onChange={(e) => onChange(a, e.target.value)} style={{ minWidth: "11rem" }}>
                  {emps.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
                </Select>
              </td>
            </tr>))}</tbody>
        </table></div>
      )}
    </div>
  );
}

function EmployeeView({ days, list, emps, cardProps }: { days: string[]; list: Assignment[]; emps: Emp[]; cardProps: CardProps }) {
  const [id, setId] = useState("");
  const cur = id || emps[0]?.id || "";
  const mine = list.filter((a) => a.employee_id === cur);
  const total = mine.reduce((s, a) => s + a.effective_minutes, 0);
  const lead = days.length ? weekdayIdx(days[0]) : 0;
  const cells: (string | null)[] = [...Array(lead).fill(null), ...days]; while (cells.length % 7) cells.push(null);
  return (
    <div className="stack">
      <div className="row">
        <Field label="Collaborateur">{(p) => <Select {...p} value={cur} onChange={(e) => setId(e.target.value)} style={{ minWidth: "14rem" }}>{emps.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</Select>}</Field>
        <Badge tone="accent">{new Set(mine.map((a) => a.day)).size} jours travaillés</Badge><Badge>{fmtHM(total)} effectives</Badge>
        <Badge tone="info" icon="info">Aucun plafond affiché : contrats non renseignés</Badge>
      </div>
      <div className="cal-scroll"><div className="month" role="grid" aria-label="Vue par collaborateur">
        {DOW_SHORT.map((d) => <div key={d} className="cal-h" role="columnheader">{d}</div>)}
        {cells.map((d, i) => d ? (
          <div key={d} className="month-cell" role="gridcell"><div className="month-day"><span>{Number(d.slice(8))}</span></div>{mine.filter((a) => a.day === d).map((a) => <ShiftCard key={a.assignment_id} {...cardProps(a, "sm")} />)}</div>
        ) : <div key={i} className="month-cell" data-empty="true" role="gridcell" />)}
      </div></div>
    </div>
  );
}

function BrandView({ days, list, budgets }: { days: string[]; list: Assignment[]; budgets: BudgetRow[] }) {
  const planned = plannedByBrand(list);
  const siteCount = new Map<string, number>(); list.forEach((a) => siteCount.set(a.site, (siteCount.get(a.site) ?? 0) + 1));
  const brandList = budgets.length ? budgets.map((b) => b.brand_code) : Object.keys(planned);
  return (
    <div className="stack">
      <div className="grid-2">
        {brandList.map((b) => {
          const bud = budgets.find((x) => x.brand_code === b); const p = planned[b] ?? 0;
          const has = new Set(list.filter((a) => b in a.allocations).map((a) => a.day));
          return (
            <section key={b} className="surface" style={{ padding: "var(--sp-4)", ...brandVars(b) as React.CSSProperties }} aria-label={b}>
              <div className="spread"><span className="row"><i className="dot" style={{ ["--c" as string]: brandColor(b) }} /><strong>{b}</strong></span>
                {bud && !bud.requirements_defined && <Badge tone="warn" icon="alert">À renseigner</Badge>}</div>
              <p className="num" style={{ margin: "var(--sp-2) 0" }}><b>{fmtHM(p)}</b> <span className="muted">/ {bud ? fmtHM(bud.target_minutes) : "budget non saisi"}</span></p>
              {bud && <Progress value={budgetProgress(p, bud.target_minutes)} label={`${b} : budget planifié`} color={brandColor(b)} />}
              <div className="heat" style={{ marginTop: "var(--sp-3)", ["--n" as string]: days.length }} aria-label={`Jours planifiés ${b}`} role="img">{days.map((d) => <i key={d} title={dayLabel(d)} data-state={has.has(d) ? "ok" : undefined} style={{ ["--c" as string]: brandColor(b) }} />)}</div>
              {bud && !bud.requirements_defined && <p className="help" style={{ marginTop: "var(--sp-2)" }}>Jours et horaires non définis : ces heures ne sont pas planifiables.</p>}
            </section>
          );
        })}
      </div>
      <div className="table-wrap"><table className="table"><caption>Shifts par site</caption><thead><tr><th>Site</th><th>Shifts</th></tr></thead><tbody>{[...siteCount].map(([s, n]) => <tr key={s}><td>{s}</td><td className="num">{n}</td></tr>)}</tbody></table></div>
    </div>
  );
}

function ShiftModal({ a, onClose, canEdit, emps, alerts, onReassign, onLock, onTimes }: { a: Assignment | null; onClose: () => void; canEdit: boolean; emps: Emp[]; alerts: string[]; onReassign: (a: Assignment, to: string) => void; onLock: (a: Assignment) => void; onTimes: (a: Assignment, f: FormData) => void }) {
  const [to, setTo] = useState("");
  useEffect(() => setTo(a?.employee_id ?? ""), [a]);
  return (
    <Modal open={!!a} onClose={onClose} title={a ? `${a.employee} · ${a.site}` : ""} description={a ? `${dayLabel(a.day)} · ${timeShort(a.start)}–${timeShort(a.end)}` : undefined}>
      {a && (
        <>
          <div className="row">
            {Object.keys(a.allocations).map((b) => <Badge key={b} style={{ ...(brandVars(b) as React.CSSProperties), background: "var(--soft)", color: "var(--ink)" }}>{b}</Badge>)}
            <Badge icon={KIND_ICON[shiftKind(a.start, a.end)]}>{KIND_LABEL[shiftKind(a.start, a.end)]}</Badge>
            {a.locked && <Badge tone="accent" icon="lock">Verrouillé</Badge>}
            <Badge tone={a.source === "manual" ? "info" : "neutral"}>{a.source === "manual" ? "Modifié manuellement" : "Proposé par le solveur"}</Badge>
          </div>
          <dl style={{ margin: 0, display: "grid", gap: "var(--sp-3)", gridTemplateColumns: "repeat(auto-fit, minmax(7rem, 1fr))" }}>
            {[["Présence", fmtHM(a.presence_minutes)], ["Pause non travaillée", `${a.break_minutes} min`], ["Travail effectif", fmtHM(a.effective_minutes)]].map(([k, v]) => (
              <div key={k} className="surface-2" style={{ padding: "var(--sp-3)" }}><dt className="muted" style={{ fontSize: "var(--text-xs)" }}>{k}</dt><dd className="kpi-value" style={{ margin: 0, fontSize: "var(--text-xl)" }}>{v}</dd></div>
            ))}
          </dl>
          {splitShares(a.allocations).length > 1 && (
            <div><p className="label">Imputation budgétaire (une seule affectation, heures non doublées)</p>
              <span className="splitbar" style={{ height: "0.625rem", margin: "var(--sp-2) 0" }}>{splitShares(a.allocations).map((s) => <span key={s.brand} style={{ ["--share" as string]: s.pct, ["--c" as string]: brandColor(s.brand) }} />)}</span>
              <p className="muted">{splitShares(a.allocations).map((s) => `${s.brand} ${fmtHM(s.minutes)} (${s.pct} %)`).join(" · ")}</p></div>
          )}
          {alerts.length > 0 && <Callout kind="warn" title="Conflits sur ce shift"><ul style={{ paddingLeft: "1.1rem", margin: 0 }}>{alerts.map((c) => <li key={c}>{c}</li>)}</ul></Callout>}
          {canEdit ? (
            <>
              <div className="row" style={{ alignItems: "flex-end" }}>
                <Field label="Réaffecter à">{(p) => <Select {...p} value={to} disabled={a.locked} onChange={(e) => setTo(e.target.value)} style={{ minWidth: "12rem" }}>{emps.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</Select>}</Field>
                <Button variant="primary" disabled={a.locked || to === a.employee_id} onClick={() => onReassign(a, to)}>Réaffecter</Button>
              </div>
              <form className="row" style={{ alignItems: "flex-end" }} onSubmit={(e) => { e.preventDefault(); onTimes(a, new FormData(e.currentTarget)); }}>
                <Field label="Début">{(p) => <Input {...p} name="s" type="time" defaultValue={timeShort(a.start)} disabled={a.locked} />}</Field>
                <Field label="Fin">{(p) => <Input {...p} name="e" type="time" defaultValue={timeShort(a.end)} disabled={a.locked} />}</Field>
                <Field label="Pause (min)">{(p) => <Input {...p} name="b" type="number" min={0} max={480} defaultValue={a.break_minutes} disabled={a.locked} style={{ width: "6rem" }} />}</Field>
                <Button type="submit" disabled={a.locked}>Modifier l&apos;horaire</Button>
              </form>
              <div className="row"><Button icon="lock" onClick={() => onLock(a)}>{a.locked ? "Déverrouiller" : "Verrouiller"}</Button>
                <p className="help">{a.locked ? "Déverrouillez pour réaffecter ou modifier." : "Un shift verrouillé n'est jamais déplacé par la réoptimisation."}</p></div>
            </>
          ) : <p className="help">Lecture seule : votre rôle ne permet pas de modifier le planning.</p>}
        </>
      )}
    </Modal>
  );
}
