"use client";
import { useEffect, useRef, useState } from "react";
import { useApi, usePeriod } from "@/components/hooks";
import { Modal } from "@/components/ui/Modal";
import { Badge, Button, Callout, Card, Field, Input, PageHead, Progress } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { brandColor } from "@/lib/brand";
import { budgetProgress } from "@/lib/metrics";
import { Assignment, diffSchedules, fmtHM } from "@/lib/schedule";
import { t } from "@/lib/i18n";
import { MonthSwitcher } from "@/components/MonthSwitcher";
import { MonthNeeds, type MonthCalendar } from "@/components/planning/MonthNeeds";
import { copyPreviousBudgets } from "@/lib/budgetCopy";
import { invalidate } from "@/lib/invalidate";
import { monthLabel, parseMonthKey } from "@/lib/months";
import { GenerationSummary } from "@/components/planning/GenerationSummary";
import { ParamsChoice, RunFailure, RunProgress, SaveOutcome, TimeLimitField, type ParamsMode, type RunTiming, type SaveInfo } from "@/components/planning/RunStatus";

const WEIGHT_LABELS: Record<string, string> = { coverage: "Couverture", budget: "Budgets", reinforce: "Renforts", preference: "Préférences", fairness: "Équité", overtime: "Heures supplémentaires", site_change: "Changements de site", balance: "Équilibre ouvertures/fermetures/week-ends", fatigue: "Enchaînements fatigants", family: "Relations entre collaborateurs", stagger: "Décalage cosmétique", rest_days: "Jours de repos", stability: "Stabilité", time_pref: "Préférence matin/middle/soir", secondary: "Marques secondaires", budget_over: "Dépassement de budget souple", sunday_quota: "Objectif exact de dimanches", individual: "Priorité individuelle", sunday_balance: "Équilibrage des dimanches", alternation: "Alternance matin/soir", days_balance: "Équilibrage des jours", cost: "Coût estimé" };
const STEPS = ["Vérification", "Paramètres", "Calcul", "Résultat"];
const SEV: Record<string, "bad" | "warn" | "info"> = { blocking: "bad", warning: "warn", info: "info" };

