"use client";
import { useEffect, useState } from "react";
import { useApi } from "@/components/hooks";
import { Badge, Callout, Field, Input, Progress } from "@/components/ui/primitives";
import { api } from "@/lib/api";

export type RunProgressData = { phase?: string; level?: string; index?: number; count?: number; solutions?: number; elapsed_s?: number; time_limit_s?: number } | null;
export type RunView = { id: string; status: string; result_status?: string | null; started_at?: string | null; progress?: RunProgressData; config?: { time_limit_s?: number };
  save?: SaveInfo | null; timing?: RunTiming | null; proof?: Proof | null };
export type PeriodParams = { frozen: boolean; frozen_at: string | null; source: string | null; differences: ParamDiff[]; current_cap_minutes: number | null; plan_cap_minutes: number | null;
  generation_run_id?: string | null; weights?: Record<string, number> | null };
export type ParamsMode = "frozen" | "current" | null;
export type ParamDiff = { employee: string | null; employee_id?: string; field: string; label: string; planning: string; current: string };

const LEVEL: Record<string, string> = {
  couverture: "couverture des besoins",
  engagements: "engagements (objectifs contractuels, quotas de dimanches, minimum de jours, budgets)",
  optimisation: "équité et préférences",
  pondere: "optimisation pondérée",
};
const fmtDate = (iso: string | null) => {
  if (!iso) return "—";
  const p = Object.fromEntries(new Intl.DateTimeFormat("fr-CH", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Zurich" })
    .formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
  return `${p.day}/${p.month}/${p.year} à ${p.hour}:${p.minute}`;
};
export const frozenLabel = (p: { frozen_at: string | null; source: string | null }) =>
  p.source === "mise_en_place" ? `conservés depuis le ${fmtDate(p.frozen_at)} (mise en place de la conservation des paramètres)` : `conservés depuis le ${fmtDate(p.frozen_at)}`;

/** Champ « Durée maximale du calcul » avec ce que fait réellement le moteur (vérifié dans engine.py). */
export function TimeLimitField({ value, onChange, width = "8rem" }: { value: number; onChange: (v: number) => void; width?: string }) {
  return (
    <div className="stack" style={{ gap: "var(--sp-1)" }}>
      <Field label="Durée maximale du calcul (secondes)">{(p) => <Input {...p} type="number" min={5} max={600} value={value} onChange={(e) => onChange(Math.max(5, Math.min(600, Number(e.target.value) || 30)))} style={{ width }} aria-describedby="time-limit-help" />}</Field>
      <div id="time-limit-help" className="help" data-testid="time-limit-help">
        <p style={{ margin: 0 }}><strong>C&apos;est une limite, pas une durée fixe.</strong> Le moteur s&apos;arrête plus tôt dès que le planning ne peut plus être amélioré (meilleure solution prouvée).</p>
        <p style={{ margin: 0 }}>Une durée plus longue laisse plus de temps pour trouver un meilleur planning (moins de shifts non couverts, heures mieux réparties) ; elle ne change jamais les règles obligatoires. Elle borne la construction du modèle et la recherche du solveur (à quelques dixièmes de seconde près : le solveur termine l&apos;étape en cours) ; la préparation des données (avant), puis les contrôles du moteur et l&apos;enregistrement vérifié (après) s&apos;y ajoutent. Le détail mesuré de chaque étape est affiché à la fin du calcul.</p>
        <p style={{ margin: 0 }}>À l&apos;expiration : si une solution existe, la meilleure trouvée est vérifiée puis enregistrée (statut « faisable » au lieu d&apos;« optimal ») ; si aucune solution n&apos;a été trouvée, rien n&apos;est enregistré et le planning existant reste intact.</p>
        <p style={{ margin: 0 }}>Un planning qui enfreindrait une contrainte obligatoire n&apos;est jamais enregistré ni présenté comme valide.</p>
      </div>
    </div>
  );
}

function stateText(run: RunView): string {
  const p = run.progress ?? {};
  if (run.status === "en_attente") return "En attente d'un calculateur disponible…";
  switch (p.phase) {
    case "preparing": return "Préparation des données (collaborateurs, besoins, règles)…";
    case "model": return "Construction du modèle de calcul…";
    case "level": return `Étape ${p.index ?? "?"} sur ${p.count ?? "?"} : ${LEVEL[p.level ?? ""] ?? p.level} — ${p.solutions ?? 0} solution${(p.solutions ?? 0) > 1 ? "s" : ""} trouvée${(p.solutions ?? 0) > 1 ? "s" : ""}`;
    case "checking": return "Vérification indépendante du planning trouvé…";
    case "saving": return "Enregistrement et vérification du planning enregistré…";
    default: return "Calcul en cours…";
  }
}

/** Temps écoulé (horloge locale, recalée sur le début réel du calcul) et état compréhensible du calcul. */
export function RunProgress({ run, limit }: { run: RunView; limit: number }) {
  const [now, setNow] = useState(() => Date.now());
  const [t0] = useState(() => Date.now());
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(id); }, []);
  const start = run.started_at ? new Date(run.started_at).getTime() : t0;
  const elapsed = Math.max(0, Math.round((now - start) / 1000));
  const max = run.progress?.time_limit_s ?? run.config?.time_limit_s ?? limit;
  return (
    <div className="stack" role="status" aria-live="polite" data-testid="run-progress" style={{ gap: "var(--sp-2)" }}>
      <p style={{ margin: 0 }}><Badge tone="info">{run.status === "en_attente" ? "En attente" : "En cours"}</Badge> {stateText(run)}</p>
      <Progress value={Math.min(100, (elapsed / Math.max(1, max)) * 100)} label="Temps utilisé sur la durée maximale" />
      <p className="help num" style={{ margin: 0 }} data-testid="run-elapsed">Temps écoulé depuis le début : {elapsed} s · durée maximale du calcul (modèle et recherche) : {max} s{elapsed > max ? " — contrôles et enregistrement en cours, hors durée maximale" : ""}</p>
    </div>
  );
}

