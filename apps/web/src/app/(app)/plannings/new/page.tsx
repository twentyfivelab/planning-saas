"use client";
import { SaveQueue } from "@/lib/saveQueue";
import { SaveStatus } from "@/components/ui/SaveStatus";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMe } from "@/components/Shell";
import { useApi, usePeriod, type Period } from "@/components/hooks";
import { MonthSwitcher } from "@/components/MonthSwitcher";
import { MonthNeeds, type MonthCalendar } from "@/components/planning/MonthNeeds";
import { SitesEditor } from "@/components/planning/SitesEditor";
import { SundayCounter } from "@/components/planning/SundayCounter";
import { useMonthSheet } from "@/components/planning/useMonthSheet";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { Badge, Button, Callout, Card, EmptyState, Input, PageHead, SearchInput, Select } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError } from "@/lib/api";
import { ParamsChoice, RunFailure, RunProgress, SaveOutcome, TimeLimitField, type ParamsMode, type RunView } from "@/components/planning/RunStatus";
import { brandColor } from "@/lib/brand";
import { summarize } from "@/lib/employeeRules";
import { invalidate } from "@/lib/invalidate";
import { monthLabel, parseMonthKey } from "@/lib/months";
import { STATUS_TONE, type PeriodRow } from "@/lib/periods";
import { fmtHM } from "@/lib/schedule";

const STEPS = ["Période", "Collaborateurs", "Paramètres individuels", "Marques et sites", "Vérification", "Génération"];
type RosterRow = { employee_id: string; code: string; name: string; state: "included" | "excluded" | "inactive" | "contract_ended"; included: boolean; selectable: boolean; reason: string | null; contract_end: string | null };
type Roster = { employees: RosterRow[]; included: number; total: number };
type Check = { level: "warning" | "info" | "blocking"; text: string };
type BrandRow = { code: string; base_minutes?: number | null; name: string; group_code: string | null; archived: boolean; active: boolean; budget_minutes: number | null; strict: boolean; reference_minutes: number | null; reference_month: string;
  need_mandatory_minutes: number; need_optional_minutes: number; shifts: number; animation_days: number; sites: { code: string; name: string }[]; schedules: string[]; checks: Check[] };
type SiteRow = { code: string; name: string; archived: boolean; active: boolean; shifts: number; minutes: number; brands: { code: string; name: string }[] };
type Readiness = { period: PeriodRow; days: number; sundays: number; saturdays: number; employees: { included: number; excluded: string[]; contract_ended: string[]; inactive: string[] };
  brands: { active: string[]; inactive: string[] }; sites: { active: string[]; inactive: string[] }; budget_minutes: number; shifts: number; mandatory_shifts: number; effective_minutes: number;
  sunday_shifts: number; sundays_reserved: number; unavailabilities: Record<string, number>; unavailable_days: number;
  constraints: { max_days_exceptions: number; sunday_quotas: number; strict_time_prefs: number; max_days: number }; issues: Check[]; ready: boolean };
const err = (e: unknown) => (e instanceof Error ? e.message : "Opération impossible");

export default function NewPlanningPage() {
  return <Suspense fallback={<div className="skeleton" style={{ height: "20rem" }} aria-hidden="true" />}><Wizard /></Suspense>;
}

