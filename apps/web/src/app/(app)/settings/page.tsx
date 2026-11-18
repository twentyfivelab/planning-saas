"use client";
import { useEffect, useRef, useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi } from "@/components/hooks";
import { Modal } from "@/components/ui/Modal";
import { Badge, Button, Callout, Card, ErrorState, Field, Input, PageHead, SkeletonCard } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { errText } from "@/lib/wfm";

type Criterion = { key: string; label: string; description: string; default: number; value: number; engine: Record<string, number> };
type Advanced = { key: string; label: string; description: string; default: number; value: number; max: number };
type Last = { period: string; status: string; at: string; objective: Record<string, number>; by_criterion: Record<string, number>; weights_used: Record<string, number> } | null;
type View = { hierarchical: boolean; criteria: Criterion[]; advanced: Advanced[]; last_run: Last; customised: boolean };
type Status = "idle" | "saving" | "saved" | "error";

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, Number.isFinite(v) ? Math.round(v) : lo));

/** Paramètres → Pondération de l'algorithme : valeurs enregistrées en base et transmises au solveur à chaque génération / réoptimisation. */
type Retention = { keep_per_month: number | null; max_age_days: number | null; months: { period_id: string; name: string; automatic: number; would_remove: number; archived: boolean }[] };

/** Conservation des copies automatiques : jamais les versions manuelles, soumises, validées ou publiées, ni celles d'un mois archivé. */
function VersionRetention() {
  const me = useMe(); const toast = useToast();
  const r = useApi<Retention>("/settings/version-retention");
  const can = me.permissions.includes("planning.admin");
  const [keep, setKeep] = useState(""); const [age, setAge] = useState("");
  useEffect(() => { if (r.data) { setKeep(r.data.keep_per_month === null ? "" : String(r.data.keep_per_month)); setAge(r.data.max_age_days === null ? "" : String(r.data.max_age_days)); } }, [r.data?.keep_per_month, r.data?.max_age_days]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!r.data) return null;
  const pending = r.data.months.reduce((n, m) => n + m.would_remove, 0);
  return (
    <Card title="Conservation des versions automatiques" eyebrow="Copies créées à chaque génération">
      <form className="row" style={{ alignItems: "flex-end" }} aria-label="Conservation des versions automatiques" onSubmit={async (e) => { e.preventDefault(); try { await api("/settings/version-retention", { method: "PUT", json: { keep_per_month: keep === "" ? null : Number(keep), max_age_days: age === "" ? null : Number(age) } }); toast.push("Politique enregistrée : elle s'applique à la prochaine génération.", "ok"); r.reload(); } catch (x) { toast.push(errText(x), "bad"); } }}>
        <Field label="Nombre conservé par mois" help="Vide : sans limite. Minimum 2.">{(p) => <Input {...p} type="number" min={2} max={1000} value={keep} disabled={!can} onChange={(e) => setKeep(e.target.value)} style={{ width: "9rem" }} />}</Field>
        <Field label="Âge maximal (jours)" help="Vide : sans limite d'âge">{(p) => <Input {...p} type="number" min={1} max={3650} value={age} disabled={!can} onChange={(e) => setAge(e.target.value)} style={{ width: "9rem" }} />}</Field>
        {can && <Button type="submit" variant="primary">Enregistrer</Button>}
        {can && pending > 0 && <Button onClick={async () => { try { await api("/settings/version-retention/apply", { method: "POST" }); toast.push(`${pending} copie(s) automatique(s) retirée(s).`, "ok"); r.reload(); } catch (x) { toast.push(errText(x), "bad"); } }}>Appliquer maintenant ({pending})</Button>}
      </form>
      <p className="help" style={{ marginTop: "var(--sp-2)" }}>Les versions manuelles, soumises, validées, publiées et celles des mois archivés ne sont jamais retirées. La copie la plus récente reste toujours. Chaque retrait est tracé dans le journal d&apos;audit.</p>
    </Card>
  );
}