/** Choix EXPLICITE des paramètres pour un planning qui conserve les siens : quand des paramètres ont changé depuis sa création, aucun choix
 *  n'est présélectionné (`value` reste null) et la génération attend la décision de l'utilisateur. */
export function ParamsChoice({ periodId, value, onChange }: { periodId: string | null; value: ParamsMode; onChange: (v: "frozen" | "current") => void }) {
  const params = useApi<PeriodParams>(periodId ? `/periods/${periodId}/params` : null);
  const d = params.data;
  const n = d?.differences.length ?? 0;
  useEffect(() => {
    if (value === null && (!periodId || (d && (!d.frozen || n === 0)))) onChange("frozen"); // rien à décider : paramètres identiques ou planning neuf
  }, [periodId, d, n, value]); // eslint-disable-line react-hooks/exhaustive-deps
  if (periodId && !d) return params.error ? <p className="help">{params.error}</p> : <div className="skeleton" style={{ height: "3rem" }} aria-hidden="true" />; // chargement : rien d'affirmé
  if (!d || !d.frozen) return <p className="help">Ce mois n&apos;a pas encore de planning : les paramètres actuels seront utilisés, puis conservés avec le planning.</p>;
  return (
    <fieldset className="sheet-section" data-testid="params-choice">
      <legend className="h2">Paramètres utilisés</legend>
      {value === null && <Callout kind="warn" title="Choisissez les paramètres à utiliser">{n} paramètre{n > 1 ? "s ont" : " a"} changé depuis la création de ce planning (fiches, effectif, règles ou pondérations). Ils ne s&apos;appliquent à ce planning que si vous le décidez.</Callout>}
      <div role="radiogroup" aria-label="Paramètres utilisés pour le calcul" className="radio-col">
        <label className="row"><input type="radio" name="params" checked={value === "frozen"} onChange={() => onChange("frozen")} /> Paramètres de ce planning <span className="faint">— {frozenLabel(d)}</span></label>
        <label className="row"><input type="radio" name="params" checked={value === "current"} onChange={() => onChange("current")} /> Paramètres actuels <span className="faint">— {n ? `${n} différence${n > 1 ? "s" : ""} ; ils remplaceront ceux conservés par ce planning` : "identiques à ceux du planning"}</span></label>
      </div>
      {value === "current" && n > 0 && <ul className="help" style={{ margin: 0, paddingLeft: "1.1rem" }}>{d.differences.slice(0, 8).map((x, i) => <li key={i}>{x.employee ? `${x.employee} · ` : ""}{x.label} : {x.planning} → <strong>{x.current}</strong></li>)}{n > 8 && <li>… et {n - 8} autre(s)</li>}</ul>}
      {d.current_cap_minutes !== null && <p className="help" style={{ margin: 0 }}>Dans les deux cas, le plafond actuel de {Math.round(d.current_cap_minutes / 60)} h de travail effectif par collaborateur et par mois (tous sites et marques cumulés) est appliqué.</p>}
    </fieldset>
  );
}

