"use client";
import { useEffect, useRef, useState } from "react";
import { Card, Page } from "@/components/Shell";
import { usePeriod } from "@/components/hooks";
import { api } from "@/lib/api";
import { Assignment, diffSchedules, hours } from "@/lib/schedule";
import { t } from "@/lib/i18n";

const WEIGHT_LABELS: Record<string, string> = { coverage: "Couverture", budget: "Budgets", reinforce: "Renforts", preference: "Préférences", fairness: "Équité", overtime: "Heures supplémentaires", site_change: "Changements de site", balance: "Équilibre ouvertures/fermetures/week-ends", fatigue: "Enchaînements fatigants", family: "Préférences familiales", stagger: "Décalage cosmétique", rest_days: "Jours de repos", stability: "Stabilité" };

export default function Generate() {
  const { period } = usePeriod();
  const [step, setStep] = useState(1);
  const [partial, setPartial] = useState(false); const [limit, setLimit] = useState(30); const [weights, setWeights] = useState<Record<string, number>>({});
  const [run, setRun] = useState<any>(null); const [diag, setDiag] = useState<any>(null);
  const [diff, setDiff] = useState<ReturnType<typeof diffSchedules> | null>(null);
  const before = useRef<Assignment[]>([]);
  const key = useRef(crypto.randomUUID());

  useEffect(() => {
    if (!run || ["termine", "annule", "erreur"].includes(run.status)) return;
    const id = setInterval(async () => setRun(await api(`/runs/${run.id}`)), 1000); return () => clearInterval(id);
  }, [run]);
  useEffect(() => {
    if (run?.status === "termine") (async () => {
      setDiag((await api(`/runs/${run.id}/diagnostic`)).report);
      const after = (await api(`/periods/${period!.id}/schedule`)).assignments; setDiff(diffSchedules(before.current, after)); setStep(4);
    })();
  }, [run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start() {
    before.current = (await api(`/periods/${period!.id}/schedule`)).assignments;
    const r = await api<{ run_id: string }>(`/periods/${period!.id}/${partial ? "reoptimize" : "runs"}`, { method: "POST", json: { time_limit_s: limit, weights, kind: partial ? "partial" : "full" }, headers: { "Idempotency-Key": key.current } });
    key.current = crypto.randomUUID(); setRun(await api(`/runs/${r.run_id}`)); setStep(3);
  }
  return (
    <Page>
      <h1 className="mb-3 text-2xl font-semibold">{t("nav.generate")}</h1>
      <ol className="mb-3 flex gap-2 text-sm" aria-label="Étapes">{["Vérification", "Paramètres", "Calcul", "Résultat"].map((l, i) => <li key={l} aria-current={step === i + 1 ? "step" : undefined} className={`surface px-3 py-1 ${step === i + 1 ? "font-semibold" : "muted"}`}>{i + 1}. {l}</li>)}</ol>
      {step === 1 && <Card title="Avant de générer">
        <p className="tag-warn mb-2 text-sm">Contrats et disponibilités incomplets : le résultat sera une <strong>{t("exploratory")}</strong>, jamais publiable. Lindt et Toblerone (128 h) ne seront pas planifiés sans jours ni horaires.</p>
        <button className="btn btn-primary" onClick={() => setStep(2)}>Continuer en simulation exploratoire</button></Card>}
      {step === 2 && <Card title="Paramètres d'optimisation">
        <label className="mb-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={partial} onChange={(e) => setPartial(e.target.checked)} /> Réoptimisation partielle (les affectations verrouillées sont conservées)</label>
        <label className="mb-3 block text-sm">Durée maximale (s)<input type="number" min={5} max={600} value={limit} onChange={(e) => setLimit(+e.target.value)} className="input mt-1 w-32" /></label>
        <fieldset className="grid gap-2 sm:grid-cols-3"><legend className="mb-1 text-sm font-medium">Poids (laisser vide = valeur par défaut)</legend>
          {Object.entries(WEIGHT_LABELS).map(([k, l]) => <label key={k} className="text-sm">{l}<input type="number" min={0} className="input mt-1" onChange={(e) => setWeights({ ...weights, [k]: +e.target.value })} /></label>)}</fieldset>
        <button className="btn btn-primary mt-3" onClick={start} disabled={!period}>Lancer</button></Card>}
      {step === 3 && <Card title="Calcul en cours"><p role="status">Statut : {run?.status}</p>
        {run && !["termine", "annule", "erreur"].includes(run.status) && <button className="btn mt-2" onClick={() => api(`/runs/${run.id}/cancel`, { method: "POST" })}>Annuler l'exécution</button>}</Card>}
      {step === 4 && diag && <>
        <Card title={`Résultat : ${diag.status}`}>
          <p className="tag-warn text-sm">{diag.mode === "simulation_exploratoire" ? t("exploratory") : "Validable"} · {diag.duration_s} s</p>
          <h3 className="mt-3 font-medium">Budgets</h3>
          <table className="grid"><tbody>{diag.budgets.map((b: any) => <tr key={b.brand}><td>{b.brand}</td><td>{hours(b.planned_minutes)} / {hours(b.target_minutes)}</td><td>{b.requirements_defined ? "" : <span className="tag-warn">{t("to_fill")}</span>}</td></tr>)}</tbody></table>
          <h3 className="mt-3 font-medium">Objectifs et poids utilisés</h3>
          <table className="grid"><tbody>{Object.entries(diag.objective).map(([k, v]) => <tr key={k}><td>{WEIGHT_LABELS[k] ?? k}</td><td>{String(v)}</td><td className="muted">poids {diag.weights_used[k]}</td></tr>)}</tbody></table>
          <h3 className="mt-3 font-medium">Préférences</h3>
          <table className="grid"><tbody>{Object.entries<any>(diag.preferences).map(([k, v]) => <tr key={k}><td>{k}</td><td className="tag-ok">{v.satisfaites} ✓</td><td className="tag-warn">{v.non_satisfaites} ✗</td></tr>)}</tbody></table>
        </Card>
        <Card title="Diagnostic et données manquantes"><ul className="space-y-2 text-sm">{[...diag.diagnostics, ...diag.missing_data].map((i: any, n: number) =>
          <li key={n} className="surface p-2"><strong className={i.severity === "blocking" ? "tag-bad" : i.severity === "warning" ? "tag-warn" : ""}>{i.code}</strong> — {i.message}
            {i.suggestions?.length > 0 && <ul className="muted list-disc pl-5">{i.suggestions.map((s: string) => <li key={s}>{s}</li>)}</ul>}</li>)}</ul></Card>
        {diff && <Card title="Comparaison avant / après"><p className="text-sm">{diff.changed.length} affectation(s) modifiée(s), {diff.added.length} ajoutée(s), {diff.removed.length} retirée(s).</p>
          <ul className="muted text-sm">{diff.changed.slice(0, 10).map((c) => <li key={c.slot}>{c.slot} : {c.from} → {c.to}</li>)}</ul></Card>}
      </>}
    </Page>
  );
}
