"use client";
import { useEffect, useRef, useState } from "react";
import { usePeriod } from "@/components/hooks";
import { Badge, Button, Callout, Card, Field, Input, PageHead, Progress } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { brandColor } from "@/lib/brand";
import { budgetProgress } from "@/lib/metrics";
import { Assignment, diffSchedules, fmtHM } from "@/lib/schedule";
import { t } from "@/lib/i18n";

const WEIGHT_LABELS: Record<string, string> = { coverage: "Couverture", budget: "Budgets", reinforce: "Renforts", preference: "Préférences", fairness: "Équité", overtime: "Heures supplémentaires", site_change: "Changements de site", balance: "Équilibre ouvertures/fermetures/week-ends", fatigue: "Enchaînements fatigants", family: "Préférences familiales", stagger: "Décalage cosmétique", rest_days: "Jours de repos", stability: "Stabilité" };
const STEPS = ["Vérification", "Paramètres", "Calcul", "Résultat"];
const SEV: Record<string, "bad" | "warn" | "info"> = { blocking: "bad", warning: "warn", info: "info" };

export default function Generate() {
  const { period } = usePeriod(); const toast = useToast();
  const [step, setStep] = useState(1);
  const [partial, setPartial] = useState(false); const [limit, setLimit] = useState(30); const [weights, setWeights] = useState<Record<string, number>>({});
  const [run, setRun] = useState<any>(null); const [diag, setDiag] = useState<any>(null);
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
      const after = (await api(`/periods/${period!.id}/schedule`)).assignments; setDiff(diffSchedules(before.current, after)); setStep(4);
      toast.push("Génération terminée.", "ok");
    })();
    if (run?.status === "annule" || run?.status === "erreur") { toast.push(run.status === "annule" ? "Exécution annulée." : "L'exécution a échoué.", run.status === "annule" ? "warn" : "bad"); setStep(2); }
  }, [run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start() {
    try {
      before.current = (await api(`/periods/${period!.id}/schedule`)).assignments;
      const r = await api<{ run_id: string }>(`/periods/${period!.id}/${partial ? "reoptimize" : "runs"}`, { method: "POST", json: { time_limit_s: limit, weights, kind: partial ? "partial" : "full" }, headers: { "Idempotency-Key": key.current } });
      key.current = crypto.randomUUID(); setRun(await api(`/runs/${r.run_id}`)); setStep(3);
    } catch (e: any) { toast.push(String(e.message), "bad"); }
  }
  const running = run && !["termine", "annule", "erreur"].includes(run.status);
  return (
    <>
      <PageHead eyebrow={period?.name} title={t("nav.generate")} />
      <ol className="stepper" aria-label="Étapes">
        {STEPS.map((l, i) => <li key={l} className="step" data-done={i + 1 < step || undefined} aria-current={step === i + 1 ? "step" : undefined}><i>{i + 1 < step ? <Icon name="check" size={12} /> : i + 1}</i>{l}</li>)}
      </ol>

      {step === 1 && (
        <Card title="Avant de générer">
          <div className="stack">
            <Callout kind="warn" title="Simulation exploratoire">Contrats et disponibilités incomplets : le résultat sera une proposition <strong>non validable</strong>, jamais publiable. Lindt et Toblerone (128 h) ne seront pas planifiés sans jours ni horaires.</Callout>
            <Callout kind="info" title="Hypothèses non validées">Les horaires de Cailler et de Nuxe/Cellcosmet sont supposés (paramétrables) ; seules deux règles légales sont exécutées, à titre de référence.</Callout>
            <div><Button variant="primary" icon="sparkles" onClick={() => setStep(2)}>Continuer en simulation exploratoire</Button></div>
          </div>
        </Card>
      )}
      {step === 2 && (
        <Card title="Paramètres d'optimisation">
          <div className="stack">
            <label className="row"><input type="checkbox" checked={partial} onChange={(e) => setPartial(e.target.checked)} /> Réoptimisation partielle <span className="help">— les affectations verrouillées sont conservées</span></label>
            <Field label="Durée maximale (secondes)">{(p) => <Input {...p} type="number" min={5} max={600} value={limit} onChange={(e) => setLimit(+e.target.value)} style={{ width: "10rem" }} />}</Field>
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="h2" style={{ marginBottom: "var(--sp-2)" }}>Poids <span className="help">(vide = valeur par défaut)</span></legend>
              <div className="toolbar">{Object.entries(WEIGHT_LABELS).map(([k, l]) => <Field key={k} label={l}>{(p) => <Input {...p} type="number" min={0} onChange={(e) => setWeights({ ...weights, [k]: +e.target.value })} />}</Field>)}</div>
            </fieldset>
            <div className="row"><Button onClick={() => setStep(1)}>Retour</Button><Button variant="primary" icon="sparkles" onClick={start} disabled={!period}>Lancer le calcul</Button></div>
          </div>
        </Card>
      )}
      {step === 3 && (
        <Card title="Calcul en cours">
          <div className="stack" role="status" aria-live="polite">
            <p>Statut : <Badge tone={running ? "info" : "neutral"}>{run?.status ?? "…"}</Badge></p>
            <div className="progress" aria-hidden="true"><span style={{ ["--value" as string]: 100, animation: "shimmer 1.4s linear infinite", backgroundImage: "linear-gradient(100deg, var(--accent) 30%, var(--brand-5) 50%, var(--accent) 70%)", backgroundSize: "200% 100%" }} /></div>
            <p className="help">Le solveur tourne en arrière-plan ; vous pouvez l&apos;interrompre.</p>
            {running && <div><Button onClick={() => api(`/runs/${run.id}/cancel`, { method: "POST" })}>Annuler l&apos;exécution</Button></div>}
          </div>
        </Card>
      )}
      {step === 4 && diag && (
        <>
          <Card title={`Résultat : ${String(diag.status).replace(/_/g, " ")}`} eyebrow={`${diag.duration_s} s`} actions={<Badge tone={diag.mode === "simulation_exploratoire" ? "warn" : "ok"} icon={diag.mode === "simulation_exploratoire" ? "alert" : "check"}>{diag.mode === "simulation_exploratoire" ? t("exploratory") : "Validable"}</Badge>}>
            <h3 className="h2" style={{ marginBottom: "var(--sp-2)" }}>Budgets</h3>
            <div className="stack">{diag.budgets.map((b: any) => (
              <div key={b.brand} className="bar-row"><span className="row"><i className="dot" style={{ ["--c" as string]: brandColor(b.brand) }} />{b.brand}</span>
                <Progress value={budgetProgress(b.planned_minutes, b.target_minutes)} label={`${b.brand} planifié`} color={brandColor(b.brand)} />
                <span className="num">{fmtHM(b.planned_minutes)} / {fmtHM(b.target_minutes)} {!b.requirements_defined && <Badge tone="warn">{t("to_fill")}</Badge>}</span></div>))}</div>
          </Card>
          <div className="grid-2">
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