/** Assistant « + Générer un nouveau planning » : chaque étape enregistre immédiatement (brouillon repris à tout moment). */
function Wizard() {
  const me = useMe(); const toast = useToast(); const router = useRouter(); const search = useSearchParams();
  const { periods, month, setMonth, ensure, reloadPeriods, loading } = usePeriod();
  const [pid, setPid] = useState<string | null>(search.get("period"));
  const [step, setStep] = useState(1);
  const init = useRef(false);
  const current = periods.find((p) => p.id === pid) as (Period & PeriodRow) | undefined;
  const existing = periods.find((p) => p.start_date === `${month}-01`) as (Period & PeriodRow) | undefined;
  const canEdit = me.permissions.includes("planning.edit");
  // brouillon supprimé (dans un autre onglet, ou lien ancien) : plus aucune étape ni enregistrement, retour à la liste
  const seen = useRef(new Set<string>());
  for (const p of periods) seen.current.add(p.id);
  const gone = !!pid && !loading && !periods.some((p) => p.id === pid) && (seen.current.has(pid) || search.get("period") === pid);

  useEffect(() => { // reprise d'un brouillon : mois et étape enregistrés
    if (init.current || loading || !pid) return;
    const p = periods.find((x) => x.id === pid);
    if (!p) return;
    init.current = true; setMonth(p.start_date.slice(0, 7)); setStep(Math.max(2, p.wizard_step ?? 2));
  }, [pid, periods, loading, setMonth]);

  async function goTo(n: number, id = pid) {
    setStep(n);
    if (id) { try { await api(`/periods/${id}/wizard`, { method: "PATCH", json: { step: n } }); reloadPeriods(); } catch { /* lecture seule : la navigation reste possible */ } }
    window.scrollTo({ top: 0 });
  }
  async function start() {
    try {
      const p = existing ?? await ensure(); // rien n'est généré : on prépare seulement la période
      setPid(p.id); await goTo(2, p.id);
    } catch (e) { toast.push(err(e), "bad"); }
  }
  const label = monthLabel(month);
  if (gone) return (
    <>
      <PageHead eyebrow="Assistant" title="Générer un nouveau planning" />
      <Callout kind="warn" title="Ce planning a été supprimé">
        <p style={{ margin: 0 }} data-testid="wizard-deleted">Il n&apos;est plus modifiable et rien n&apos;y est enregistré. Vous pouvez créer volontairement un nouveau planning pour ce mois : il aura sa propre identité.</p>
        <div className="row" style={{ marginTop: "var(--sp-2)" }}>
          <Button variant="primary" onClick={() => { setPid(null); setStep(1); router.replace("/plannings/new"); }}>Revenir au choix du mois</Button>
          <Button onClick={() => router.push("/planning")}>Ouvrir le planning</Button>
        </div>
      </Callout>
    </>
  );
  return (
    <>
      <PageHead eyebrow={step > 1 ? label : "Assistant"} title="Générer un nouveau planning">
        {current && <Badge tone={STATUS_TONE[current.status ?? "draft"]}>{current.status_label}</Badge>}
      </PageHead>
      <ol className="stepper" aria-label="Étapes de création">
        {STEPS.map((l, i) => {
          const n = i + 1; const reachable = n === 1 || !!pid;
          return (
            <li key={l} className="step" data-done={n < step || undefined} aria-current={step === n ? "step" : undefined}>
              <button type="button" className="step-btn" disabled={!reachable} onClick={() => (n === 1 ? setStep(1) : void goTo(n))}><i>{n < step ? <Icon name="check" size={12} /> : n}</i>{l}</button>
            </li>);
        })}
      </ol>

      {step === 1 && <StepPeriod month={month} setMonth={(m) => { setMonth(m); setPid(null); }} existing={existing} onOpen={() => router.push("/planning")}
        onEdit={() => { if (existing) { setPid(existing.id); void goTo(Math.max(2, existing.wizard_step ?? 2), existing.id); } }} onNext={start} canEdit={canEdit} />}
      {step === 2 && pid && <StepRoster pid={pid} canEdit={canEdit && current?.status !== "archived"} />}
      {step === 3 && pid && <StepParams pid={pid} month={month} />}
      {step === 4 && pid && <StepBrands pid={pid} month={month} canEdit={me.permissions.includes("budgets.write") && current?.status !== "archived"} canCatalog={me.permissions.includes("referential.write")} />}
      {step === 5 && pid && <StepReview pid={pid} goTo={goTo} />}
      {step === 6 && pid && <StepGenerate pid={pid} period={current} onDone={() => { reloadPeriods(); invalidate(); }} onOpen={() => { setMonth(month); router.push("/planning"); }} />}

      {step > 1 && (
        <div className="glass row wizard-nav" role="navigation" aria-label="Navigation de l'assistant">
          <Button icon="chevL" onClick={() => (step === 2 ? setStep(1) : void goTo(step - 1))}>Précédent</Button>
          <span className="muted">Étape {step} sur {STEPS.length} · enregistré automatiquement</span>
          {step < STEPS.length ? <Button variant="primary" onClick={() => void goTo(step + 1)}>Suivant : {STEPS[step].toLowerCase()}<Icon name="chevR" size={16} /></Button> : <span />}
        </div>
      )}
    </>
  );
}