export default function Settings() {
  const me = useMe(); const toast = useToast();
  const canEdit = me.permissions.includes("rules.write");
  const w = useApi<View>("/settings/weights");
  const [crit, setCrit] = useState<Record<string, number>>({}); const [adv, setAdv] = useState<Record<string, number>>({});
  const [status, setStatus] = useState<Status>("idle"); const [confirming, setConfirming] = useState(false);
  const pending = useRef<{ criteria: Record<string, number>; advanced: Record<string, number> }>({ criteria: {}, advanced: {} });
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    if (!w.data) return;
    setCrit((c) => (Object.keys(c).length ? c : Object.fromEntries(w.data!.criteria.map((x) => [x.key, x.value]))));
    setAdv((c) => (Object.keys(c).length ? c : Object.fromEntries(w.data!.advanced.map((x) => [x.key, x.value]))));
  }, [w.data]);

  function queue(kind: "criteria" | "advanced", key: string, value: number) {
    pending.current[kind][key] = value; setStatus("saving");
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const body = pending.current; pending.current = { criteria: {}, advanced: {} };
      try { w.mutate(await api<View>("/settings/weights", { method: "PUT", json: body })); setStatus("saved"); invalidate(); }
      catch { setStatus("error"); }
    }, 500);
  }
  const setC = (k: string, v: number, max = 100) => { const n = clamp(v, 0, max); setCrit((c) => ({ ...c, [k]: n })); queue("criteria", k, n); };
  const setA = (k: string, v: number, max: number) => { const n = clamp(v, 0, max); setAdv((c) => ({ ...c, [k]: n })); queue("advanced", k, n); };
  async function reset() {
    try { const v = await api<View>("/settings/weights/reset", { method: "POST" }); w.mutate(v); setCrit(Object.fromEntries(v.criteria.map((x) => [x.key, x.value]))); setAdv(Object.fromEntries(v.advanced.map((x) => [x.key, x.value])));
      setStatus("saved"); setConfirming(false); toast.push("Pondérations par défaut rétablies.", "ok"); invalidate(); }
    catch (e: unknown) { toast.push(e instanceof Error ? e.message : "Réinitialisation impossible", "bad"); }
  }
  const labelOf = (k: string) => w.data?.criteria.find((c) => c.key === k)?.label ?? w.data?.advanced.find((c) => c.key === k)?.label ?? k;
  return (
    <>
      <PageHead eyebrow="Réglages courants, options techniques à part" title="Paramètres">
        {canEdit && <Button icon="undo" onClick={() => setConfirming(true)} disabled={!w.data}>Réinitialiser les pondérations par défaut</Button>}
      </PageHead>
      <Callout kind="info" title="Priorités du planning">
        Chaque critère va de 0 à 100 et pèse dans la fonction d&apos;optimisation : <strong>+20 points doublent son influence</strong>, −20 la divisent par deux, 0 la supprime.
        Les contraintes strictes (repos, jours consécutifs, indisponibilités, marques autorisées, verrous, budgets stricts…) ne dépendent <strong>jamais</strong> de ces poids. Les réglages s&apos;appliquent à chaque nouvelle génération et réoptimisation.
      </Callout>
      {w.error ? <ErrorState message={w.error} onRetry={w.reload} /> : !w.data ? <SkeletonCard lines={8} /> : (
        <>
          <Card title="Priorités" eyebrow={w.data.customised ? "Personnalisé" : "Valeurs par défaut"} actions={<span className="muted" role="status" aria-live="polite">{status === "saving" ? "Enregistrement…" : status === "saved" ? "Enregistré automatiquement" : status === "error" ? "Échec de l'enregistrement" : canEdit ? "Enregistrement automatique" : "Lecture seule"}</span>}>
            <div className="weights">
              {w.data.criteria.map((c) => (
                <div key={c.key} className="weight-row" data-testid={`weight-${c.key}`}>
                  <div className="weight-text"><strong id={`w-${c.key}`}>{c.label}</strong><span className="help">{c.description}</span></div>
                  <input type="range" min={0} max={100} step={1} value={crit[c.key] ?? c.value} disabled={!canEdit} aria-labelledby={`w-${c.key}`} onChange={(e) => setC(c.key, Number(e.target.value))} />
                  <input className="input weight-num num" type="number" min={0} max={100} value={crit[c.key] ?? c.value} disabled={!canEdit} aria-label={`Valeur — ${c.label}`} onChange={(e) => setC(c.key, Number(e.target.value))} />
                  <span className="faint nowrap">défaut {c.default}</span>
                </div>))}
            </div>
          </Card>
          <VersionRetention />
          <details className="card glass advanced" data-testid="advanced-settings">
            <summary>Paramètres avancés</summary>
            <p className="help">Options techniques du moteur : leurs valeurs actuelles sont conservées telles quelles ; rien n&apos;est modifié en ouvrant cette section.</p>
            <Card title="Logique d'optimisation" eyebrow="Les contraintes strictes priment toujours">
            <label className="row"><input type="checkbox" checked={w.data.hierarchical} disabled={!canEdit} onChange={async (e) => { await api("/settings/weights", { method: "PUT", json: { hierarchical: e.target.checked } }); w.reload(); }} /> <strong>Optimisation hiérarchisée</strong></label>
            <p className="help">Activée : le moteur maximise d&apos;abord la couverture, puis tient les engagements (objectifs contractuels, quotas exacts, budgets souples), puis optimise l&apos;équité, les préférences et les autres critères. Chaque niveau est figé avant le suivant : un poids élevé sur une préférence ne peut jamais faire perdre un poste couvert. Désactivée : tous les critères sont additionnés.</p>
            </Card>
            <div className="card" data-testid="raw-weights"><p className="h2" style={{ marginTop: 0 }}>Poids bruts du moteur</p>
            <div className="weights" style={{ marginTop: "var(--sp-3)" }}>
              {w.data.advanced.map((a) => (
                <div key={a.key} className="weight-row">
                  <div className="weight-text"><strong id={`a-${a.key}`}>{a.label}</strong><span className="help">{a.description}</span></div>
                  <input type="range" min={0} max={a.max} step={1} value={adv[a.key] ?? a.value} disabled={!canEdit} aria-labelledby={`a-${a.key}`} onChange={(e) => setA(a.key, Number(e.target.value), a.max)} />
                  <input className="input weight-num num" type="number" min={0} max={a.max} value={adv[a.key] ?? a.value} disabled={!canEdit} aria-label={`Valeur — ${a.label}`} onChange={(e) => setA(a.key, Number(e.target.value), a.max)} />
                  <span className="faint nowrap">défaut {a.default}</span>
                </div>))}
            </div>
            </div>
            <Card title="Influence sur la dernière génération" eyebrow={w.data.last_run ? `${w.data.last_run.period} · ${new Date(w.data.last_run.at).toLocaleString("fr-CH", { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Zurich" })}` : undefined}>
            {!w.data.last_run ? <p className="muted">Aucune génération pour l&apos;instant : lancez-en une pour voir quels critères ont influencé le résultat.</p> : (
              <div className="table-wrap"><table className="table">
                <caption className="sr-only">Coût par critère de la dernière génération</caption>
                <thead><tr><th>Critère</th><th>Coût dans le score</th></tr></thead>
                <tbody>{Object.entries(w.data.last_run.by_criterion).filter(([, v]) => v !== 0).sort((a, b) => b[1] - a[1]).map(([k, v]) => <tr key={k}><td>{labelOf(k)}</td><td className="num">{v}</td></tr>)}</tbody>
              </table></div>
            )}
            <p className="help" style={{ marginTop: "var(--sp-2)" }}><Badge tone="info" icon="info">Lecture</Badge> Un coût élevé signifie que le critère a « coûté » dans la solution retenue (compromis). Le moteur minimise la somme pondérée.</p>
            </Card>
          </details>
        </>
      )}
      <Modal open={confirming} onClose={() => setConfirming(false)} title="Réinitialiser les pondérations ?" description="Toutes les pondérations reviennent aux valeurs par défaut." variant="confirm">
        <div className="stack"><p>Les plannings existants ne changent pas ; la prochaine génération utilisera les valeurs par défaut.</p>
          <div className="row modal-actions"><Button onClick={() => setConfirming(false)}>Annuler</Button><Button variant="primary" onClick={reset}>Réinitialiser</Button></div></div>
      </Modal>
    </>
  );
}
