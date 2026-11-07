"use client";
import { Badge, Button, Callout } from "@/components/ui/primitives";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { useApi } from "@/components/hooks";
import { hourRange, longDate } from "@/lib/reassign";
import { resultLabel } from "@/lib/wfm";
import { TermList, points, type TermLine } from "./ReplacementsModal";

type Explain = {
  employee: string; day: string; site: string; start: string; end: string; brands: string[]; all_rules_ok: boolean; caveat: string; compatible_candidates: number; better_alternatives: number;
  checks: { ok: boolean; code: string; label: string; detail: string }[];
  observed: { label: string; tone: "favorable" | "defavorable" | "neutre"; detail: string }[];
  alternatives: { name: string; extra_cost: number; terms: TermLine[] }[];
  origin: { source: string; locked: boolean; manual: boolean; run_status?: string; proved_optimal?: boolean; strategy?: string | null };
};
const TONE = { favorable: "ok", defavorable: "warn", neutre: "neutral" } as const;

/** « Pourquoi ce collaborateur ? » : uniquement des faits vérifiables, sans inventer de cause unique. */
export function ExplainModal({ assignmentId, onClose }: { assignmentId: string | null; onClose: () => void }) {
  const q = useApi<Explain>(assignmentId ? `/assignments/${assignmentId}/explain` : null);
  const x = q.data;
  return (
    <Modal open={!!assignmentId} onClose={onClose} title={x ? `Pourquoi ${x.employee} sur ce shift ?` : "Pourquoi ce collaborateur ?"} description={x ? `${longDate(x.day)} · ${x.brands.join(" + ")} · ${x.site} · ${hourRange(x.start, x.end)}` : undefined}>
      {q.loading && !x ? <p className="muted" role="status">Analyse de l&apos;affectation…</p> : q.error ? <Callout kind="bad" title="Explication indisponible">{q.error}</Callout> : x && (
        <div className="stack">
          <div className="row">
            <Badge tone={x.origin.manual ? "info" : "neutral"}>{x.origin.manual ? "Affectation manuelle" : "Proposée par le moteur"}</Badge>
            {x.origin.locked && <Badge tone="accent" icon="lock">Verrouillée</Badge>}
            {x.origin.run_status && <Badge tone={x.origin.proved_optimal ? "ok" : "info"}>{resultLabel(x.origin.run_status, x.origin.proved_optimal)}</Badge>}
          </div>
          <section aria-label="Règles strictes contrôlées">
            <h3 className="h2">Règles strictes</h3>
            {!x.all_rules_ok && <Callout kind="warn">Au moins une règle n&apos;est pas respectée aujourd&apos;hui : dérogation enregistrée ou paramètres modifiés depuis.</Callout>}
            <ul className="explain-list">{x.checks.map((c) => <li key={c.code} data-ok={c.ok}><Icon name={c.ok ? "check" : "alert"} size={14} /><span><strong>{c.label}</strong><span className="muted"> — {c.detail}</span></span></li>)}</ul>
          </section>
          <section aria-label="Critères observés">
            <h3 className="h2">Critères observés</h3>
            <ul className="explain-list">{x.observed.map((o) => <li key={o.label + o.detail}><Badge tone={TONE[o.tone]}>{o.tone === "favorable" ? "Favorable" : o.tone === "defavorable" ? "Défavorable" : "Neutre"}</Badge><span><strong>{o.label}</strong><span className="muted"> — {o.detail}</span></span></li>)}</ul>
          </section>
          <section aria-label="Autres candidats">
            <h3 className="h2">Autres candidats compatibles ({x.compatible_candidates})</h3>
            {x.alternatives.length === 0 ? <p className="muted">Aucun autre collaborateur ne respecte toutes les règles strictes pour ce shift.</p> : (
              <>
                <p className="help">Variation du coût du planning si cette personne prenait ce shift, tout le reste étant inchangé. {x.better_alternatives > 0 ? `${x.better_alternatives} candidat(s) réduiraient ce coût : le moteur a pu arbitrer au niveau du planning entier, ou ce shift a été modifié depuis.` : "Aucun échange simple ne réduirait le coût."}</p>
                <ul className="cand-list">{x.alternatives.map((a) => (
                  <li key={a.name} className="cand"><div className="spread"><strong>{a.name}</strong><span className="num">{points(a.extra_cost)}</span></div>
                    <details><summary>Détail</summary><TermList terms={a.terms} /></details></li>))}</ul>
              </>
            )}
          </section>
          <Callout kind="info" title="Comment lire cette explication">{x.caveat}</Callout>
          <div className="row modal-actions"><Button onClick={onClose}>Fermer</Button></div>
        </div>
      )}
    </Modal>
  );
}