function StepPeriod({ month, setMonth, existing, onOpen, onEdit, onNext, canEdit }: { month: string; setMonth: (m: string) => void; existing?: Period & PeriodRow; onOpen: () => void; onEdit: () => void; onNext: () => void; canEdit: boolean }) {
  const { y, m } = parseMonthKey(month);
  const cal = useApi<MonthCalendar>(`/calendar?year=${y}&month=${m}`);
  return (
    <div className="stack">
      <Card title="Choisissez le mois et l'année">
        <div className="stack">
          <MonthSwitcher month={month} onChange={setMonth} />
          <p className="help">Choisir une période ne génère rien : vous préparez d&apos;abord l&apos;effectif, les paramètres, les marques et les budgets.</p>
          {existing && existing.status !== "draft" ? (
            <Callout kind="warn" title={`Un planning existe déjà pour ${monthLabel(month)} (${existing.status_label?.toLowerCase()})`}>
              <p style={{ margin: 0 }}>Il ne sera jamais écrasé sans votre confirmation explicite.</p>
              <div className="row" style={{ marginTop: "var(--sp-2)" }}>
                <Button variant="primary" icon="calendar" onClick={onOpen}>Ouvrir le planning</Button>
                {canEdit && <Button icon="history" onClick={onEdit}>Modifier ses paramètres</Button>}
              </div>
            </Callout>
          ) : existing ? (
            <Callout kind="info" title={`Brouillon en cours pour ${monthLabel(month)}`}>
              <div className="row"><Button variant="primary" onClick={onEdit}>Reprendre le brouillon</Button></div>
            </Callout>
          ) : (
            <div className="row"><Button variant="primary" icon="plus" disabled={!canEdit} onClick={onNext}>Créer le planning de {monthLabel(month)} et continuer</Button></div>
          )}
        </div>
      </Card>
      {cal.data && <MonthNeeds cal={cal.data} />}
    </div>
  );
}

function StepRoster({ pid, canEdit }: { pid: string; canEdit: boolean }) {
  const r = useApi<Roster>(`/periods/${pid}/roster`);
  const [q, setQ] = useState(""); const [rows, setRows] = useState<RosterRow[] | null>(null);
  const [, rerender] = useState(0);
  // enregistrement automatique fiable : un envoi à la fois, « Enregistré » seulement après confirmation de TOUTES les modifications
  const queue = useRef<SaveQueue<string, boolean> | null>(null);
  if (!queue.current) queue.current = new SaveQueue<string, boolean>(async (batch) => {
    const res = await api<Roster>(`/periods/${pid}/roster`, { method: "PUT", json: { employees: [...batch].map(([employee_id, included]) => ({ employee_id, included })) } });
    if (!queue.current!.unsaved) { r.mutate(res); setRows(res.employees); } // une réponse ne remplace jamais des modifications plus récentes à l'écran
    invalidate();
  }, () => rerender((x) => x + 1), 350, (e) => e instanceof ApiError && (e.status === 404 || e.status === 410)); // planning supprimé entre-temps : arrêt définitif
  useEffect(() => () => queue.current?.dispose(), []);
  useEffect(() => { if (r.data && !queue.current?.unsaved) setRows(r.data.employees); }, [r.data]);
  function toggle(ids: string[], included: boolean) {
    setRows((x) => (x ?? []).map((e) => (ids.includes(e.employee_id) && e.selectable ? { ...e, included, state: included ? "included" : "excluded" } : e)));
    for (const id of ids) queue.current!.set(id, included);
  }
  const list = (rows ?? []).filter((e) => !q || e.name.toLowerCase().includes(q.toLowerCase()));
  const selectable = list.filter((e) => e.selectable).map((e) => e.employee_id);
  const n = (rows ?? []).filter((e) => e.included).length;
  return (
    <Card title="Collaborateurs du mois" eyebrow={`${n} sélectionné${n > 1 ? "s" : ""} sur ${(rows ?? []).length}`} actions={<SaveStatus state={queue.current.state} error={queue.current.error} confirmed={queue.current.confirmed} onRetry={() => queue.current!.retry()} />}>
      <div className="stack">
        <p className="help">Décocher un collaborateur l&apos;exclut <strong>uniquement de ce mois</strong> : sa fiche, son historique, ses anciens shifts et ses autres mois ne changent pas. « Contrat terminé » et « Inactif » sont des états permanents (fiche / contrat).</p>
        <div className="row">
          <div style={{ minWidth: "14rem", flex: 1 }}><SearchInput aria-label="Rechercher un collaborateur" placeholder="Rechercher un collaborateur…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <Button size="sm" disabled={!canEdit} onClick={() => toggle(selectable, true)}>Tout sélectionner</Button>
          <Button size="sm" disabled={!canEdit} onClick={() => toggle(selectable, false)}>Tout désélectionner</Button>
        </div>
        {!rows ? <div className="skeleton" style={{ height: "10rem" }} aria-hidden="true" /> : (
          <ul className="roster-list" aria-label="Effectif du mois">{list.map((e) => (
            <li key={e.employee_id} className="roster-item" data-state={e.state}>
              <label className="row" style={{ flexWrap: "nowrap" }}><input type="checkbox" checked={e.included} disabled={!canEdit || !e.selectable} onChange={(ev) => toggle([e.employee_id], ev.target.checked)} /><strong>{e.name}</strong></label>
              {e.state === "excluded" && <Badge tone="warn">Exclu ce mois</Badge>}
              {e.state === "contract_ended" && <Badge>Contrat terminé{e.contract_end ? ` le ${e.contract_end.slice(8)}/${e.contract_end.slice(5, 7)}` : ""}</Badge>}
              {e.state === "inactive" && <Badge>Inactif</Badge>}
            </li>))}</ul>
        )}
      </div>
    </Card>
  );
}