export default function Generate() {
  const { period, month, setMonth, ensure } = usePeriod(); const toast = useToast();
  const ym = parseMonthKey(month);
  const cal = useApi<MonthCalendar>(`/calendar?year=${ym.y}&month=${ym.m}`);
  const [runPeriod, setRunPeriod] = useState("");
  async function copyBudgets() {
    try { const n = await copyPreviousBudgets(month); toast.push(n ? `${n} budget(s) copié(s) depuis le mois précédent.` : "Rien à copier : aucun budget le mois précédent ou déjà saisis.", n ? "ok" : "info"); cal.reload(); invalidate(); }
    catch (e: unknown) { toast.push(e instanceof Error ? e.message : "Copie impossible", "bad"); }
  }
  const [step, setStep] = useState(1);
  const [confirming, setConfirming] = useState(false);
  const compat = useApi<{ has_plan: boolean; locked: number; unlocked: number; hard: string[]; soft: unknown[] }>(period ? `/periods/${period.id}/compatibility` : null);
  const [partial, setPartial] = useState(false); const [limit, setLimit] = useState(30); const [weights, setWeights] = useState<Record<string, number>>({});
  const [run, setRun] = useState<any>(null); const [diag, setDiag] = useState<any>(null);
  const [paramsMode, setParamsMode] = useState<ParamsMode>(null); const [failed, setFailed] = useState<{ id: string; status: string; save?: SaveInfo | null; timing?: RunTiming | null } | null>(null);
  const [diff, setDiff] = useState<ReturnType<typeof diffSchedules> | null>(null);
  const before = useRef<Assignment[]>([]);
  const key = useRef("");
  useEffect(() => { key.current = crypto.randomUUID(); }, []);

  useEffect(() => {
    if (!run || ["termine", "annule", "erreur"].includes(run.status)) return;
    const id = setInterval(async () => setRun(await api(`/runs/${run.id}`)), 1000); return () => clearInterval(id);
  }, [run]);
  useEffect(() => {
    if (run?.status === "termine") (async () => {
      setDiag((await api(`/runs/${run.id}/diagnostic`)).report);
      const after = (await api(`/periods/${runPeriod || run.period_id}/schedule`)).assignments; setDiff(diffSchedules(before.current, after)); setStep(4);
      toast.push(run.save?.outcome === "kept_previous" ? "Calcul terminé : le planning précédent est conservé." : "Génération terminée.", run.save?.outcome === "kept_previous" ? "warn" : "ok");
    })();
    if (run?.status === "annule" || run?.status === "erreur") { toast.push(run.status === "annule" ? "Exécution annulée." : "L'exécution a échoué.", run.status === "annule" ? "warn" : "bad"); setFailed({ id: run.id, status: run.status, save: run.save, timing: run.timing }); setStep(2); }
  }, [run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start() {
    try {
      const p = period ?? await ensure(); // le planning du mois est créé s'il n'existe pas (les autres mois ne sont jamais touchés)
      setRunPeriod(p.id);
      before.current = (await api(`/periods/${p.id}/schedule`)).assignments;
      setFailed(null);
      const r = await api<{ run_id: string }>(`/periods/${p.id}/${partial ? "reoptimize" : "runs"}`, { method: "POST", json: { time_limit_s: limit, weights, kind: partial ? "partial" : "full", confirm_replace: true, params: paramsMode ?? "frozen" }, headers: { "Idempotency-Key": key.current } }); // la confirmation est demandée ci-dessous quand un planning existe
      key.current = crypto.randomUUID(); setRun(await api(`/runs/${r.run_id}`)); setStep(3);
    } catch (e: any) { toast.push(String(e.message), "bad"); }
  }
  const running = run && !["termine", "annule", "erreur"].includes(run.status);
  return (
    <>
      <PageHead eyebrow={monthLabel(month)} title={t("nav.generate")}><a className="btn btn-primary" href="/plannings/new"><Icon name="plus" size={16} />Générer un nouveau planning</a><MonthSwitcher month={month} onChange={(m) => { setMonth(m); setStep(1); setRun(null); setParamsMode(null); }} /></PageHead>
      {step <= 2 && cal.data && <MonthNeeds cal={cal.data} actions={cal.data.budgets_missing ? <Button size="sm" onClick={copyBudgets}>Copier les budgets du mois précédent</Button> : undefined} />}
      <ol className="stepper" aria-label="Étapes">
        {STEPS.map((l, i) => <li key={l} className="step" data-done={i + 1 < step || undefined} aria-current={step === i + 1 ? "step" : undefined}><i>{i + 1 < step ? <Icon name="check" size={12} /> : i + 1}</i>{l}</li>)}
      </ol>

      {step === 1 && (
        <Card title="Avant de générer">
          <div className="stack">
            <Callout kind="warn" title="Vérifiez les données avant de générer">Tant que des contrats manquent, le résultat reste une proposition <strong>non validable</strong> et non publiable. Une marque dont le budget n&apos;a ni jours ni horaires définis n&apos;est pas planifiée.</Callout>
            <Callout kind="info" title="Hypothèses et règles légales">Les horaires marqués comme hypothèses restent à confirmer (voir Alertes). Les règles légales exécutées et leur état de validation sont dans <a href="/rules" style={{ textDecoration: "underline" }}>Règles</a>.</Callout>
            <div className="row"><Button variant="primary" icon="sparkles" onClick={() => setStep(2)}>Continuer</Button></div>
          </div>
        </Card>
      )}
      {step === 2 && (
        <Card title="Paramètres d'optimisation">
          <div className="stack">
            <label className="row"><input type="checkbox" checked={partial} onChange={(e) => setPartial(e.target.checked)} /> Réoptimisation partielle <span className="help">— les affectations verrouillées sont conservées</span></label>
            {failed && <RunFailure runId={failed.id} status={failed.status} save={failed.save} timing={failed.timing} />}
            <ParamsChoice periodId={period?.id ?? null} value={paramsMode} onChange={setParamsMode} />
            <TimeLimitField value={limit} onChange={setLimit} width="10rem" />
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="h2" style={{ marginBottom: "var(--sp-2)" }}>Ajustement exceptionnel des poids <span className="help">(vide = pondération enregistrée dans <a href="/settings" style={{ textDecoration: "underline" }}>Paramètres</a>)</span></legend>
              <div className="toolbar">{Object.entries(WEIGHT_LABELS).map(([k, l]) => <Field key={k} label={l}>{(p) => <Input {...p} type="number" min={0} onChange={(e) => setWeights({ ...weights, [k]: +e.target.value })} />}</Field>)}</div>
            </fieldset>
            <div className="row"><Button onClick={() => setStep(1)}>Retour</Button><Button variant="primary" icon="sparkles" disabled={paramsMode === null} onClick={() => (compat.data?.has_plan ? setConfirming(true) : start())}>Générer automatiquement le planning</Button>{paramsMode === null && <span className="help">Choisissez d&apos;abord les paramètres à utiliser.</span>}</div>
          </div>
        </Card>
      )}
      <Modal open={confirming} onClose={() => setConfirming(false)} title="Un planning existe déjà pour ce mois" description="Ouvrez-le, ou confirmez avant de le recalculer.">
        <div className="stack">
          {(period?.status === "validated" || period?.status === "published") && <Callout kind="warn" title={`Planning ${period.status_label?.toLowerCase()}`}>La version {period.status === "published" ? "publiée" : "validée"} reste conservée, mais le planning en cours sera remplacé et devra être de nouveau validé et publié.</Callout>}
          <p><strong>{compat.data?.locked ?? 0}</strong> affectation(s) verrouillée(s) ou ajoutée(s) à la main resteront inchangées.</p>
          <p><strong>{compat.data?.unlocked ?? 0}</strong> affectation(s) non verrouillée(s) seront recalculées avec {paramsMode === "current" ? "les paramètres actuels" : "les paramètres de ce planning"}{partial ? " (réoptimisation partielle : le moins de changements possible)" : ""}.</p>
          {!!(compat.data && (compat.data.hard.length || compat.data.soft.length)) && <p className="help">{compat.data!.hard.length + compat.data!.soft.length} incompatibilité(s) actuelle(s) avec les paramètres seront traitées. Un comparatif avant/après sera affiché.</p>}
          <div className="row modal-actions"><Button onClick={() => setConfirming(false)}>Annuler</Button><a className="btn" href="/planning"><Icon name="calendar" size={16} />Ouvrir le planning existant</a><Button variant="primary" onClick={() => { setConfirming(false); void start(); }}>Confirmer et lancer</Button></div>
        </div>
      </Modal>
      {step === 3 && (
        <Card title="Calcul en cours">
          <div className="stack" role="status" aria-live="polite">
            {run && <RunProgress run={run} limit={limit} />}
            <p className="help">Le solveur tourne en arrière-plan ; vous pouvez l&apos;interrompre.</p>
            {running && <div><Button onClick={() => api(`/runs/${run.id}/cancel`, { method: "POST" })}>Annuler l&apos;exécution</Button></div>}
          </div>
        </Card>
      )}
      {step === 4 && diag && (
        <>
          {run && diag.save?.outcome === "replaced" && <GenerationSummary runId={run.id} />}
          {diag.save ? <SaveOutcome save={diag.save} timing={diag.timing} proof={{ proved: !!diag.proved_optimal, time_limit_s: diag.timing?.time_limit_s ?? null }} /> : (diag.status === "infaisable" || (diag.status === "interrompu" && !diag.verification?.executed)) && (
            <Callout kind="bad" title="Aucun planning enregistré">{diag.status === "infaisable" ? "Les contraintes obligatoires ne permettent aucun planning : voir le diagnostic ci-dessous." : "Aucune solution trouvée dans la durée maximale : augmentez-la ou allégez les contraintes."} Le planning existant n&apos;a pas été modifié.</Callout>)}
          {diag.params_used && <p className="help">Paramètres utilisés : {diag.params_used.mode === "frozen" ? "ceux conservés par ce planning" : "paramètres actuels (désormais conservés par ce planning)"}{diag.params_used.monthly_cap_minutes ? ` · plafond mensuel ${Math.round(diag.params_used.monthly_cap_minutes / 60)} h par collaborateur` : ""}.</p>}
          <Card title={`Résultat : ${String(diag.status).replace(/_/g, " ")}`} eyebrow={diag.timing?.total_s !== undefined ? `${String(diag.timing.total_s).replace(".", ",")} s au total · ${String(diag.duration_s).replace(".", ",")} s de calcul du moteur` : `${diag.duration_s} s`} actions={<div className="row">{diag.verification?.executed && <Badge tone={diag.hard_violations?.length ? "bad" : "ok"} icon={diag.hard_violations?.length ? "alert" : "check"} data-testid="verification">{diag.hard_violations?.length ? `Vérificateur : ${diag.hard_violations.length} violation(s), planning refusé` : "Vérificateur indépendant : aucune violation"}</Badge>}<Badge tone={diag.mode === "simulation_exploratoire" ? "warn" : "ok"} icon={diag.mode === "simulation_exploratoire" ? "alert" : "check"}>{diag.mode === "simulation_exploratoire" ? t("exploratory") : "Validable"}</Badge></div>}>
            <h3 className="h2" style={{ marginBottom: "var(--sp-2)" }}>Budgets</h3>
            <div className="stack">{diag.budgets.map((b: any) => (
              <div key={b.brand} className="bar-row"><span className="row"><i className="dot" style={{ ["--c" as string]: brandColor(b.brand) }} />{b.brand}</span>
                <Progress value={budgetProgress(b.planned_minutes, b.target_minutes)} label={`${b.brand} planifié`} color={brandColor(b.brand)} />
                <span className="num">{fmtHM(b.planned_minutes)} / {fmtHM(b.target_minutes)} {!b.requirements_defined && <Badge tone="warn">{t("to_fill")}</Badge>}</span></div>))}</div>
          </Card>
          <div className="grid-2">
            {diag.levels?.length > 0 && <Card title="Optimisation hiérarchisée" eyebrow={diag.model ? `${diag.model.decision_variables.toLocaleString("fr-CH")} variables de décision · ${diag.model.filtered_out.toLocaleString("fr-CH")} affectations impossibles écartées d'emblée` : "Chaque niveau est figé avant le suivant"}><div className="table-wrap"><table className="table"><thead><tr><th>Niveau</th><th>Coût</th><th>Preuve</th></tr></thead><tbody>{diag.levels.map((l: any) => <tr key={l.level}><td>{({ couverture: "1. Couverture des postes", engagements: "2. Engagements (contrats, quotas, budgets souples)", optimisation: "3. Équité, préférences et autres critères", pondere: "Somme pondérée" } as Record<string, string>)[l.level] ?? l.level}</td><td className="num">{l.value ?? "—"}</td><td>{l.proved_optimal ? <Badge tone="ok" icon="check">Optimum prouvé</Badge> : <Badge tone="info">Non prouvé</Badge>}</td></tr>)}</tbody></table></div></Card>}
            <Card title="Objectifs et poids utilisés"><div className="table-wrap"><table className="table"><thead><tr><th>Terme</th><th>Coût</th><th>Poids</th></tr></thead><tbody>{Object.entries(diag.objective).map(([k, v]) => <tr key={k}><td>{WEIGHT_LABELS[k] ?? k}</td><td className="num">{String(v)}</td><td className="num">{diag.weights_used[k]}</td></tr>)}</tbody></table></div></Card>
            <Card title="Préférences"><div className="table-wrap"><table className="table"><thead><tr><th>Préférence</th><th>Respectées</th><th>Non respectées</th></tr></thead><tbody>{Object.entries<any>(diag.preferences).map(([k, v]) => <tr key={k}><td>{k}</td><td className="num" style={{ color: "var(--ok)" }}>{v.satisfaites}</td><td className="num" style={{ color: "var(--warn)" }}>{v.non_satisfaites}</td></tr>)}</tbody></table></div></Card>
          </div>
          <Card title="Diagnostic et données manquantes">
            <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>{[...diag.diagnostics, ...diag.missing_data].map((i: any, n: number) => (
              <li key={n} className="surface" style={{ padding: "var(--sp-3) var(--sp-4)" }}>
                <div className="row"><Badge tone={SEV[i.severity] ?? "neutral"}>{i.severity}</Badge><strong>{i.code}</strong></div>
                <p style={{ margin: "var(--sp-2) 0" }}>{i.message}</p>
                {i.suggestions?.length > 0 && <ul className="muted" style={{ margin: 0, paddingLeft: "1.1rem" }}>{i.suggestions.map((s: string) => <li key={s}>{s}</li>)}</ul>}
              </li>))}</ul>
          </Card>
          {diff && (
            <Card title="Comparaison avant / après">
              <div className="row"><Badge tone="accent">{diff.changed.length} modifiée(s)</Badge><Badge tone="ok">{diff.added.length} ajoutée(s)</Badge><Badge tone="bad">{diff.removed.length} retirée(s)</Badge></div>
              {diff.changed.length > 0 && <ul className="muted" style={{ paddingLeft: "1.1rem" }}>{diff.changed.slice(0, 10).map((c) => <li key={c.slot}>{c.slot} : {c.from} → <strong style={{ color: "var(--fg)" }}>{c.to}</strong></li>)}</ul>}
            </Card>
          )}
          <div className="row"><Button onClick={() => setStep(2)} icon="sparkles">Relancer</Button><a className="btn btn-primary" href="/planning"><Icon name="calendar" size={16} />Voir le planning</a></div>
        </>
      )}
    </>
  );
}
