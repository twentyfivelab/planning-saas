"use client";
import { useMe } from "@/components/Shell";
import { useApi } from "@/components/hooks";
import { Badge, Button, Callout, Card, ErrorState, SkeletonCard } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { errText } from "@/lib/wfm";

type Rule = { id: string; code: string; jurisdiction: string | null; params: { value?: number; rules?: { over_minutes: number; break_minutes: number }[] }; version: number; enabled: boolean; valid_from: string | null; valid_to: string | null; source_url: string | null; review_status: string; review_label: string; reviewed_by: string | null; note: string | null };
type Template = { key: string; label: string; note: string; source_url: string; active: boolean };
type Data = { rules: Rule[]; templates: Template[]; pending_review: number; regimes: string[]; sources: { label: string; url: string }[] };
const NAME: Record<string, string> = { rest_hours: "Repos quotidien", max_consecutive_days: "Jours consécutifs", weekly_max_minutes: "Durée maximale hebdomadaire", break_rules: "Pauses minimales" };
const value = (r: Rule) => {
  if (r.code === "rest_hours") return `${r.params.value} h`;
  if (r.code === "max_consecutive_days") return `${r.params.value} jours`;
  if (r.code === "weekly_max_minutes") return `${(r.params.value ?? 0) / 60} h`;
  return (r.params.rules ?? []).map((x) => `${x.break_minutes} min au-delà de ${x.over_minutes / 60} h`).join(" · ");
};
const TONE: Record<string, "ok" | "warn" | "bad"> = { valide: "ok", a_valider: "warn", rejete: "bad" };

/** Référentiel juridique : modèles sourcés, activation explicite, versions conservées, validation nominative par un responsable. */
export function LegalReferential() {
  const me = useMe(); const toast = useToast();
  const q = useApi<Data>("/legal/rules");
  const canWrite = me.permissions.includes("rules.write"), canReview = me.permissions.includes("legal.review");
  async function act(fn: () => Promise<unknown>, msg: string) { try { await fn(); toast.push(msg, "ok"); q.reload(); invalidate(); } catch (e) { toast.push(errText(e), "bad"); } }
  if (q.error) return <ErrorState message={q.error} onRetry={q.reload} />;
  if (!q.data) return <SkeletonCard lines={4} />;
  const d = q.data;
  return (
    <Card title="Référentiel juridique" eyebrow="Configurable, versionné, à faire valider">
      <div className="stack">
        <Callout kind="warn" title={d.pending_review ? `${d.pending_review} règle(s) active(s) à valider` : "Validation requise avant commercialisation"}>Ces valeurs sont des références tirées des sources officielles ci-dessous, pas un avis juridique. Le régime applicable dépend du contrat, du secteur et de la convention collective : il se choisit dans le contrat de chaque collaborateur.</Callout>
        {d.rules.length > 0 && (
          <div className="table-wrap"><table className="table table-cards" aria-label="Règles légales">
            <thead><tr><th>Règle</th><th>Régime</th><th>Valeur</th><th>Version</th><th>Validité</th><th>Validation</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{d.rules.map((r) => (
              <tr key={r.id}><td className="cell-main"><strong>{NAME[r.code] ?? r.code}</strong>{!r.enabled && <> <Badge>Inactive</Badge></>}</td><td data-label="Régime">{r.jurisdiction ?? "Général"}</td><td className="num" data-label="Valeur">{value(r)}</td><td className="num" data-label="Version">v{r.version}</td>
                <td className="num nowrap" data-label="Validité">{r.valid_from ?? "—"} → {r.valid_to ?? "—"}</td><td data-label="Validation"><Badge tone={TONE[r.review_status] ?? "warn"}>{r.review_label}{r.reviewed_by ? ` · ${r.reviewed_by}` : ""}</Badge></td>
                <td><div className="row">
                  {canReview && r.review_status !== "valide" && r.enabled && <Button size="sm" onClick={() => act(() => api(`/legal/rules/${r.id}/review`, { method: "POST", json: { status: "valide" } }), "Règle validée : votre nom et la date sont enregistrés.")}>Valider</Button>}
                  {canWrite && <Button size="sm" variant="ghost" onClick={() => act(() => api(`/legal/rules/${r.id}/enabled`, { method: "POST", json: { enabled: !r.enabled } }), r.enabled ? "Règle désactivée." : "Règle activée.")}>{r.enabled ? "Désactiver" : "Activer"}</Button>}
                </div></td></tr>))}</tbody>
          </table></div>)}
        <section aria-label="Modèles disponibles" className="stack" style={{ gap: "var(--sp-2)" }}>
          <h3 className="h2">Modèles à activer</h3>
          <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: "var(--sp-2)" }}>
            {d.templates.map((t) => (
              <li key={t.key} className="surface spread" style={{ padding: "var(--sp-3)" }}>
                <div style={{ minWidth: 0, flex: 1 }}><strong>{t.label}</strong><p className="help" style={{ margin: 0 }}>{t.note} <a href={t.source_url} target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>Source</a></p></div>
                {t.active ? <Badge tone="ok" icon="check">Activée</Badge> : canWrite && <Button size="sm" onClick={() => act(() => api("/legal/rules/from-template", { method: "POST", json: { template: t.key } }), "Règle activée : elle s'applique dès la prochaine génération et reste à valider.")}>Activer</Button>}
              </li>))}
          </ul>
        </section>
        <p className="help">Sources : {d.sources.map((s, i) => <span key={s.url}>{i > 0 && " · "}<a href={s.url} target="_blank" rel="noreferrer" style={{ textDecoration: "underline" }}>{s.label}</a></span>)}. Non exécutés à ce stade : travail de nuit, dimanche et repos compensatoires, jeunes travailleurs, conventions collectives particulières.</p>
      </div>
    </Card>
  );
}