function StepParams({ pid, month }: { pid: string; month: string }) {
  const sheet = useMonthSheet(month);
  const r = useApi<Roster>(`/periods/${pid}/roster`);
  const included = new Set((r.data?.employees ?? []).filter((e) => e.included).map((e) => e.employee_id));
  const list = sheet.empsM.filter((e) => included.has(e.id));
  return (
    <div className="stack">
      {sheet.counter && sheet.summary && sheet.summary.total > 0 && <SundayCounter counter={sheet.counter} summary={sheet.summary} />}
      <Card title="Paramètres individuels" eyebrow={`${list.length} collaborateur${list.length > 1 ? "s" : ""} retenu${list.length > 1 ? "s" : ""}`}>
        <p className="help">Les paramètres permanents de chaque fiche sont repris automatiquement. Indisponibilités, dimanches et exception de jours maximum ne concernent que {monthLabel(month)}.</p>
        {list.length === 0 ? <EmptyState icon="users" title="Aucun collaborateur retenu">Revenez à l&apos;étape précédente pour sélectionner l&apos;effectif.</EmptyState> : (
          <div className="table-wrap"><table className="table table-cards">
            <thead><tr><th>Collaborateur</th><th>Marques autorisées</th><th>Paramètres du mois</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{list.map((e) => { const eff = sheet.effective(e); return (
              <tr key={e.id}><td className="cell-main"><strong>{e.name}</strong></td>
                <td data-label="Marques"><div className="row">{Object.keys(e.brands).length ? Object.keys(e.brands).map((b) => <Badge key={b}><i className="dot" style={{ ["--c" as string]: brandColor(b) }} />{b}</Badge>) : <Badge tone="warn">Aucune</Badge>}</div></td>
                <td data-label="Paramètres"><div className="row">{summarize(eff).map((x) => <Badge key={x} tone="accent">{x}</Badge>)}{eff.exception && <Badge tone="info">Exception du mois</Badge>}{!summarize(eff).length && <span className="faint">Pas de préférence</span>}</div></td>
                <td><Button size="sm" disabled={!sheet.ready} onClick={() => sheet.open(e)}>Configurer</Button></td></tr>); })}</tbody>
          </table></div>
        )}
      </Card>
      {sheet.element}
    </div>
  );
}