/** Calcul refusé par la vérification indépendante : jamais présenté comme un planning valide. */
export function RunFailure({ runId, status, save, timing }: { runId: string; status: string; save?: SaveInfo | null; timing?: RunTiming | null }) {
  const [blocked, setBlocked] = useState<string[] | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  useEffect(() => {
    api<{ status: string; report: { blocked_by_verification?: string[]; diagnostics?: { message: string }[]; error?: string } }>(`/runs/${runId}/diagnostic`)
      .then((r) => { setBlocked(r.report.blocked_by_verification ?? null); if (r.status === "infaisable" || r.status === "interrompu") setReason(r.status === "interrompu" ? "Aucune solution trouvée dans la durée maximale : augmentez-la ou allégez les contraintes." : r.report.diagnostics?.[0]?.message ?? "Contraintes incompatibles."); })
      .catch(() => setBlocked(null));
  }, [runId]);
  if (save && save.outcome === "kept_previous" && !blocked?.length) return <SaveOutcome save={save} timing={timing} />;
  return (
    <Callout kind="bad" title={status === "annule" ? "Calcul annulé" : blocked?.length ? "Planning refusé par la vérification" : "La génération n'a pas abouti"}>
      <p style={{ margin: 0 }}>Le planning existant (s&apos;il y en a un) n&apos;a pas été modifié.</p>
      {blocked && blocked.length > 0 && <><p style={{ margin: "var(--sp-1) 0 0" }}>La solution trouvée enfreignait {blocked.length} contrainte(s) obligatoire(s) : elle n&apos;a pas été enregistrée.</p><ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{blocked.slice(0, 5).map((b) => <li key={b}>{b}</li>)}</ul></>}
      {(save?.reason ?? reason) && <p style={{ margin: "var(--sp-1) 0 0" }}>{save?.reason ?? reason}</p>}
      <TimingLine t={timing} />
    </Callout>
  );
}

export type Volume = { mandatory: number; optional: number; minutes: number; optional_minutes: number; other: number };
export type VolumeReport = { before: Volume; after: Volume; delta_optional: number; delta_optional_minutes: number; optional_without_budget: string[]; note: string | null };
export type Proof = { proved: boolean; time_limit_s?: number | null; levels?: { level: string; proved: boolean }[] };
export type SaveInfo = { outcome: "replaced" | "kept_previous" | "simulation"; reason_code: string; reason: string;
  before: { assignments: number; locked: number; version: number | null }; after: { assignments: number; locked: number; version: number | null }; volume?: VolumeReport };
export type RunTiming = { time_limit_s?: number; preparation_s?: number; model_s?: number; search_s?: number; post_s?: number; engine_total_s?: number;
  solver_call_s?: number; saving_s?: number; total_s?: number };
const sec = (v?: number) => (v === undefined || v === null ? "—" : `${v < 10 ? v.toFixed(1) : Math.round(v)} s`.replace(".", ","));

/** Temps MESURÉS de chaque étape : la durée maximale borne la construction du modèle et la recherche du solveur ; la préparation des données,
 *  les contrôles du moteur et l'enregistrement s'y ajoutent. */
export function TimingLine({ t }: { t?: RunTiming | null }) {
  if (!t || t.total_s === undefined) return null;
  return (
    <p className="help" data-testid="run-timing" style={{ margin: 0 }}>
      Temps mesurés : préparation des données {sec(t.preparation_s)} · construction du modèle {sec(t.model_s)} + recherche du solveur {sec(t.search_s)}
      {t.time_limit_s ? ` (durée maximale ${sec(t.time_limit_s)} pour ces deux étapes)` : ""} · contrôles du moteur {sec(t.post_s)} · enregistrement et vérification {sec(t.saving_s)} · total {sec(t.total_s)}.
    </p>
  );
}

