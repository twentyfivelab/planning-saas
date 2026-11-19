"use client";
import { useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { MonthSwitcher } from "@/components/MonthSwitcher";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, Field, Input, PageHead, Select, SkeletonCard } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { t } from "@/lib/i18n";
import { errText } from "@/lib/wfm";

type V = { id: string; number: number; label: string | null; state: "snapshot" | "in_review" | "validated" | "published" | "superseded"; state_label: string; kind: string; kind_label: string; published: boolean; exploratory: boolean; created_at: string; assignments: number; created_by: string | null; validated_by: string | null; published_by: string | null; same_as_current: boolean; note: string | null; conformity?: Conformity; engine_version?: string | null; has_context?: boolean };
type Side = { status: "conforme" | "non_conforme" | "contexte_incomplet"; violations: number | null; preferences?: number; checked: number; unchecked: number; checked_at?: string; message?: string;
  items?: { code: string; rule: string; employee: string; reason: string }[] };
type Conformity = { creation: Side; current: Side | null };
type Cmp = { changed: { slot_key: string; from: string; to: string }[]; added: string[]; removed: string[]; unchanged: number };
const TONE = { snapshot: "neutral", in_review: "accent", validated: "ok", published: "ok", superseded: "neutral" } as const;
const fmt = (d: string) => new Date(d).toLocaleString("fr-CH", { timeZone: "Europe/Zurich", dateStyle: "short", timeStyle: "short" });

