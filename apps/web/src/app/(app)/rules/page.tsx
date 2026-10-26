"use client";
import { FormEvent, useState } from "react";
import { Card, Page, useMe } from "@/components/Shell";
import { useApi } from "@/components/hooks";
import { api } from "@/lib/api";
import { t } from "@/lib/i18n";

type Rule = { id: string; kind: string; code: string; scope: string; params: any; jurisdiction: string | null; version: number; enabled: boolean; exception_reason: string | null; legal_review_status: string; enabled_by: string | null };
const KIND: Record<string, string> = { legal: "Règle légale", exception: "Dérogation autorisée", internal: "Règle interne", preference: "Préférence" };

export default function Rules() {
  const me = useMe();
  const rules = useApi<Rule[]>("/constraints");
  const [msg, setMsg] = useState("");
  async function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget);
    try {
      await api("/constraints", { method: "POST", json: { kind: f.get("kind"), code: f.get("code"), params: { value: Number(f.get("value")) }, jurisdiction: f.get("jur") || null, version: Number(f.get("ver") || 1), exception_reason: f.get("reason") || null } });
      setMsg("Règle enregistrée (à valider juridiquement)"); rules.reload();
    } catch (err: any) { setMsg(typeof err.detail === "string" ? err.message : "Données invalides (une dérogation exige un motif)"); }
  }
  const groups = ["legal", "exception", "internal", "preference"];
  return (
    <Page>
      <h1 className="mb-3 text-2xl font-semibold">{t("nav.rules")}</h1>
      <p className="tag-warn mb-3 text-sm">Contraintes dures et préférences sont distinctes : une préférence ne contourne jamais une contrainte dure.</p>
      {groups.map((g) => <Card key={g} title={KIND[g]}>
        <ul className="space-y-1 text-sm">{(rules.data ?? []).filter((r) => r.kind === g).map((r) =>
          <li key={r.id} className="surface p-2"><strong>{r.code}</strong> v{r.version} {JSON.stringify(r.params)} {r.jurisdiction && `· ${r.jurisdiction}`}
            {" "}· <span className="tag-warn">{r.legal_review_status === "a_valider" ? "validation juridique requise" : r.legal_review_status}</span>
            {r.exception_reason && <div className="muted">Motif : {r.exception_reason}{r.enabled_by ? ` (activée par ${r.enabled_by.slice(0, 8)})` : ""}</div>}</li>)}</ul></Card>)}
      {me.permissions.includes("rules.write") && <Card title="Ajouter / versionner une règle">
        <form onSubmit={add} className="grid gap-2 sm:grid-cols-3">
          <label className="text-sm">Type<select name="kind" className="input mt-1">{groups.map((g) => <option key={g} value={g}>{KIND[g]}</option>)}</select></label>
          <label className="text-sm">Code (ex. rest_hours)<input name="code" required className="input mt-1" /></label>
          <label className="text-sm">Valeur<input name="value" type="number" required className="input mt-1" /></label>
          <label className="text-sm">Juridiction (pays/canton/convention)<input name="jur" className="input mt-1" /></label>
          <label className="text-sm">Version<input name="ver" type="number" min={1} defaultValue={1} className="input mt-1" /></label>
          <label className="text-sm">Motif (obligatoire pour une dérogation)<input name="reason" className="input mt-1" /></label>
          <div><button className="btn btn-primary">Enregistrer</button> <span role="status">{msg}</span></div></form></Card>}
    </Page>
  );
}