/** Résultat d'enregistrement donné par le serveur : planning remplacé (versions avant / après) ou ancien planning conservé, avec la raison. */
const hm = (m: number) => { const h = Math.floor(m / 60), r = m % 60; return r ? `${h} h ${String(r).padStart(2, "0")}` : `${h} h`; };

/** Volume attribué, présenté À PART de l'équité : obligatoires, optionnels, heures ; toute baisse des optionnels est signalée et expliquée. */
export function VolumeLine({ v }: { v?: VolumeReport }) {
  if (!v) return null;
  const a = v.after, b = v.before;
  return (
    <div className="stack" style={{ gap: "var(--sp-1)" }} data-testid="volume">
      <p style={{ margin: 0 }}><strong>Volume attribué :</strong> {a.mandatory} shift(s) obligatoire(s) et {a.optional} optionnel(s), {hm(a.minutes)} au total
        {b.mandatory + b.optional > 0 ? <> (planning remplacé : {b.mandatory} obligatoire(s), {b.optional} optionnel(s), {hm(b.minutes)})</> : null}.</p>
      {v.note && <Callout kind={v.delta_optional > 0 ? "info" : "warn"} title={v.delta_optional > 0 ? `${v.delta_optional} shift(s) optionnel(s) de plus (+${hm(v.delta_optional_minutes)})` : `${-v.delta_optional} shift(s) optionnel(s) de moins (${hm(-v.delta_optional_minutes)})`}>
        <span data-testid="volume-note">{v.note}</span> <a href="/planning#besoins-optionnels" style={{ textDecoration: "underline" }}>Voir les besoins optionnels non attribués</a></Callout>}
    </div>
  );
}

/** Planning valide ≠ optimum prouvé : quand la durée maximale est atteinte, le planning respecte toutes les règles obligatoires (vérifiées)
 *  mais sa répartition n'est pas prouvée la meilleure possible. */
export function ProofLine({ p }: { p?: Proof | null }) {
  if (!p) return null;
  return p.proved
    ? <p className="help" style={{ margin: 0 }} data-testid="proof" data-proved="true">Meilleure solution prouvée pour les critères choisis.</p>
    : <p style={{ margin: 0 }} data-testid="proof" data-proved="false"><strong>Planning valide, optimisation non terminée :</strong> toutes les règles obligatoires sont vérifiées, mais la durée maximale{p.time_limit_s ? ` (${p.time_limit_s} s)` : ""} a été atteinte avant de prouver la meilleure répartition. Le planning est utilisable ; une durée plus longue peut encore l&apos;améliorer.</p>;
}

export function SaveOutcome({ save, timing, proof }: { save?: SaveInfo | null; timing?: RunTiming | null; proof?: Proof | null }) {
  if (!save) return null;
  const v = (n: number | null | undefined) => (n ? `version n° ${n}` : "aucune version");
  if (save.outcome === "replaced") return (
    <Callout kind="ok" title="Nouveau planning enregistré">
      <div className="stack" style={{ gap: "var(--sp-1)" }} data-testid="save-outcome" data-outcome="replaced">
        <ProofLine p={proof} />
        <VolumeLine v={save.volume} />
        <p style={{ margin: 0 }}>{save.after.assignments} affectation(s) enregistrée(s), dont {save.after.locked} verrouillée(s) conservée(s) telles quelles. Avant : {save.before.assignments} affectation(s), {v(save.before.version)} ; après : {v(save.after.version)}.</p>
        <TimingLine t={timing} />
      </div>
    </Callout>
  );
  if (save.outcome === "simulation") return null;
  return (
    <Callout kind="warn" title="Le planning précédent est conservé">
      <div className="stack" style={{ gap: "var(--sp-1)" }} data-testid="save-outcome" data-outcome="kept_previous" data-reason={save.reason_code}>
        <p style={{ margin: 0 }}><strong>Pourquoi :</strong> {save.reason}</p>
        <p style={{ margin: 0 }}>Planning inchangé : {save.before.assignments} affectation(s) ({save.before.locked} verrouillée(s)), {v(save.before.version)}. Aucune nouvelle solution valide n&apos;a été enregistrée.</p>
        <TimingLine t={timing} />
      </div>
    </Callout>
  );
}