function StepBrands({ pid, month, canEdit, canCatalog }: { pid: string; month: string; canEdit: boolean; canCatalog: boolean }) {
  const toast = useToast();
  const brands = useApi<BrandRow[]>(`/periods/${pid}/brands`);
  const sites = useApi<SiteRow[]>(`/periods/${pid}/sites`);
  const [editor, setEditor] = useState(false);
  async function put(code: string, body: Record<string, unknown>) {
    try { const r = await api<BrandRow>(`/periods/${pid}/brands/${encodeURIComponent(code)}`, { method: "PUT", json: body }); brands.mutate((brands.data ?? []).map((b) => (b.code === code ? r : b))); invalidate(); }
    catch (e) { toast.push(err(e), "bad"); }
  }
  async function site(code: string, active: boolean) {
    try { const r = await api<SiteRow>(`/periods/${pid}/sites/${encodeURIComponent(code)}`, { method: "PUT", json: { active } }); sites.mutate((sites.data ?? []).map((s) => (s.code === code ? r : s))); brands.reload(); invalidate(); }
    catch (e) { toast.push(err(e), "bad"); }
  }
  // total recalculé pendant la saisie (valeur en cours de frappe), avant même l'enregistrement
  const [drafts, setDrafts] = useState<Record<string, number | null>>({});
  const total = useMemo(() => (brands.data ?? []).filter((b) => b.active).reduce((s, b) => s + ((b.code in drafts ? drafts[b.code] : b.budget_minutes) ?? 0), 0), [brands.data, drafts]);
  return (
    <div className="stack">
      <Card title={`Marques et budgets horaires — ${monthLabel(month)}`} eyebrow={`Budget total actif : ${fmtHM(total)}`} actions={canCatalog ? <Button icon="briefcase" onClick={() => setEditor(true)}>Ajouter ou modifier des sites et marques</Button> : undefined}>
        <p className="help">Les budgets sont propres à ce mois : ceux des autres mois ne changent jamais. La référence du mois précédent n&apos;est jamais imposée : reprenez-la explicitement si besoin.</p>
        {!brands.data ? <div className="skeleton" style={{ height: "12rem" }} aria-hidden="true" /> : (
          <div className="table-wrap"><table className="table table-cards" aria-label="Marques du mois">
            <thead><tr><th>Active</th><th>Marque</th><th>Budget du mois</th><th>Besoins de couverture</th><th>Horaires et sites</th></tr></thead>
            <tbody>{brands.data.map((b) => <BrandLine key={b.code} b={b} canEdit={canEdit && !b.archived} onPut={(body) => put(b.code, body)} onDraft={(v) => setDrafts((d) => ({ ...d, [b.code]: v }))} />)}</tbody>
          </table></div>
        )}
      </Card>
      <Card title={`Sites actifs — ${monthLabel(month)}`}>
        {!sites.data ? <div className="skeleton" style={{ height: "6rem" }} aria-hidden="true" /> : (
          <div className="table-wrap"><table className="table table-cards" aria-label="Sites du mois">
            <thead><tr><th>Actif</th><th>Site</th><th>Marques</th><th>Shifts du mois</th></tr></thead>
            <tbody>{sites.data.map((s) => (
              <tr key={s.code}>
                <td><input type="checkbox" aria-label={`Site ${s.name} actif`} checked={s.active} disabled={!canEdit || s.archived} onChange={(e) => site(s.code, e.target.checked)} /></td>
                <td className="cell-main"><strong>{s.name}</strong>{s.archived && <Badge>Archivé</Badge>}</td>
                <td data-label="Marques"><div className="row">{s.brands.map((b) => <Badge key={b.code}>{b.name}</Badge>)}{!s.brands.length && <span className="faint">Aucune animation</span>}</div></td>
                <td data-label="Shifts" className="num">{s.shifts} · {fmtHM(s.minutes)}</td>
              </tr>))}</tbody>
          </table></div>
        )}
      </Card>
      <Modal open={editor} onClose={() => { setEditor(false); brands.reload(); sites.reload(); }} title="Sites et marques" description={`Modifications à partir de ${monthLabel(month)}`}>
        {editor && <SitesEditor month={month} canEdit={canCatalog} />}
        <div className="row modal-actions"><Button variant="primary" onClick={() => { setEditor(false); brands.reload(); sites.reload(); }}>Fermer</Button></div>
      </Modal>
    </div>
  );
}

