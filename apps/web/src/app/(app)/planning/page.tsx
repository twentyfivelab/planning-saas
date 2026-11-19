"use client";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, Field, Input, PageHead, Progress, SearchInput, Select, SkeletonCard } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { ShiftCard } from "@/components/ui/ShiftCard";
import { useToast } from "@/components/ui/Toast";
import { useReassign } from "@/components/planning/useReassign";
import { SundayStrip } from "@/components/planning/SundayCounter";
import { CompatBanner } from "@/components/planning/CompatBanner";
import { AddShiftModal } from "@/components/planning/AddShiftModal";
import { DayShiftsModal, RemoveDialog } from "@/components/planning/DayShiftsModal";
import { IntegrationTracker } from "@/components/planning/IntegrationTracker";
import { PeriodProposals } from "@/components/planning/ReplacementProposal";
import { DuplicateModal, SwapModal } from "@/components/planning/SwapDuplicate";
import { DeletePlanningModal } from "@/components/planning/DeletePlanning";
import { EmployeeMonthModal } from "@/components/planning/EmployeeMonth";
import { WeekView } from "@/components/planning/WeekView";
import { HistoryPanel } from "@/components/planning/HistoryPanel";
import { ReplacementsModal, type ReplaceTarget } from "@/components/planning/ReplacementsModal";
import { ExplainModal } from "@/components/planning/ExplainModal";
import { AbsenceModal } from "@/components/planning/AbsenceModal";
import { MonthSwitcher } from "@/components/MonthSwitcher";
import { MonthNeeds, type MonthCalendar } from "@/components/planning/MonthNeeds";
import { parseMonthKey } from "@/lib/months";
import { canWork } from "@/lib/brandGroups";
import { invalidate } from "@/lib/invalidate";
import { computeCounter, type SundaySummary } from "@/lib/sundays";
import { api } from "@/lib/api";
import { brandColor, brandVars } from "@/lib/brand";
import { budgetProgress, plannedByBrand, splitShares, type BudgetRow } from "@/lib/metrics";
import {
  DOW_SHORT, KIND_LABEL, addDays, conflictsBySlot, dayLabel, daysBetween, defaultWeek, filterAssignments, fmtHM, mainBrand, shiftKind, timeShort,
  weekdayIdx, type Assignment, type ShiftKind,
} from "@/lib/schedule";

type Schedule = { assignments: Assignment[]; uncovered: { shift_id: string; slot_key: string; day: string; site: string; start: string; end: string }[] };
type RegShift = { assignment_id: string; shift_id: string; site: string; site_name: string; brands: string[]; start: string; end: string; locked: boolean };
type Reg = { id: string; employee_id: string; employee: string; day: string; new: RegShift; initial: RegShift; created_at: string };
type Emp = { id: string; code: string; name: string; brands?: Record<string, string>; sunday_quota?: number | null; sunday_mode?: "max" | "exact"; deleted_at?: string | null };
const VIEWS = [["month", "Mois"], ["general", "Planning général"], ["week", "Semaine"], ["day", "Jour"], ["employee", "Collaborateur"], ["brand", "Marque / site"]] as const;
type View = (typeof VIEWS)[number][0];
const KIND_ICON = { open: "sunrise", day: "briefcase", close: "sunset" } as const;
type Drag = { id: string; day: string; from: string } | null;
type Target = { emp: string; day: string; state: "ok" | "bad" } | null;