export default function Versions() {
  const me = useMe(); const toast = useToast();
  const { period, month, setMonth, reloadPeriods } = usePeriod();
  const v = useApi<V[]>(period ? `/periods/${period.id}/versions` : null);
  const can = (p: string) => me.permissions.includes(p);
  const [a, setA] = useState(""); const [b, setB] = useState(""); const [cmp, setCmp] = useState<Cmp | null>(null);
  const [purging, setPurging] = useState(false); const [resetting, setResetting] = useState(false); const [typed, setTyped] = useState("");
  const [label, setLabel] = useState(""); const [restoring, setRestoring] = useState<V | null>(null); const [publishing, setPublishing] = useState<V | null>(null); const [notify, setNotify] = useState(true);
  const refresh = () => { v.reload(); reloadPeriods(); invalidate(); };
  const [detail, setDetail] = useState<V | null>(null);
  async function act(fn: () => Promise<unknown>, msg: string) { try { await fn(); toast.push(msg, "ok"); refresh(); } catch (e) { toast.push(errText(e), "bad"); } }
  async function publish() {
    if (!publishing) return;
    const x = publishing; setPublishing(null);
    try { const r = await api<{ notifications: number }>(`/versions/${x.id}/publish`, { method: "POST", json: { notify } }); toast.push(`Version ${x.number} publiée${r.notifications ? ` : ${r.notifications} collaborateur(s) notifié(s)` : ""}.`, "ok"); refresh(); }
    catch (e) { toast.push(errText(e), "bad"); }
  }
  async function restore() {
    if (!restoring) return;
    const x = restoring; setRestoring(null);
    try { const r = await api<{ changed: number; skipped: number; safety_version: number }>(`/versions/${x.id}/restore`, { method: "POST" }); toast.push(`Version ${x.number} restaurée : ${r.changed} affectation(s) rétablie(s). État précédent copié en version ${r.safety_version}.`, r.skipped ? "warn" : "ok"); refresh(); }
    catch (e) { toast.push(errText(e), "bad"); }
  }
  return (
    <>
      <PageHead eyebrow={period ? `${period.name} · ${period.status_label ?? ""}` : undefined} title={t("nav.versions")}><MonthSwitcher month={month} onChange={setMonth} /></PageHead>
      {period?.changed_since && <Callout kind="warn" title="Planning modifié depuis sa validation ou sa publication">La version officielle reste conservée. Créez une nouvelle version puis validez-la et publiez-la pour communiquer ces changements.</Callout>}
      {!period ? <Card><EmptyState icon="history" title="Aucun planning pour ce mois">Générez d&apos;abord le planning de ce mois.</EmptyState></Card> : v.error ? <ErrorState message={v.error} onRetry={v.reload} /> : v.loading && !v.data ? <SkeletonCard lines={4} /> : (
        <>
          <Card title="Historique des versions" actions={can("planning.edit") ? <form className="row" onSubmit={async (e) => { e.preventDefault(); await act(() => api(`/periods/${period.id}/versions`, { method: "POST", json: { label: label.trim() || null } }), "Version créée."); setLabel(""); }}><Input aria-label="Libellé de la version" placeholder="ex. Planning corrigé" value={label} maxLength={100} onChange={(e) => setLabel(e.target.value)} style={{ width: "13rem" }} /><Button type="submit" variant="primary" icon="plus">Nouvelle version</Button></form> : undefined}>
            {!v.data?.length ? <EmptyState icon="history" title="Aucune version">Une version est créée à chaque génération ; vous pouvez aussi en enregistrer une à tout moment.</EmptyState> : (
              <div className="table-wrap"><table className="table table-cards" aria-label="Versions"><thead><tr><th>N°</th><th>Libellé</th><th>Origine</th><th>Créée le</th><th>Affectations</th><th>Conformité</th><th>État</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>{[...v.data].reverse().map((x) => (
                  <tr key={x.id}><td className="num cell-main"><strong>v{x.number}</strong></td><td data-label="Libellé">{x.label ?? <span className="faint">—</span>}{x.same_as_current && <> <Badge tone="info">Planning actuel</Badge></>}</td><td data-label="Origine">{x.kind_label}{x.created_by ? ` · ${x.created_by}` : ""}</td><td className="num nowrap" data-label="Créée le">{fmt(x.created_at)}</td><td className="num" data-label="Affectations">{x.assignments}</td>
                    <td data-label="Conformité"><ConformityCell x={x} onDetail={() => setDetail(x)} /></td>
                    <td data-label="État"><div className="row"><Badge tone={TONE[x.state]} icon={x.state === "published" || x.state === "validated" ? "check" : undefined}>{x.state_label}</Badge>{x.exploratory && <Badge tone="warn" icon="alert">Données incomplètes · non publiable</Badge>}</div></td>
                    <td><div className="row">
                      {x.state === "snapshot" && can("planning.edit") && x.same_as_current && <Button size="sm" onClick={() => act(() => api(`/versions/${x.id}/submit`, { method: "POST" }), "Version soumise à validation.")}>Soumettre</Button>}
                      {(x.state === "snapshot" || x.state === "in_review") && can("planning.validate") && x.same_as_current && <Button size="sm" onClick={() => act(() => api(`/versions/${x.id}/validate`, { method: "POST" }), "Version validée.")}>Valider</Button>}
                      {x.state !== "published" && x.state !== "superseded" && can("planning.publish") && x.same_as_current && <Button size="sm" variant="primary" onClick={() => { setNotify(true); setPublishing(x); }}>Publier</Button>}
                      {can("planning.edit") && !x.same_as_current && <Button size="sm" onClick={() => setRestoring(x)}>Restaurer</Button>}
                      {can("planning.edit") && x.state === "snapshot" && x.kind === "manual" && <Button size="sm" variant="ghost" onClick={() => act(async () => { await api(`/versions/${x.id}`, { method: "DELETE" }); v.mutate((v.data ?? []).filter((y) => y.id !== x.id)); }, "Copie de travail supprimée.")} aria-label={`Supprimer la version ${x.number}`}>Supprimer</Button>}
                    </div></td></tr>))}</tbody></table></div>
            )}
          </Card>
          {can("planning.admin") && (
            <Card title="Administration du mois" eyebrow="Réservé aux propriétaires et administrateurs">
              <div className="row">
                <Button onClick={() => setPurging(true)}>Retirer les copies automatiques</Button>
                <Button variant="danger" onClick={() => { setTyped(""); setResetting(true); }}>Remettre ce mois à zéro</Button>
              </div>
              <p className="help" style={{ marginTop: "var(--sp-2)" }}>La durée de conservation des copies automatiques se règle dans <a href="/settings" style={{ textDecoration: "underline" }}>Paramètres</a>.</p>
            </Card>)}
          <Card title="Comparer deux versions">
            <div className="row" style={{ alignItems: "flex-end" }}>
              <Field label="Version A">{(p) => <Select {...p} value={a} onChange={(e) => setA(e.target.value)} style={{ minWidth: "9rem" }}><option value="">Choisir…</option>{v.data?.map((x) => <option key={x.id} value={x.id}>v{x.number}{x.label ? ` — ${x.label}` : ""}</option>)}</Select>}</Field>
              <Field label="Version B">{(p) => <Select {...p} value={b} onChange={(e) => setB(e.target.value)} style={{ minWidth: "9rem" }}><option value="">Choisir…</option>{v.data?.map((x) => <option key={x.id} value={x.id}>v{x.number}{x.label ? ` — ${x.label}` : ""}</option>)}</Select>}</Field>
              <Button variant="primary" disabled={!a || !b} onClick={async () => setCmp(await api<Cmp>(`/versions/compare?a=${a}&b=${b}`))}>Comparer</Button>
            </div>
            {cmp && (
              <div className="stack" style={{ marginTop: "var(--sp-4)" }} aria-live="polite">
                <div className="row"><Badge tone="accent">{cmp.changed.length} modifiée(s)</Badge><Badge tone="ok">{cmp.added.length} ajoutée(s)</Badge><Badge tone="bad">{cmp.removed.length} retirée(s)</Badge><Badge>{cmp.unchanged} inchangée(s)</Badge></div>
                {cmp.changed.length > 0 && <div className="table-wrap"><table className="table"><thead><tr><th>Shift</th><th>Avant</th><th>Après</th></tr></thead><tbody>{cmp.changed.slice(0, 30).map((c) => <tr key={c.slot_key}><td>{c.slot_key}</td><td>{c.from}</td><td><strong>{c.to}</strong></td></tr>)}</tbody></table></div>}
              </div>
            )}
          </Card>
        </>
      )}
      <Modal open={purging} onClose={() => setPurging(false)} title="Retirer les copies automatiques ?" variant="confirm" description={period?.name}>
        <div className="stack">
          <p>Les versions « Avant génération » et « Planning généré » de ce mois seront retirées. Le planning, les copies manuelles et toute version soumise, validée ou publiée restent.</p>
          <div className="row modal-actions"><Button onClick={() => setPurging(false)}>Annuler</Button><Button variant="primary" onClick={async () => { setPurging(false); await act(() => api(`/periods/${period!.id}/versions/purge-automatic`, { method: "POST", json: { confirm: true } }), "Copies automatiques retirées."); }}>Retirer</Button></div>
        </div>
      </Modal>
      <Modal open={resetting} onClose={() => setResetting(false)} title={`Remettre ${period?.name ?? "ce mois"} à zéro ?`} variant="confirm" description="Cette opération ne s'annule pas.">
        <div className="stack">
          <p>Seront retirés pour ce mois : affectations, shifts, calculs, versions, heures saisies, effectif, marques et sites du mois, budgets et paramètres mensuels. Les autres mois, les fiches et les indisponibilités ne changent pas.</p>
          <Field label={`Saisissez « ${period?.name ?? ""} » pour confirmer`}>{(p) => <Input {...p} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />}</Field>
          <div className="row modal-actions"><Button onClick={() => setResetting(false)}>Annuler</Button><Button variant="danger" disabled={typed.trim() !== period?.name} onClick={async () => { setResetting(false); await act(() => api(`/periods/${period!.id}/reset`, { method: "POST", json: { confirm_name: typed.trim() } }), `${period!.name} remis à zéro.`); }}>Remettre à zéro</Button></div>
        </div>
      </Modal>
      <Modal open={!!publishing} onClose={() => setPublishing(null)} title={`Publier la version ${publishing?.number ?? ""} ?`} variant="confirm" description="La publication rend ce planning visible par les collaborateurs concernés.">
        <div className="stack">
          <label className="row"><input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} /> Notifier les collaborateurs concernés <span className="faint">— une seule notification par personne</span></label>
          <div className="row modal-actions"><Button onClick={() => setPublishing(null)}>Annuler</Button><Button variant="primary" onClick={publish}>Publier</Button></div>
        </div>
      </Modal>
      <Modal open={!!restoring} onClose={() => setRestoring(null)} title={`Restaurer la version ${restoring?.number ?? ""} ?`} variant="confirm" description="Le planning reprend l'état de cette version, en une seule opération.">
        <div className="stack">
          <p>L&apos;état actuel est d&apos;abord copié dans une nouvelle version : vous pourrez revenir en arrière. Les versions validées ou publiées ne sont jamais modifiées.</p>
          <div className="row modal-actions"><Button onClick={() => setRestoring(null)}>Annuler</Button><Button variant="primary" onClick={restore}>Restaurer</Button></div>
        </div>
      </Modal>
      {detail && <ConformityModal v={detail} onClose={() => setDetail(null)} />}
    </>
  );
}