function BrandLine({ b, canEdit, onPut, onDraft }: { b: BrandRow; canEdit: boolean; onPut: (body: Record<string, unknown>) => Promise<void>; onDraft: (minutes: number | null) => void }) {
  const [h, setH] = useState(b.budget_minutes === null ? "" : String(b.budget_minutes / 60));
  useEffect(() => setH(b.budget_minutes === null ? "" : String(b.budget_minutes / 60)), [b.budget_minutes]);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const commit = (raw = h) => {
    clearTimeout(timer.current);
    const v = raw.trim();
    if (v === "" && b.budget_minutes !== null) void onPut({ clear_budget: true });
    else if (v !== "" && Number(v) >= 0 && Math.round(Number(v) * 60) !== b.budget_minutes) void onPut({ budget_minutes: Math.round(Number(v) * 60) });
  };
  // enregistrement automatique (petites flèches comprises) : peu après la dernière modification, et immédiatement en quittant le champ
  const change = (v: string) => {
    setH(v); onDraft(v.trim() === "" ? null : Math.round(Number(v) * 60));
    clearTimeout(timer.current); timer.current = setTimeout(() => commit(v), 700);
  };
  const base = b.base_minutes ?? null;
  const [confirmBase, setConfirmBase] = useState(false);
  const toBase = () => { if (base === null) return; clearTimeout(timer.current); setConfirmBase(false); onDraft(base); void onPut({ budget_minutes: base }); };
  return (
    <tr data-active={b.active}>
      <td><input type="checkbox" aria-label={`${b.name} active ce mois`} checked={b.active} disabled={!canEdit} onChange={(e) => onPut({ active: e.target.checked })} /></td>
      <td className="cell-main"><span className="row" style={{ flexWrap: "nowrap" }}><i className="dot" style={{ ["--c" as string]: brandColor(b.code) }} /><strong>{b.name}</strong></span>{b.archived && <Badge>Archivée</Badge>}{!b.active && !b.archived && <Badge>Inactive ce mois</Badge>}</td>
      <td data-label="Budget"><div className="stack" style={{ gap: "var(--sp-1)" }}>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <Input aria-label={`Budget ${b.name} (heures)`} type="number" min={0} step={0.5} value={h} disabled={!canEdit} placeholder="—" onChange={(e) => change(e.target.value)} onBlur={() => commit()} onKeyDown={(e) => { if (e.key === "Enter") commit(); }} style={{ width: "7rem" }} />
          <span className="faint">h</span>
          <Select aria-label={`Nature du budget ${b.name}`} value={b.strict ? "strict" : "soft"} disabled={!canEdit || b.budget_minutes === null} onChange={(e) => onPut({ strict: e.target.value === "strict" })} style={{ width: "auto" }}>
            <option value="strict">Plafond strict</option><option value="soft">Objectif souple</option>
          </Select>
        </div>
        {base !== null ? (
          <span className="help" data-testid={`base-${b.code}`}>{b.budget_minutes === base ? <>Budget de base : {fmtHM(base)}</> : <>Ajusté pour ce mois · budget de base : {fmtHM(base)}{canEdit && <> · <button type="button" className="link-btn" onClick={() => setConfirmBase(true)}>Revenir au budget de base</button></>}</>}
            <Modal open={confirmBase} onClose={() => setConfirmBase(false)} variant="confirm" title={`Revenir au budget de base pour ${b.name} ?`}
              description="Seul le budget de ce mois change ; le budget de base, les autres mois et les plannings existants restent inchangés.">
              <div className="stack" data-testid={`base-confirm-${b.code}`}>
                <p>Le budget de ce mois passera de <strong>{b.budget_minutes === null ? "aucun budget" : fmtHM(b.budget_minutes)}</strong> à <strong>{fmtHM(base)}</strong> (budget de base de {b.name}).</p>
                <div className="row modal-actions"><Button onClick={() => setConfirmBase(false)}>Annuler</Button><Button variant="primary" onClick={toBase}>Remplacer par {fmtHM(base)}</Button></div>
              </div>
            </Modal></span>
        ) : b.budget_minutes === null && !b.archived ? (
          <span className="help warn-text" data-testid={`base-${b.code}`}>Aucun budget de base pour {b.name} : renseignez-le dans « Sites et marques », ou saisissez le budget de ce mois.</span>
        ) : null}
        {b.reference_minutes !== null && <span className="help">Référence {monthLabel(b.reference_month.slice(0, 7))} : {fmtHM(b.reference_minutes)}{canEdit && b.budget_minutes !== b.reference_minutes && <> · <button type="button" className="link-btn" onClick={() => onPut({ budget_minutes: b.reference_minutes })}>Reprendre</button></>}</span>}
      </div></td>
      <td data-label="Besoins"><span className="num">{fmtHM(b.need_mandatory_minutes)}</span> <span className="faint">obligatoires</span>{b.need_optional_minutes > 0 && <> + <span className="num">{fmtHM(b.need_optional_minutes)}</span> <span className="faint">optionnelles</span></>}
        <div className="faint">{b.animation_days} j d&apos;animation · {b.shifts} shifts</div>
        {b.checks.map((c) => <div key={c.text} className={c.level === "warning" ? "error-text" : "help"}>{c.text}</div>)}</td>
      <td data-label="Horaires"><div className="faint">{b.schedules.join(", ") || "Aucun horaire"}</div><div className="row">{b.sites.map((s) => <Badge key={s.code}>{s.name}</Badge>)}</div></td>
    </tr>
  );
}