export default function PlanningPage() {
  const me = useMe();
  const toast = useToast();
  const canEditRole = me.permissions.includes("planning.edit");
  const { period, month, setMonth, loading: pLoading, reloadPeriods } = usePeriod();
  const archived = period?.status === "archived";
  const canEdit = canEditRole && !archived; // un planning archivé reste consultable mais n'est plus modifiable
  const ym = parseMonthKey(month);
  const cal = useApi<MonthCalendar>(`/calendar?year=${ym.y}&month=${ym.m}`);
  const sched = useApi<Schedule>(period ? `/periods/${period.id}/schedule` : null);
  const confl = useApi<{ hard_violations: string[] }>(period ? `/periods/${period.id}/conflicts` : null);
  // supprimés compris : leurs affectations passées restent affichées ; ils ne sont jamais proposés pour une nouvelle affectation
  const empsAll = useApi<Emp[]>("/employees?include_deleted=true");
  const emps = useMemo(() => ({ ...empsAll, data: empsAll.data?.filter((e) => !e.deleted_at) }), [empsAll]);
  const budgets = useApi<BudgetRow[]>("/budgets");
  const sunday = useApi<SundaySummary>(period ? `/periods/${period.id}/sunday-summary` : null);

  const [view, setView] = useState<View>("general");
  const [focusState, setFocus] = useState("");
  const [text, setText] = useState(""); const [site, setSite] = useState(""); const [brand, setBrand] = useState(""); const [empF, setEmpF] = useState(""); const [client, setClient] = useState("");
  const clients = useApi<{ id: string; name: string }[]>(me.permissions.includes("referential.read") ? "/clients" : null);
  const brandRows = useApi<{ code: string; client_id: string | null }[]>(me.permissions.includes("referential.read") ? "/brands" : null);
  const clientBrands = useMemo(() => (client ? (brandRows.data ?? []).filter((b) => b.client_id === client).map((b) => b.code) : undefined), [client, brandRows.data]);
  const [sel, setSel] = useState<Assignment | null>(null);
  const [drag, setDrag] = useState<Drag>(null); const [target, setTarget] = useState<Target>(null);

  const days = useMemo(() => (period ? daysBetween(period.start_date, period.end_date) : []), [period?.start_date, period?.end_date]); // eslint-disable-line react-hooks/exhaustive-deps -- un rechargement du même mois ne réinitialise pas la vue
  useEffect(() => { if (days.length) setFocus(defaultWeek(days)); }, [days]);
  const focus = focusState || defaultWeek(days);
  const all = useMemo(() => sched.data?.assignments ?? [], [sched.data]);
  const list = useMemo(() => filterAssignments(all, { text, site, brand, employee: empF, brands: clientBrands }), [all, text, site, brand, empF, clientBrands]);
  const histEmps = useMemo(() => (empsAll.data ?? []).filter((e) => !e.deleted_at || all.some((a) => a.employee_id === e.id))
    .map((e) => (e.deleted_at ? { ...e, name: `${e.name} (supprimé·e)` } : e)), [empsAll.data, all]);
  const alertMap = useMemo(() => conflictsBySlot(confl.data?.hard_violations ?? [], all), [confl.data, all]);
  const sites = useMemo(() => [...new Set(all.map((a) => a.site))].sort(), [all]);
  const brands = useMemo(() => [...new Set(all.flatMap((a) => Object.keys(a.allocations)))].sort(), [all]);
    const filtersActive = !!(text || site || brand || empF || client);
  const inPeriod = (d: string) => days.includes(d);
  const regsApi = useApi<Reg[]>(period ? `/periods/${period.id}/regularizations` : null);
  const regs = regsApi.data ?? [];
  const [swapping, setSwapping] = useState<Assignment | null>(null);
  const [deleting, setDeleting] = useState(false); const [deletedMsg, setDeletedMsg] = useState("");
  const [duplicating, setDuplicating] = useState<Assignment | null>(null);
  const [empMonth, setEmpMonth] = useState<{ id: string; name: string } | null>(null);
  // un seul rechargement : `invalidate` relit en silence toutes les données affichées (planning, conflits, dimanches, rappels…)
  const refresh = () => invalidate();
  const [adding, setAdding] = useState<{ emp: Emp; day: string } | null>(null);
  const [picking, setPicking] = useState<{ emp: Emp; day: string } | null>(null);
  const [removing, setRemoving] = useState<Assignment | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [replace, setReplace] = useState<ReplaceTarget>(null);
  const [explain, setExplain] = useState<string | null>(null);
  const [absence, setAbsence] = useState(false);

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
      const dragged = all.find((x) => x.assignment_id === drag.id);
      const eligible = !dragged || canWork(emps.data?.find((x) => x.id === empId)?.brands, Object.keys(dragged.allocations));
      const state = drag.day === day && eligible ? "ok" : "bad"; e.dataTransfer.dropEffect = state === "ok" ? "move" : "none";
      if (!target || target.emp !== empId || target.day !== day || target.state !== state) setTarget({ emp: empId, day, state });
    },
    onDragLeave: () => setTarget(null),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault(); const d = drag; setDrag(null); setTarget(null); if (!d) return;
      const a = all.find((x) => x.assignment_id === d.id); if (!a || d.from === empId) return;
      if (!canWork(emps.data?.find((x) => x.id === empId)?.brands, Object.keys(a.allocations))) { toast.push(`${emps.data?.find((x) => x.id === empId)?.name ?? "Ce collaborateur"} n'est pas autorisé·e sur ${Object.keys(a.allocations).join(" + ")} (fiche collaborateur).`, "warn"); return; }
      if (d.day !== day) { toast.push("Un shift ne change pas de jour par glisser-déposer : modifiez son horaire depuis la fiche.", "warn"); return; }
      reassign.request(a, empId);
    },
  });

  const loading = pLoading || sched.loading && !sched.data;
  const err = sched.error || emps.error;

  return (
    <>
      <PageHead eyebrow={period ? `${period.name} · ${period.status_label ?? ""}` : "Planning"} title="Planning">
        <MonthSwitcher month={month} onChange={setMonth} />
        {canEditRole && <a className="btn btn-primary" href="/plannings/new"><Icon name="plus" size={16} />Générer un nouveau planning</a>}
        {period && canEdit && <a className="btn" href={`/plannings/new?period=${period.id}`}><Icon name="sparkles" size={16} />Paramètres du mois</a>}
        {period && me.permissions.includes("planning.publish") && period.status !== "draft" && (
          <Button icon="history" onClick={async () => { try { await api(`/periods/${period.id}/${archived ? "unarchive" : "archive"}`, { method: "POST" }); reloadPeriods(); invalidate(); toast.push(archived ? `${period.name} désarchivé : il est de nouveau modifiable.` : `${period.name} archivé : consultable, non modifiable.`, "ok"); } catch (e) { toast.push(e instanceof Error ? e.message : "Action impossible", "bad"); } }}>{archived ? "Désarchiver" : "Archiver"}</Button>)}
        {period && me.permissions.includes("planning.delete") && period.status !== "draft" && (
          <Button variant="danger" icon="x" onClick={() => setDeleting(true)}>Supprimer ce planning</Button>)}
        <Button icon="undo" disabled={!reassign.canUndo} onClick={reassign.undo}>Annuler</Button>
        <Button icon="redo" disabled={!reassign.canRedo} onClick={reassign.redo}>Rétablir</Button>
        <Button icon="clock" onClick={() => setHistoryOpen(true)} disabled={!period}>Historique</Button>
        {period && canEdit && me.permissions.includes("availability.write") && <Button icon="alert" onClick={() => setAbsence(true)}>Déclarer une absence</Button>}
        {canEdit && <Button variant="primary" icon="history" onClick={saveVersion} disabled={!period}>Enregistrer une version</Button>}
      </PageHead>
      {deletedMsg && <Callout kind="ok" title={deletedMsg}><span data-testid="deleted-message">La suppression est inscrite dans l&apos;historique, avec votre identité. <a href="/history?kind=deletion" style={{ textDecoration: "underline" }}>Voir l&apos;historique</a></span></Callout>}

      <Card>
        <div className="toolbar" role="search" aria-label="Filtres du planning">
          <Field label="Recherche">{(p) => <SearchInput {...p} placeholder="Rechercher…" value={text} onChange={(e) => setText(e.target.value)} />}</Field>
          <Field label="Site">{(p) => <Select {...p} value={site} onChange={(e) => setSite(e.target.value)}><option value="">Tous les sites</option>{sites.map((s) => <option key={s}>{s}</option>)}</Select>}</Field>
          <Field label="Marque">{(p) => <Select {...p} value={brand} onChange={(e) => setBrand(e.target.value)}><option value="">Toutes les marques</option>{brands.map((s) => <option key={s}>{s}</option>)}</Select>}</Field>
          <Field label="Collaborateur">{(p) => <Select {...p} value={empF} onChange={(e) => setEmpF(e.target.value)}><option value="">Tous les collaborateurs</option>{emps.data?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</Select>}</Field>
          {!!clients.data?.length && <Field label="Client" help="Shifts des marques de ce client">{(p) => <Select {...p} value={client} onChange={(e) => setClient(e.target.value)}><option value="">Tous les clients</option>{clients.data!.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>}</Field>}
        </div>
        <div className="spread" style={{ marginTop: "var(--sp-4)" }}>
          <div className="seg" role="tablist" aria-label="Vues du planning">
            {VIEWS.map(([v, l]) => <button key={v} type="button" role="tab" aria-selected={view === v} className="btn" onClick={() => setView(v)}>{l}</button>)}
          </div>
          <div className="row">
            {view === "day" && days.length > 0 && (
              <>
                <Button iconOnly icon="chevL" label="Jour précédent" onClick={() => setFocus(addDays(focus, -1))} disabled={!inPeriod(addDays(focus, -1))} />
                <strong className="num" aria-live="polite" style={{ minWidth: "9.5rem", textAlign: "center" }}>
                  {dayLabel(focus)}
                </strong>
                <Button iconOnly icon="chevR" label="Jour suivant" onClick={() => setFocus(addDays(focus, 1))} disabled={!inPeriod(addDays(focus, 1))} />
                <Button size="sm" onClick={() => setFocus(defaultWeek(days))}>Début de période</Button>
              </>
            )}
            {!loading && <span className="muted num" aria-live="polite">{list.length} affectation{list.length > 1 ? "s" : ""}{filtersActive ? " (filtré)" : ""}</span>}
            {filtersActive && <Button size="sm" variant="ghost" icon="x" onClick={() => { setText(""); setSite(""); setBrand(""); setEmpF(""); }}>Réinitialiser</Button>}
          </div>
        </div>
      </Card>

      {period && (sunday.loading || emps.loading) && !sunday.data && <div className="glass skeleton" style={{ minHeight: "3.4rem" }} aria-hidden="true" />}
      {sunday.data && sunday.data.total > 0 && emps.data && (
        <SundayStrip counter={computeCounter(sunday.data, emps.data.map((e) => ({ code: e.code, sunday_quota: e.sunday_quota ?? null, sunday_mode: e.sunday_mode ?? "max" })))} onDetails={() => { window.location.href = "/employees"; }} />
      )}
      <Legend brands={brands} />

      {archived && <Callout kind="info" title={`${period!.name} est archivé`}>Ce planning reste consultable (planning général, plannings individuels, historique, versions) mais n&apos;est plus modifiable. Désarchivez-le pour le modifier.</Callout>}
      {period && all.length > 0 && !archived && <CompatBanner periodId={period.id} periodName={period.name} />}
      {period && <PeriodProposals periodId={period.id} canEdit={canEdit} />}
      {period && <IntegrationTracker periodId={period.id} emps={emps.data ?? []} canEdit={canEdit}
        onPick={(emp, day) => { const e = (emps.data ?? []).find((x) => x.id === emp.id); if (e) setPicking({ emp: e, day }); }} onChanged={refresh} />}
      {(confl.data?.hard_violations.length ?? 0) > 0 && (
        <Callout kind="warn" title={`${confl.data!.hard_violations.length} conflit(s) de contraintes dures`}>
          Les cartes concernées sont entourées en orange. <a href="/alerts" style={{ textDecoration: "underline" }}>Voir le détail</a>
        </Callout>
      )}
      {!!sched.data?.uncovered.length && (
        <Callout kind="warn" title={`${sched.data.uncovered.length} shift(s) non couvert(s)`}>
          <div className="row" style={{ marginTop: "var(--sp-1)" }}>
            {sched.data.uncovered.slice(0, 8).map((u) => <Button key={u.shift_id} size="sm" onClick={() => setReplace({ shift_id: u.shift_id, label: `${dayLabel(u.day)} · ${u.site} · ${timeShort(u.start)}–${timeShort(u.end)}` })} aria-label={`Trouver un collaborateur : ${dayLabel(u.day)}, ${u.site}, ${timeShort(u.start)}`}>{dayLabel(u.day)} {u.site} {timeShort(u.start)}</Button>)}
            {sched.data.uncovered.length > 8 && <span className="muted">+ {sched.data.uncovered.length - 8} autres</span>}
          </div>
        </Callout>)}

      {!pLoading && !period && cal.data && (
        <MonthNeeds cal={cal.data} actions={canEdit ? <a className="btn btn-primary" href="/generate"><Icon name="sparkles" size={16} />Générer automatiquement le planning</a> : undefined} />
      )}
      <div className="plan-layout" data-aside={regs.length > 0}>
      {regs.length > 0 && (
        <aside className="plan-aside glass card" aria-label="À régulariser" data-testid="regularizations">
          <div className="spread"><h2 className="h2" style={{ margin: 0 }}>À régulariser</h2><Badge tone="warn" icon="alert">{regs.length}</Badge></div>
          <p className="help" style={{ margin: 0 }}>Doubles affectations confirmées provisoirement : conflits à corriger avant validation ou publication.</p>
          {regs.map((r) => {
            const initial = all.find((a) => a.assignment_id === r.initial.assignment_id);
            const label = new Date(`${r.day}T12:00:00`).toLocaleDateString("fr-CH", { day: "numeric", month: "long", year: "numeric" });
            const fmt = (x: RegShift) => `${x.brands.join(" / ") || x.site_name}${x.brands.length ? ` (${x.site_name})` : ""}, ${x.start.replace(":", " h ").replace(" h 00", " h")}–${x.end.replace(":", " h ").replace(" h 00", " h")}`;
            return (
              <article key={r.id} className="reg-note" data-testid="regularization">
                <p><strong>{r.employee} — {label}</strong></p>
                <p>Nouvelle affectation : {fmt(r.new)}.</p>
                <p>Affectation initiale à traiter : {fmt(r.initial)}.</p>
                <p className="help">Retirez {r.employee} de l&apos;affectation initiale et réattribuez ce poste à un autre collaborateur.</p>
                <div className="row">
                  <Button size="sm" onClick={() => initial && setSel(initial)} disabled={!initial}>Voir le shift initial</Button>
                  {canEdit && <Button size="sm" onClick={() => initial && setSel(initial)} disabled={!initial}>Réattribuer</Button>}
                  {canEdit && <Button size="sm" variant="danger" onClick={() => initial && setRemoving(initial)} disabled={!initial}>Retirer l&apos;affectation</Button>}
                </div>
              </article>
            );
          })}
        </aside>
      )}
      <div style={{ minWidth: 0 }}>
      {!pLoading && !period ? null : err ? <ErrorState message={err} onRetry={() => { sched.reload(); emps.reload(); }} /> : loading ? <SkeletonCard lines={6} /> : !all.length ? (
        <Card><EmptyState icon="calendar" title="Aucun planning pour cette période" action={<a className="btn btn-primary" href="/generate"><Icon name="sparkles" size={16} />Générer le planning</a>}>Lancez une génération (simulation exploratoire tant que les données sont incomplètes) ou saisissez des affectations.</EmptyState></Card>
      ) : (
        <Card>
          {view === "month" && <MonthView days={days} list={list} alertMap={alertMap} onPickDay={(d) => { setFocus(d); setView("day"); }} />}
          {view === "general" && <GeneralGrid onOpenEmployee={(e) => setEmpMonth({ id: e.id, name: e.name.replace(" (supprimé·e)", "") })} periodId={period!.id} days={days} inPeriod={inPeriod} list={list} emps={histEmps.filter((e) => !empF || e.id === empF)} cardProps={cardProps} cellDnD={cellDnD} dragging={!!drag} canEdit={canEdit} onAdd={(emp, day) => setPicking({ emp, day })} />}
          {view === "week" && <WeekView anchor={focus} days={days} list={list} cardProps={cardProps} onAnchor={setFocus} />}
          {view === "day" && <DayView day={focus} list={list.filter((a) => a.day === focus)} uncovered={(sched.data?.uncovered ?? []).filter((u) => u.day === focus).length} cardProps={cardProps} emps={histEmps} canEdit={canEdit} onChange={reassign.request} />}
          {view === "employee" && <EmployeeView days={days} list={list} emps={histEmps} cardProps={cardProps} canEdit={canEdit} onAdd={(emp, day) => setPicking({ emp, day })} />}
          {view === "brand" && <BrandView days={days} list={list} budgets={(budgets.data ?? []).filter((x) => (x as { month?: string }).month === period?.start_date)} />}
        </Card>
      )}
      </div>
      </div>

      {reassign.dialog}
      <DayShiftsModal target={picking} periodId={period?.id ?? ""} onClose={() => setPicking(null)} onChanged={() => { setPicking(null); refresh(); }} onCreateNew={() => { setAdding(picking); setPicking(null); }} />
      {empMonth && <EmployeeMonthModal employee={empMonth} initialMonth={month} emps={emps.data ?? []} onClose={() => { setEmpMonth(null); refresh(); }} />}
      <RemoveDialog a={removing} onClose={() => setRemoving(null)} onDone={() => { setRemoving(null); refresh(); }} />
      <HistoryPanel open={historyOpen} periodId={period?.id ?? ""} employeeId={empF || undefined} onClose={() => setHistoryOpen(false)} />
      <AddShiftModal target={adding} periodId={period?.id ?? ""} onClose={() => setAdding(null)} onAdded={() => { setAdding(null); refresh(); }} />
      <ShiftModal a={sel} onClose={() => setSel(null)} canEdit={canEdit} emps={histEmps} alerts={sel ? alertMap.get(sel.assignment_id) ?? [] : []}
        onReassign={(a, to) => { setSel(null); reassign.request(a, to); }} onLock={toggleLock} onTimes={editTimes} onRemove={(a) => { setSel(null); setRemoving(a); }}
        onExplain={(a) => setExplain(a.assignment_id)} onReplacements={(a) => { setSel(null); setReplace({ shift_id: a.shift_id, label: `${dayLabel(a.day)} · ${a.site} · ${timeShort(a.start)}–${timeShort(a.end)}` }); }}
        onSwap={(a) => { setSel(null); setSwapping(a); }} onDuplicate={(a) => { setSel(null); setDuplicating(a); }} />
      {period && <DeletePlanningModal periodId={period.id} open={deleting} onClose={() => setDeleting(false)} onDeleted={(msg) => { setDeleting(false); setDeletedMsg(msg); reloadPeriods(); invalidate(); }} />}
      <SwapModal a={swapping} periodId={period?.id ?? ""} all={all} onClose={() => setSwapping(null)} onDone={() => { setSwapping(null); refresh(); }} />
      <DuplicateModal a={duplicating} period={period ?? null} onClose={() => setDuplicating(null)} onDone={() => { setDuplicating(null); refresh(); }} />
      <ExplainModal assignmentId={explain} onClose={() => setExplain(null)} />
      <ReplacementsModal target={replace} periodId={period?.id ?? ""} canEdit={canEdit} onClose={() => setReplace(null)} onDone={() => { setReplace(null); refresh(); }} />
      <AbsenceModal open={absence} periodId={period?.id ?? ""} period={period} emps={emps.data ?? []} canOptimize={me.permissions.includes("planning.optimize")} canEdit={canEdit} onClose={() => setAbsence(false)} onChanged={refresh} />
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

const hScroll = new Map<string, number>(); // position horizontale par période (conservée entre les vues)
const COL_REM = 8.75;
/**
 * Planning général : collaborateurs en lignes (colonne fixe), TOUS les jours du mois en colonnes, défilement horizontal natif
 * (trackpad, souris, tactile, clavier) + flèches. Les lignes sont rendues par le navigateur à la demande (content-visibility) pour
 * rester fluides avec des centaines de collaborateurs ; la position est conservée entre les vues et réinitialisée au changement de mois.
 */
function GeneralGrid({ onOpenEmployee, periodId, days, inPeriod, list, emps, cardProps, cellDnD, dragging, canEdit, onAdd }: { onOpenEmployee: (e: Emp) => void; periodId: string; days: string[]; inPeriod: (d: string) => boolean; list: Assignment[]; emps: Emp[]; cardProps: CardProps; cellDnD: (e: string, d: string) => any; dragging: boolean; canEdit: boolean; onAdd: (e: Emp, d: string) => void }) {
  const scroller = useRef<HTMLDivElement>(null);
  const [nav, setNav] = useState({ first: 0, last: 0, left: false, right: true });
  const today = new Date().toISOString().slice(0, 10);
  const cols = `9.5rem repeat(${days.length}, ${COL_REM}rem) 5.5rem`;
  const colPx = () => (parseFloat(getComputedStyle(document.documentElement).fontSize) || 16) * COL_REM;
  const measure = () => {
    const el = scroller.current; if (!el) return;
    const w = colPx(), name = 9.5 * (parseFloat(getComputedStyle(document.documentElement).fontSize) || 16);
    const first = Math.max(0, Math.min(days.length - 1, Math.floor(el.scrollLeft / w)));
    const last = Math.max(first, Math.min(days.length - 1, Math.floor((el.scrollLeft + el.clientWidth - name - 1) / w)));
    setNav({ first, last, left: el.scrollLeft > 1, right: el.scrollLeft + el.clientWidth < el.scrollWidth - 1 });
  };
  useLayoutEffect(() => { // restaure la position du mois (0 pour un nouveau mois)
    const el = scroller.current; if (!el) return;
    el.scrollLeft = hScroll.get(periodId) ?? 0; measure();
  }, [periodId, days.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const on = () => measure(); window.addEventListener("resize", on); return () => window.removeEventListener("resize", on); });
  const raf = useRef(0);
  const onScroll = () => { hScroll.set(periodId, scroller.current?.scrollLeft ?? 0); cancelAnimationFrame(raf.current); raf.current = requestAnimationFrame(measure); };
  const go = (n: number) => scroller.current?.scrollBy({ left: n * colPx(), behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  const toDay = (i: number) => scroller.current?.scrollTo({ left: i * colPx(), behavior: "smooth" });
  const byEmp = useMemo(() => { const m = new Map<string, Map<string, Assignment[]>>(); for (const a of list) { const r = m.get(a.employee_id) ?? new Map(); r.set(a.day, [...(r.get(a.day) ?? []), a]); m.set(a.employee_id, r); } return m; }, [list]);
  return (
    <>
      <div className="spread hgrid-bar">
        <div className="row">
          <Button iconOnly icon="chevL" label="Jours précédents" disabled={!nav.left} onClick={() => go(-7)} />
          <strong className="num" aria-live="polite" style={{ minWidth: "12rem", textAlign: "center" }}>{days.length ? `${dayLabel(days[nav.first])} – ${dayLabel(days[nav.last])}` : ""}</strong>
          <Button iconOnly icon="chevR" label="Jours suivants" disabled={!nav.right} onClick={() => go(7)} />
          <Button size="sm" onClick={() => toDay(0)} disabled={!nav.left}>Début du mois</Button>
          {days.includes(today) && <Button size="sm" onClick={() => toDay(Math.max(0, days.indexOf(today) - 1))}>Aujourd&apos;hui</Button>}
        </div>
        <p className="help">Faites glisser horizontalement (trackpad, souris, doigt) ou utilisez les flèches : les noms restent visibles.</p>
      </div>
      {dragging && <p className="help" role="status" style={{ marginBottom: "var(--sp-2)" }}>Déposez sur la ligne d&apos;un autre collaborateur, le même jour. Vert : dépôt possible · Rouge : jour différent.</p>}
      <div className="cal-scroll hgrid-scroll" ref={scroller} onScroll={onScroll} tabIndex={0} role="region" aria-label="Planning général, défilement horizontal"
        onKeyDown={(e) => { if (e.target !== e.currentTarget) return; if (e.key === "ArrowRight") { e.preventDefault(); go(1); } if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); } }}>
        <div className="hgrid" role="table" aria-label="Planning général" style={{ ["--cols" as string]: cols }}>
          <div className="hgrid-row hgrid-head" role="row">
            <div className="cal-h cal-name-h" role="columnheader">Collaborateur</div>
            {days.map((d) => <div key={d} className="cal-h" role="columnheader" data-today={d === today} data-weekend={weekdayIdx(d) >= 5 || undefined}>{DOW_SHORT[weekdayIdx(d)]} {Number(d.slice(8))}</div>)}
            <div className="cal-h cal-total-h" role="columnheader">Heures</div>
          </div>
          {emps.map((e) => {
            const mine = byEmp.get(e.id);
            let mins = 0; mine?.forEach((l) => l.forEach((a) => { mins += a.effective_minutes; }));
            return (
              <div key={e.id} className="hgrid-row" role="row">
                <div className="cal-name" role="rowheader"><button type="button" className="name-link" onClick={() => onOpenEmployee(e)} title={`Ouvrir le planning mensuel de ${e.name}`}>{e.name}</button></div>
                {days.map((d) => (
                  <div key={d} className="cal-cell" role="cell" data-off={!inPeriod(d) || undefined} data-weekend={weekdayIdx(d) >= 5 || undefined} {...cellDnD(e.id, d)} aria-label={`${e.name}, ${dayLabel(d)}`}>
                    {(mine?.get(d) ?? []).map((a) => <ShiftCard key={a.assignment_id} {...cardProps(a)} />)}
                    {canEdit && !e.deleted_at && inPeriod(d) && !mine?.get(d)?.length && <button type="button" className="cal-add" aria-label={`Ajouter un shift pour ${e.name}, ${dayLabel(d)}`} onClick={() => onAdd(e, d)}>+</button>}
                  </div>
                ))}
                <div className="cal-cell cal-total num" role="cell">{mins ? fmtHM(mins) : "–"}</div>
              </div>
            );
          })}
        </div>
      </div>
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
                  {emps.filter((e) => !e.deleted_at || e.id === a.employee_id).map((e) => { const ok = e.id === a.employee_id || canWork(e.brands, Object.keys(a.allocations)); return <option key={e.id} value={e.id} disabled={!ok}>{e.name}{ok ? "" : " — marque non autorisée"}</option>; })}
                </Select>
              </td>
            </tr>))}</tbody>
        </table></div>
      )}
    </div>
  );
}