function sideBadge(side: Side | null | undefined, label: string) {
  if (!side) return null;
  if (side.status === "contexte_incomplet") return <Badge tone="neutral" icon="info">{label} : contexte incomplet</Badge>;
  return side.status === "conforme"
    ? <Badge tone="ok" icon="check">{label} : conforme</Badge>
    : <Badge tone="warn" icon="alert">{label} : {side.violations} règle(s) non respectée(s)</Badge>;
}

/** Conformité informative : aux règles de la création (contexte figé de la version) et aux règles actuelles (date de vérification). */
function ConformityCell({ x, onDetail }: { x: V; onDetail: () => void }) {
  const c = x.conformity;
  if (!c) return <span className="faint">—</span>;
  return (
    <div className="stack" style={{ gap: "var(--sp-1)" }} data-testid={`conformity-v${x.number}`}>
      {sideBadge(c.creation, "Règles de création")}
      {sideBadge(c.current, `Règles actuelles${c.current?.checked_at ? ` (${fmt(c.current.checked_at)})` : ""}`)}
      <button type="button" className="link-btn" onClick={onDetail}>Détail</button>
    </div>
  );
}

function ConformityModal({ v, onClose }: { v: V; onClose: () => void }) {
  const d = useApi<Conformity & { engine_version: string | null; params: { mode: string; frozen_at: string | null } | null }>(`/versions/${v.id}/conformity`);
  const block = (title: string, side: Side | null | undefined) => side && (
    <section className="stack" style={{ gap: "var(--sp-2)" }}>
      <h3 className="h2" style={{ margin: 0 }}>{title}</h3>
      {side.status === "contexte_incomplet" ? <Callout kind="info" title="Contexte incomplet">{side.message}</Callout>
        : side.status === "conforme" ? <p style={{ margin: 0 }}>{sideBadge(side, "Conforme")} <span className="help">{side.checked} affectation(s) vérifiée(s){side.unchecked ? `, ${side.unchecked} hors de ces données` : ""}.</span></p>
        : <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{(side.items ?? []).map((i, n) => <li key={n}><strong>{i.employee}</strong> · {i.rule} — {i.reason}</li>)}</ul>}
    </section>
  );
  return (
    <Modal open onClose={onClose} title={`Conformité de la version ${v.number}`} description="Information uniquement : ni les affectations, ni le statut, ni les paramètres enregistrés ne sont modifiés.">
      <div className="stack">
        {!d.data ? <div className="skeleton" style={{ height: "6rem" }} aria-hidden="true" /> : (
          <>
            {block(`Règles utilisées lors de la création${d.data.engine_version ? ` (moteur ${d.data.engine_version})` : ""}`, d.data.creation)}
            {block(`Règles actuelles — vérifié le ${d.data.current?.checked_at ? fmt(d.data.current.checked_at) : "—"}`, d.data.current)}
          </>
        )}
        <div className="row modal-actions"><Button variant="primary" onClick={onClose}>Fermer</Button></div>
      </div>
    </Modal>
  );
}