function StepReview({ pid, goTo }: { pid: string; goTo: (n: number) => void }) {
  const r = useApi<Readiness>(`/periods/${pid}/readiness`);
  if (!r.data) return <div className="skeleton" style={{ height: "16rem" }} aria-hidden="true" />;
  const d = r.data;
  const stat = (k: string, v: React.ReactNode, n?: number) => <div className="surface-2" style={{ padding: "var(--sp-3)" }}><dt className="muted" style={{ fontSize: "var(--text-xs)" }}>{k}</dt><dd className="kpi-value num" style={{ margin: 0, fontSize: "var(--text-xl)" }}>{v}</dd>{n && <button type="button" className="link-btn" onClick={() => goTo(n)}>Modifier</button>}</div>;
  return (
    <div className="stack">
      <Card title={`Récapitulatif — ${d.period.name}`} eyebrow="Vérification avant génération">
        <dl className="recap">
          {stat("Collaborateurs retenus", d.employees.included, 2)}{stat("Marques actives", d.brands.active.length, 4)}{stat("Sites actifs", d.sites.active.length, 4)}
          {stat("Budget horaire total", fmtHM(d.budget_minutes), 4)}{stat("Shifts à couvrir", d.shifts)}{stat("Dimanches", `${d.sundays} · ${d.sunday_shifts} shifts`)}
          {stat("Jours d'indisponibilité", d.unavailable_days, 3)}{stat("Contraintes particulières", d.constraints.max_days + d.constraints.sunday_quotas + d.constraints.strict_time_prefs, 3)}
        </dl>
        <div className="stack" style={{ marginTop: "var(--sp-3)" }}>
          {d.employees.excluded.length > 0 && <p className="help"><strong>Exclus ce mois :</strong> {d.employees.excluded.join(", ")}</p>}
          {d.employees.contract_ended.length > 0 && <p className="help"><strong>Contrat terminé :</strong> {d.employees.contract_ended.join(", ")}</p>}
          {d.brands.inactive.length > 0 && <p className="help"><strong>Marques inactives :</strong> {d.brands.inactive.join(", ")}</p>}
          {d.sites.inactive.length > 0 && <p className="help"><strong>Sites inactifs :</strong> {d.sites.inactive.join(", ")}</p>}
          {Object.keys(d.unavailabilities).length > 0 && <p className="help"><strong>Indisponibilités :</strong> {Object.entries(d.unavailabilities).map(([n, k]) => `${n} (${k} j)`).join(", ")}</p>}
          <p className="help"><strong>Contraintes :</strong> {d.constraints.max_days} limite(s) de jours dont {d.constraints.max_days_exceptions} exception(s) du mois · {d.constraints.sunday_quotas} quota(s) de dimanches ({d.sundays_reserved} réservés) · {d.constraints.strict_time_prefs} préférence(s) horaire(s) stricte(s).</p>
        </div>
      </Card>
      <Card title={d.issues.length ? `${d.issues.length} point(s) à vérifier` : "Aucune incohérence détectée"}>
        {d.issues.length === 0 ? <p className="muted"><Icon name="check" size={14} /> Les données du mois sont cohérentes. Vous pouvez générer le planning.</p> : (
          <ul className="review-list">{d.issues.map((i) => <li key={i.text}><span>{i.text}</span> {i.level === "blocking" ? <Badge tone="bad">Bloquant</Badge> : i.level === "warning" ? <Badge tone="warn">À vérifier</Badge> : <Badge tone="info">Information</Badge>}</li>)}</ul>
        )}
      </Card>
    </div>
  );
}

