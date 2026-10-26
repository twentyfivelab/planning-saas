"use client";
import { FormEvent } from "react";
import { useMe } from "@/components/Shell";
import { useApi } from "@/components/hooks";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, Field, Input, PageHead, Select, SkeletonCard } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type Rule = { id: string; kind: string; code: string; scope: string; params: unknown; jurisdiction: string | null; version: number; exception_reason: string | null; legal_review_status: string; enabled_by: string | null };
const PARAM_LABEL: Record<string, string> = { value: "Valeur", tags: "Shifts interdits", days: "Jours" };
function fmtParams(p: unknown): string {
  if (!p || typeof p !== "object") return "";
  return Object.entries(p as Record<string, unknown>).map(([k, v]) => `${PARAM_LABEL[k] ?? k} : ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(" · ");
}
const KIND: Record<string, string> = { legal: "Règles légales", exception: "Dérogations autorisées", internal: "Règles internes", preference: "Préférences" };
const HINT: Record<string, string> = { legal: "Valeurs de référence, versionnées par juridiction et période.", exception: "Exigent un motif ; l'activateur est enregistré.", internal: "Propres à l'entreprise.", preference: "Souples : ne contournent jamais une contrainte dure." };

export default function Rules() {
  const me = useMe(); const toast = useToast();
  const rules = useApi<Rule[]>("/constraints");
  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = e.currentTarget; const f = new FormData(form);
    try {
      await api("/constraints", { method: "POST", json: { kind: f.get("kind"), code: f.get("code"), params: { value: Number(f.get("value")) }, jurisdiction: f.get("jur") || null, version: Number(f.get("ver") || 1), exception_reason: f.get("reason") || null } });
      toast.push("Règle enregistrée — validation juridique requise.", "ok"); form.reset(); rules.reload();
    } catch (err: any) { toast.push(typeof err.detail === "string" ? err.message : "Données invalides (une dérogation exige un motif).", "bad"); }
  }
  return (
    <>
      <PageHead eyebrow="Légal · dérogations · interne · préférences" title={t("nav.rules")} />
      <Callout kind="warn" title="Non commercialisable en l'état">Seuls le repos quotidien (11 h) et les 6 jours consécutifs sont exécutés, comme valeurs de référence non validées. Les autres règles légales suisses ne sont pas exécutées. Une préférence ne contourne jamais une contrainte dure.</Callout>
      {rules.error ? <ErrorState message={rules.error} onRetry={rules.reload} /> : rules.loading && !rules.data ? <SkeletonCard lines={5} /> : (
        <div className="grid-2">
          {Object.keys(KIND).map((g) => {
            const list = (rules.data ?? []).filter((r) => r.kind === g);
            return (
              <Card key={g} title={KIND[g]} actions={<Badge>{list.length}</Badge>}>
                <p className="help" style={{ marginTop: "calc(var(--sp-2) * -1)", marginBottom: "var(--sp-3)" }}>{HINT[g]}</p>
                {!list.length ? <EmptyState icon="shield" title="Aucune règle" /> : (
                  <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>{list.map((r) => (
                    <li key={r.id} className="surface" style={{ padding: "var(--sp-3)" }}>
                      <div className="spread"><strong>{r.code}</strong><span className="row"><Badge>v{r.version}</Badge>{r.legal_review_status === "a_valider" && <Badge tone="warn" icon="alert">Validation juridique requise</Badge>}</span></div>
                      <p className="muted">{fmtParams(r.params)}{r.jurisdiction ? ` · ${r.jurisdiction}` : ""}{r.scope === "employee" ? " · règle individuelle" : ""}</p>
                      {r.exception_reason && <p className="help">Motif : {r.exception_reason}{r.enabled_by ? ` (activée par ${r.enabled_by.slice(0, 8)})` : ""}</p>}
                    </li>))}</ul>)}
              </Card>
            );
          })}
        </div>
      )}
      {me.permissions.includes("rules.write") && (
        <Card title="Ajouter ou versionner une règle">
          <form onSubmit={add} className="toolbar">
            <Field label="Type">{(p) => <Select {...p} name="kind">{Object.entries(KIND).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select>}</Field>
            <Field label="Code" help="Ex. rest_hours">{(p) => <Input {...p} name="code" required />}</Field>
            <Field label="Valeur">{(p) => <Input {...p} name="value" type="number" required />}</Field>
            <Field label="Juridiction" help="Pays, canton, convention">{(p) => <Input {...p} name="jur" />}</Field>
            <Field label="Version">{(p) => <Input {...p} name="ver" type="number" min={1} defaultValue={1} />}</Field>
            <Field label="Motif" help="Obligatoire pour une dérogation">{(p) => <Input {...p} name="reason" />}</Field>
            <div><Button type="submit" variant="primary" icon="plus">Enregistrer</Button></div>
          </form>
        </Card>
      )}
    </>
  );
}
