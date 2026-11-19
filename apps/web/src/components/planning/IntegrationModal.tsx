"use client";
import { useEffect, useRef, useState } from "react";
import { Badge, Button, Callout, Field, Input, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { fmtHM } from "@/lib/schedule";
import { errText } from "@/lib/wfm";
import { RunFailure, RunProgress, SaveOutcome, type RunView } from "@/components/planning/RunStatus";

export type Added = { kind: "brand"; code: string; name: string } | { kind: "employee"; id: string; name: string };
type Candidate = { period_id: string; name: string; label: string; month: string; status_label: string; assignments: number; published: boolean;
  already: { choice: string; choice_label: string } | null };
type Missing = { code: string; text: string; where: "catalog" | "budget" };
type Readiness = { ready: boolean; missing: Missing[]; shifts: number; sites: string[]; base_minutes: number | null; budget_minutes: number | null; need_minutes: number };
type Step = "choose" | "recalc" | "running" | "manual-done";

const TIME_LIMIT = 30;
const DONE = new Set(["termine", "erreur", "annule"]);

/**
 * Après l'ajout d'une marque ou d'un collaborateur : « Comment souhaitez-vous intégrer cet ajout au planning de [mois année] ? ».
 * Le mois concerné est indiqué avant le choix ; rien n'est lancé ni modifié tant qu'un choix n'est pas confirmé ; aucun autre mois touché.
 * Ne s'affiche que si un planning existant (en cours ou à venir, avec des affectations) est concerné.
 */
export function IntegrationModal({ added, onClose }: { added: Added | null; onClose: () => void }) {
  const toast = useToast();
  const [periods, setPeriods] = useState<Candidate[] | null>(null);
  const [pid, setPid] = useState("");
  const [step, setStep] = useState<Step>("choose");
  const [ready, setReady] = useState<Readiness | null>(null);
  const [budget, setBudget] = useState("");
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const [official, setOfficial] = useState(false); const [confirmReplace, setConfirmReplace] = useState(false);
  const [run, setRun] = useState<RunView | null>(null);
  const key = useRef("");

  useEffect(() => {
    setPeriods(null); setPid(""); setStep("choose"); setReady(null); setErr(""); setOfficial(false); setConfirmReplace(false); setRun(null);
    if (!added) return;
    key.current = `integ-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const q = added.kind === "brand" ? `brand_code=${encodeURIComponent(added.code)}` : `employee_id=${added.id}`;
    api<{ periods: Candidate[] }>(`/integrations/candidates?${q}`).then((r) => {
      const todo = r.periods.filter((p) => !p.already);
      if (!todo.length) { onClose(); return; } // aucun planning existant concerné : rien à demander
      setPeriods(todo); setPid(todo[0].period_id);
    }).catch(() => onClose());
  }, [added]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { // suivi du calcul lancé
    if (!run || DONE.has(run.status)) return;
    const id = setInterval(async () => { try { setRun(await api<RunView>(`/runs/${run.id}`)); } catch { /* nouvel essai à l'intervalle suivant */ } }, 1000);
    return () => clearInterval(id);
  }, [run]);
  useEffect(() => { if (run && DONE.has(run.status)) invalidate(); }, [run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const cur = periods?.find((p) => p.period_id === pid) ?? null;
  const what = added?.kind === "brand" ? `la marque ${added.name}` : `${added?.name ?? ""}`;
  const body = (choice: "recalculate" | "manual") => ({
    kind: added!.kind, choice, time_limit_s: TIME_LIMIT, confirm_replace: confirmReplace,
    ...(added!.kind === "brand" ? { brand_code: added!.code } : { employee_id: added!.id }),
  });

  async function loadReadiness() {
    if (!added || added.kind !== "brand" || !cur) return;
    const r = await api<Readiness>(`/periods/${cur.period_id}/integrations/readiness?brand_code=${encodeURIComponent(added.code)}`);
    setReady(r);
    if (r.budget_minutes === null) setBudget(r.base_minutes !== null ? String(r.base_minutes / 60) : "");
  }
  async function toRecalc() {
    setErr(""); setStep("recalc");
    if (added?.kind !== "brand") return; // collaborateur : rien à vérifier avant le calcul (aucun quota supposé)
    try { await loadReadiness(); } catch (e) { setErr(errText(e)); }
  }
  async function saveBudget() {
    if (!added || added.kind !== "brand" || !cur || budget.trim() === "" || Number(budget) < 0) return;
    setBusy(true); setErr("");
    try { await api(`/periods/${cur.period_id}/brands/${encodeURIComponent(added.code)}`, { method: "PUT", json: { budget_minutes: Math.round(Number(budget) * 60) } }); await loadReadiness(); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function submit(choice: "recalculate" | "manual") {
    if (!cur || busy) return;
    setBusy(true); setErr("");
    try {
      const r = await api<{ run_id: string | null; label: string }>(`/periods/${cur.period_id}/integrations`, { method: "POST", json: body(choice), headers: { "Idempotency-Key": key.current } });
      if (choice === "manual") { setStep("manual-done"); toast.push(`Choix enregistré pour ${r.label} : ajout manuel des shifts.`, "ok"); invalidate(); }
      else { setStep("running"); setRun({ id: r.run_id!, status: "en_attente" }); }
    } catch (e) {
      const d = e instanceof ApiError ? (e.detail as { code?: string; message?: string; missing?: Missing[] } | undefined) : undefined;
      if (d?.code === "official_version") { setOfficial(true); setErr(d.message ?? ""); key.current = `integ-${Date.now()}`; }
      else if (d?.code === "not_ready") { setErr(d.message ?? ""); await loadReadiness().catch(() => undefined); key.current = `integ-${Date.now()}`; }
      else { setErr(d?.message ?? errText(e)); key.current = `integ-${Date.now()}`; }
    } finally { setBusy(false); }
  }
  const goPlanning = () => { if (cur) { try { localStorage.setItem("planning:month", cur.month); } catch { /* préférence locale seulement */ } } window.location.assign("/planning"); };

  if (!added || !periods || !cur) return null;
  const title = `Comment souhaitez-vous intégrer cet ajout au planning de ${cur.label} ?`;
  return (
    <Modal open onClose={() => !busy && onClose()} title={title} description={`${added.kind === "brand" ? "Nouvelle marque" : "Nouveau collaborateur"} : ${added.name}. Seul le planning de ${cur.label} est concerné ; aucun autre mois n'est modifié.`}>
      <div className="stack" data-testid="integration-modal">
        {periods.length > 1 && step === "choose" && (
          <Field label="Planning concerné" help="Un seul mois à la fois ; les autres ne sont pas modifiés.">{(p) => (
            <Select {...p} value={pid} onChange={(e) => { setPid(e.target.value); setReady(null); setErr(""); }}>
              {periods.map((x) => <option key={x.period_id} value={x.period_id}>{x.label.charAt(0).toUpperCase() + x.label.slice(1)} — {x.status_label}</option>)}
            </Select>)}</Field>)}
        <dl className="facts" data-testid="integration-month">
          <div><dt>Mois concerné</dt><dd>{cur.label.charAt(0).toUpperCase() + cur.label.slice(1)}</dd></div>
          <div><dt>Statut</dt><dd>{cur.status_label}{cur.published ? <> <Badge tone="warn">Publié</Badge></> : null}</dd></div>
          <div><dt>Affectations actuelles</dt><dd className="num">{cur.assignments}</dd></div>
        </dl>

        {step === "choose" && <>
          <div className="choice-grid" role="group" aria-label="Choix d'intégration">
            <button type="button" className="choice-card" onClick={() => void toRecalc()} data-testid="choice-recalculate">
              <strong>Recalculer tout le planning</strong>
              <span className="help">Nouvelle génération de {cur.label} avec {what}, les besoins et les paramètres du mois : disponibilités, compétences, budgets, plafond mensuel et affectations verrouillées respectés. Le planning actuel est conservé en version ; le résultat est une nouvelle version, non publiée.</span>
            </button>
            <button type="button" className="choice-card" onClick={() => void submit("manual")} disabled={busy} data-testid="choice-manual">
              <strong>Ajouter les shifts manuellement</strong>
              <span className="help">Les affectations actuelles sont conservées et aucune n&apos;est créée automatiquement. {added.kind === "brand" ? "Un suivi de couverture de la marque s'affiche dans le planning." : `${added.name} rejoint l'effectif de ce mois ; vous lui attribuez les shifts de votre choix.`}</span>
            </button>
          </div>
          {err && <Callout kind="bad" title="Choix non enregistré">{err}</Callout>}
          <div className="row modal-actions"><Button onClick={onClose} disabled={busy}>Décider plus tard</Button></div>
        </>}

        {step === "recalc" && <>
          {added.kind === "brand" && !ready && !err && <div className="skeleton" style={{ height: "4rem" }} aria-hidden="true" />}
          {added.kind === "brand" && ready && !ready.ready && (
            <Callout kind="warn" title="Informations à compléter avant le calcul" >
              <ul className="issue-list" data-testid="integration-missing">{ready.missing.map((m) => <li key={m.code}>{m.text}{m.where === "catalog" && <> <a href="/catalog" style={{ textDecoration: "underline" }}>Renseigner dans « Sites et marques »</a></>}</li>)}</ul>
              {ready.missing.some((m) => m.code === "budget") && (
                <form className="row" style={{ alignItems: "flex-end", marginTop: "var(--sp-2)" }} onSubmit={(e) => { e.preventDefault(); void saveBudget(); }}>
                  <Field label={`Budget ${added.name} pour ${cur.label} (heures)`} help={ready.base_minutes !== null ? `Prérempli avec le budget de base (${fmtHM(ready.base_minutes)}) : modifiable.` : "Aucun budget de base : saisissez le budget de ce mois."}>{(p) => (
                    <Input {...p} type="number" min={0} step={0.5} value={budget} onChange={(e) => setBudget(e.target.value)} style={{ width: "8rem" }} />)}</Field>
                  <Button type="submit" disabled={busy || budget.trim() === ""}>Enregistrer le budget</Button>
                </form>)}
            </Callout>)}
          {added.kind === "brand" && ready?.ready && <Callout kind="ok" title={`${added.name} est prête pour le calcul`}>{ready.shifts} shift(s) à couvrir ({fmtHM(ready.need_minutes)}) · budget du mois {ready.budget_minutes !== null ? fmtHM(ready.budget_minutes) : "—"}.</Callout>}
          {added.kind === "employee" && <p>{added.name} sera ajouté·e à l&apos;effectif de {cur.label} uniquement, puis le mois sera recalculé.</p>}
          {official && <label className="row"><input type="checkbox" checked={confirmReplace} onChange={(e) => setConfirmReplace(e.target.checked)} /> Remplacer le planning en cours de {cur.label} (la version validée ou publiée reste conservée et n&apos;est pas modifiée)</label>}
          {err && <Callout kind="bad" title="Calcul non lancé">{err}</Callout>}
          <div className="row modal-actions">
            <Button onClick={() => { setStep("choose"); setErr(""); setOfficial(false); }} disabled={busy}>Retour</Button>
            <Button variant="primary" onClick={() => void submit("recalculate")} disabled={busy || (added.kind === "brand" && !ready?.ready) || (official && !confirmReplace)} aria-busy={busy} data-testid="integration-launch">
              {busy ? "Lancement…" : "Lancer le recalcul"}</Button>
          </div>
        </>}

        {step === "running" && run && <>
          {!DONE.has(run.status) ? <RunProgress run={run} limit={TIME_LIMIT} /> : run.status === "termine" && run.save?.outcome === "replaced" ? (
            <Callout kind="ok" title="Planning recalculé"><span data-testid="integration-result" data-outcome="replaced" hidden /><SaveOutcome save={run.save} timing={run.timing} proof={run.proof} /><p className="help" style={{ margin: 0 }}>Le planning précédent reste disponible dans les versions (« Avant intégration de {added.name} »). La nouvelle version n&apos;est pas publiée.</p></Callout>
          ) : <div data-testid="integration-result" data-outcome={run.save?.outcome ?? run.status}>
            <Callout kind="warn" title={`Planning de ${cur.label} conservé`}>Le recalcul n&apos;a pas remplacé le planning : il reste actif tel qu&apos;il était. Raison ci-dessous.</Callout>
            <RunFailure runId={run.id} status={run.status} save={run.save} timing={run.timing} /></div>}
          <div className="row modal-actions">
            {!DONE.has(run.status) && <Button onClick={() => void api(`/runs/${run.id}/cancel`, { method: "POST" }).catch((e) => setErr(errText(e)))}>Annuler le calcul</Button>}
            {err && <span className="error-text">{err}</span>}
            <Button onClick={onClose}>Fermer</Button>
            {DONE.has(run.status) && <Button variant="primary" onClick={goPlanning}>Voir le planning</Button>}
          </div>
        </>}

        {step === "manual-done" && <>
          <Callout kind="ok" title="Choix enregistré">
            {added.kind === "brand" ? `Le suivi de couverture de ${added.name} est affiché dans le planning de ${cur.label}. Placez puis attribuez ses shifts ; les contrôles habituels s'appliquent.`
              : `${added.name} fait partie de l'effectif de ${cur.label}. Attribuez-lui des shifts depuis le planning ; les contrôles habituels s'appliquent.`}
          </Callout>
          <div className="row modal-actions"><Button onClick={onClose}>Fermer</Button><Button variant="primary" onClick={goPlanning}>Ouvrir le planning de {cur.label}</Button></div>
        </>}
      </div>
    </Modal>
  );
}