function StepGenerate({ pid, period, onDone, onOpen }: { pid: string; period?: Period & PeriodRow; onDone: () => void; onOpen: () => void }) {
  const toast = useToast();
  const ready = useApi<Readiness>(`/periods/${pid}/readiness`);
  const [run, setRun] = useState<RunView | null>(null);
  const [confirm, setConfirm] = useState(false); const [limit, setLimit] = useState(30);
  const [paramsMode, setParamsMode] = useState<ParamsMode>(null);
  // enregistré = le serveur l'a dit (résultat d'enregistrement) ; repli pour les calculs plus anciens sans ce résultat
  const saved = (r: RunView | null) => r?.status === "termine" && (r.save ? r.save.outcome === "replaced" : r.result_status !== "infaisable" && r.result_status !== "interrompu");
  const key = useRef(crypto.randomUUID());
  useEffect(() => {
    if (!run || ["termine", "annule", "erreur"].includes(run.status)) return;
    const id = setInterval(async () => setRun(await api(`/runs/${run.id}`)), 1000); return () => clearInterval(id);
  }, [run]);
  useEffect(() => { if (saved(run)) { void api(`/periods/${pid}/wizard`, { method: "PATCH", json: { step: null } }); onDone(); toast.push("Planning généré et ajouté à l'historique.", "ok"); } }, [run?.status]); // eslint-disable-line react-hooks/exhaustive-deps
  const hasPlan = (period?.assignments ?? 0) > 0;
  async function go() {
    setConfirm(false);
    try { const r = await api<{ run_id: string }>(`/periods/${pid}/runs`, { method: "POST", json: { time_limit_s: limit, confirm_replace: true, params: paramsMode ?? "frozen" }, headers: { "Idempotency-Key": key.current } }); key.current = crypto.randomUUID(); setRun(await api(`/runs/${r.run_id}`)); }
    catch (e) { toast.push(err(e), "bad"); }
  }
  const running = run && !["termine", "annule", "erreur"].includes(run.status);
  const blocking = ready.data?.issues.filter((i) => i.level === "blocking") ?? [];
  return (
    <Card title="Génération automatique">
      <div className="stack">
        <p>Le moteur utilise uniquement l&apos;effectif, les marques, les sites, les budgets et les paramètres de ce mois, avec les pondérations enregistrées (<a href="/settings" style={{ textDecoration: "underline" }}>Paramètres</a>) et les affectations verrouillées.</p>
        {blocking.length > 0 && <Callout kind="bad" title="Génération impossible pour l'instant">{blocking.map((b) => <p key={b.text} style={{ margin: 0 }}>{b.text}</p>)}</Callout>}
        {hasPlan && !running && <ParamsChoice periodId={pid} value={paramsMode} onChange={setParamsMode} />}
        <TimeLimitField value={limit} onChange={setLimit} />
        {!run && <div><Button variant="primary" icon="sparkles" disabled={blocking.length > 0 || (hasPlan && paramsMode === null)} onClick={() => (hasPlan ? setConfirm(true) : go())}>Générer automatiquement le planning</Button></div>}
        {running && <RunProgress run={run!} limit={limit} />}
        {run && (run.status === "erreur" || run.status === "annule" || (run.status === "termine" && !saved(run))) && <RunFailure runId={run.id} status={run.status} save={run.save} timing={run.timing} />}
        {saved(run) && <SaveOutcome save={run!.save} timing={run!.timing} proof={run!.proof} />}
        {saved(run) && <Callout kind="ok" title={`Planning de ${period?.name ?? "ce mois"} généré (${String(run?.result_status ?? "").replace(/_/g, " ")})`}>
          <div className="row"><Button variant="primary" icon="calendar" onClick={onOpen}>Ouvrir le planning</Button><a className="btn" href="/generate">Voir le diagnostic détaillé</a></div></Callout>}
        {run && !running && !saved(run) && <div><Button icon="sparkles" disabled={blocking.length > 0} onClick={() => { setRun(null); }}>Modifier et relancer</Button></div>}
      </div>
      <Modal open={confirm} onClose={() => setConfirm(false)} title="Un planning existe déjà pour ce mois" description="Confirmez avant de le recalculer." variant="confirm">
        <div className="stack"><p>Les affectations <strong>verrouillées</strong> (dont les ajouts et transferts manuels) sont conservées ; les autres seront recalculées avec {paramsMode === "current" ? "les paramètres actuels" : "les paramètres de ce planning"}.</p>
          <div className="row modal-actions"><Button onClick={() => setConfirm(false)}>Annuler</Button><Button variant="primary" onClick={go}>Confirmer et générer</Button></div></div>
      </Modal>
    </Card>
  );
}