function EmployeeView({ days, list, emps, cardProps, canEdit, onAdd }: { days: string[]; list: Assignment[]; emps: Emp[]; cardProps: CardProps; canEdit: boolean; onAdd: (e: Emp, d: string) => void }) {
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
      </div>
      <div className="cal-scroll"><div className="month" role="grid" aria-label="Vue par collaborateur">
        {DOW_SHORT.map((d) => <div key={d} className="cal-h" role="columnheader">{d}</div>)}
        {cells.map((d, i) => d ? (
          <div key={d} className="month-cell" role="gridcell"><div className="month-day">{canEdit && cur ? <button type="button" aria-label={`Shifts du ${dayLabel(d)} pour ${emps.find((e) => e.id === cur)?.name}`} onClick={() => onAdd(emps.find((e) => e.id === cur)!, d)}>{Number(d.slice(8))}</button> : <span>{Number(d.slice(8))}</span>}</div>{mine.filter((a) => a.day === d).map((a) => <ShiftCard key={a.assignment_id} {...cardProps(a, "sm")} />)}
            {canEdit && cur && !mine.some((a) => a.day === d) && <button type="button" className="cal-add" aria-label={`Ajouter un jour de travail pour ${emps.find((e) => e.id === cur)?.name}, ${dayLabel(d)}`} onClick={() => onAdd(emps.find((e) => e.id === cur)!, d)}>+</button>}</div>
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

type Allowed = { allowed: { template: string; start: string; end: string; break_minutes: number }[]; can_override: boolean };

function ShiftModal({ a, onClose, canEdit, emps, alerts, onReassign, onLock, onTimes, onRemove, onExplain, onReplacements, onSwap, onDuplicate }: { a: Assignment | null; onClose: () => void; canEdit: boolean; emps: Emp[]; alerts: string[]; onReassign: (a: Assignment, to: string) => void; onLock: (a: Assignment) => void; onTimes: (a: Assignment, f: FormData) => void; onRemove: (a: Assignment) => void; onExplain: (a: Assignment) => void; onReplacements: (a: Assignment) => void; onSwap: (a: Assignment) => void; onDuplicate: (a: Assignment) => void }) {
  const [to, setTo] = useState("");
  const [allowed, setAllowed] = useState<Allowed | null>(null);
  const [slotSel, setSlotSel] = useState("");
  useEffect(() => { setTo(a?.employee_id ?? ""); setAllowed(null); setSlotSel("");
    if (a) api<Allowed>(`/shifts/${a.shift_id}/allowed-times`).then((r) => { setAllowed(r); const cur = r.allowed.find((x) => x.start.slice(0, 5) === a.start.slice(0, 5) && x.end.slice(0, 5) === a.end.slice(0, 5)); setSlotSel(cur ? `${cur.start}|${cur.end}` : r.can_override ? "custom" : ""); }).catch(() => setAllowed({ allowed: [], can_override: false }));
  }, [a]);
  const restricted = !!allowed && allowed.allowed.length > 0;
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
          <div className="row"><Button icon="info" onClick={() => onExplain(a)}>Pourquoi ce collaborateur ?</Button><Button icon="users" onClick={() => onReplacements(a)}>Voir les remplaçants</Button></div>
          {canEdit ? (
            <>
              <div className="row" style={{ alignItems: "flex-end" }}>
                <Field label="Réaffecter à">{(p) => <Select {...p} value={to} disabled={a.locked} onChange={(e) => setTo(e.target.value)} style={{ minWidth: "12rem" }}>{emps.filter((e) => !e.deleted_at || e.id === a.employee_id).map((e) => { const ok = !e.deleted_at && canWork(e.brands, Object.keys(a.allocations)); return <option key={e.id} value={e.id} disabled={!ok}>{e.name}{ok ? "" : e.deleted_at ? "" : " — marque non autorisée"}</option>; })}</Select>}</Field>
                <Button variant="primary" disabled={a.locked || to === a.employee_id} onClick={() => onReassign(a, to)}>Réaffecter</Button>
              </div>
              <form className="row" style={{ alignItems: "flex-end" }} onSubmit={(e) => { e.preventDefault(); onTimes(a, new FormData(e.currentTarget)); }}>
                {restricted ? (
                  <>
                    <Field label="Horaire autorisé" help={`Horaires de ${a.site}`}>{(p) => (
                      <Select {...p} value={slotSel} disabled={a.locked} onChange={(e) => setSlotSel(e.target.value)} style={{ minWidth: "10rem" }}>
                        {allowed!.allowed.map((x) => <option key={x.template} value={`${x.start}|${x.end}`}>{x.start.slice(0, 5)}–{x.end.slice(0, 5)}</option>)}
                        {allowed!.can_override && <option value="custom">Autre horaire (administrateur)</option>}
                      </Select>)}</Field>
                    {slotSel !== "custom" && <><input type="hidden" name="s" value={slotSel.split("|")[0] ?? ""} /><input type="hidden" name="e" value={slotSel.split("|")[1] ?? ""} /></>}
                  </>
                ) : null}
                {(!restricted || slotSel === "custom") && (
                  <>
                    <Field label="Début">{(p) => <Input {...p} name="s" type="time" defaultValue={timeShort(a.start)} disabled={a.locked} />}</Field>
                    <Field label="Fin">{(p) => <Input {...p} name="e" type="time" defaultValue={timeShort(a.end)} disabled={a.locked} />}</Field>
                  </>
                )}
                <Field label="Pause (min)">{(p) => <Input {...p} name="b" type="number" min={0} max={480} defaultValue={a.break_minutes} disabled={a.locked} style={{ width: "6rem" }} />}</Field>
                <Button type="submit" disabled={a.locked || (restricted && !slotSel)}>Modifier l&apos;horaire</Button>
              </form>
              <div className="row"><Button icon="lock" onClick={() => onLock(a)}>{a.locked ? "Déverrouiller" : "Verrouiller"}</Button>
                <Button onClick={() => onSwap(a)}>Échanger…</Button>
                <Button onClick={() => onDuplicate(a)}>Dupliquer…</Button>
                <Button icon="x" onClick={() => onRemove(a)}>Retirer du planning</Button>
                <p className="help">{a.locked ? "Déverrouillez pour réaffecter ou modifier." : "Un shift verrouillé n'est jamais déplacé par la réoptimisation."}</p></div>
            </>
          ) : <p className="help">Lecture seule : votre rôle ne permet pas de modifier le planning.</p>}
        </>
      )}
    </Modal>
  );
}
