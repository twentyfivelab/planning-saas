"use client";
import { useEffect, useState } from "react";
import { Badge, Button, Callout, Card, EmptyState, Field, Input, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { useApi } from "@/components/hooks";
import { api } from "@/lib/api";
import { brandColor } from "@/lib/brand";
import { invalidate } from "@/lib/invalidate";
import { monthLabel } from "@/lib/months";
import { IntegrationModal, type Added } from "@/components/planning/IntegrationModal";

type Animation = { id: string; code: string; brands: { code: string; name: string }[]; start: string; end: string; break_minutes: number; weekdays: number[]; headcount: number; mandatory: boolean; valid_from: string | null; valid_to: string | null; shared_schedule: boolean; hypothesis: boolean };
type SiteRow = { code: string; name: string; archived: boolean; archived_from: string | null; animations: Animation[] };
type BrandRow = { code: string; name: string; group_code: string | null; archived: boolean; archived_from: string | null; authorized_employees: number; base_budget_minutes?: number | null };
type Catalog = { month: string | null; sites: SiteRow[]; brands: BrandRow[] };
type Emp = { id: string; name: string; active: boolean; brands: Record<string, string> };
const DOW = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

const err = (e: unknown) => (e instanceof Error ? e.message : "Opération impossible");

/**
 * Sites, marques et animations (marque + site + horaire + jours + nombre de personnes). Les codes sont stables : renommer ne change que
 * le nom affiché. Toute modification s'applique À PARTIR du mois choisi ; les mois précédents gardent leur configuration.
 */
export function SitesEditor({ month, canEdit }: { month: string; canEdit: boolean }) {
  const toast = useToast();
  const cat = useApi<Catalog>(`/catalog?month=${month}`);
  const [siteName, setSiteName] = useState(""); const [brandName, setBrandName] = useState(""); const [brandGroup, setBrandGroup] = useState("");
  const [auth, setAuth] = useState<BrandRow | null>(null);
  const [added, setAdded] = useState<Added | null>(null); // nouvelle marque : proposer son intégration aux plannings existants
  const groups = [...new Set((cat.data?.brands ?? []).map((b) => b.group_code).filter(Boolean))] as string[];
  const done = (msg: string) => { toast.push(msg, "ok"); cat.reload(); invalidate(); };
  async function run(f: () => Promise<unknown>, msg: string) { try { await f(); done(msg); } catch (e) { toast.push(err(e), "bad"); } }

  return (
    <div className="stack">
      <Callout kind="info" title={`Modifications à partir de ${monthLabel(month)}`}>Les horaires, jours et besoins modifiés ici s&apos;appliquent à partir de {monthLabel(month)}. Les mois précédents conservent leur configuration et leurs affectations ; renommer un site ou une marque ne change que le nom affiché.</Callout>
      {canEdit && (
        <div className="grid-2">
          <Card title="Ajouter un site">
            <form className="row" style={{ alignItems: "flex-end" }} onSubmit={(e) => { e.preventDefault(); if (siteName.trim()) void run(() => api("/catalog/sites", { method: "POST", json: { name: siteName.trim() } }), `Site « ${siteName.trim()} » créé.`).then(() => setSiteName("")); }}>
              <Field label="Nom du site">{(p) => <Input {...p} value={siteName} onChange={(e) => setSiteName(e.target.value)} placeholder="ex. GVA7" />}</Field>
              <Button type="submit" variant="primary" icon="plus" disabled={!siteName.trim()}>Ajouter le site</Button>
            </form>
          </Card>
          <Card title="Ajouter une marque">
            <form className="row" style={{ alignItems: "flex-end" }} onSubmit={(e) => { e.preventDefault(); if (brandName.trim()) void run(async () => { const b = await api<{ code: string; name: string }>("/catalog/brands", { method: "POST", json: { name: brandName.trim(), group_code: brandGroup || null } }); setAdded({ kind: "brand", code: b.code, name: b.name }); }, `Marque « ${brandName.trim()} » créée.`).then(() => setBrandName("")); }}>
              <Field label="Nom de la marque (ou marque + boutique)">{(p) => <Input {...p} value={brandName} onChange={(e) => setBrandName(e.target.value)} placeholder="ex. Ploom GVA7" />}</Field>
              <Field label="Groupe">{(p) => <Select {...p} value={brandGroup} onChange={(e) => setBrandGroup(e.target.value)}><option value="">Aucun</option>{groups.map((g) => <option key={g} value={g}>{g}</option>)}</Select>}</Field>
              <Button type="submit" variant="primary" icon="plus" disabled={!brandName.trim()}>Ajouter la marque</Button>
            </form>
          </Card>
        </div>
      )}
      {!cat.data ? <div className="skeleton" style={{ height: "12rem" }} aria-hidden="true" /> : (
        <>
          {cat.data.sites.map((s) => <SiteCard key={s.code} site={s} month={month} brands={cat.data!.brands} canEdit={canEdit} run={run} />)}
          <Card title="Marques et collaborateurs autorisés">
            <div className="table-wrap"><table className="table table-cards">
              <thead><tr><th>Marque</th><th>Groupe</th><th>Budget de base (h / mois)</th><th>Collaborateurs autorisés</th><th>Statut</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>{cat.data.brands.map((b) => (
                <tr key={b.code}>
                  <td className="cell-main"><span className="row" style={{ flexWrap: "nowrap" }}><i className="dot" style={{ ["--c" as string]: brandColor(b.code) }} /><strong>{b.name}</strong></span></td>
                  <td data-label="Groupe">{b.group_code ?? "—"}</td>
                  <td data-label="Budget de base"><BaseBudget b={b} canEdit={canEdit && !b.archived} run={run} /></td>
                  <td data-label="Autorisés" className="num">{b.authorized_employees}</td>
                  <td data-label="Statut">{b.archived ? <Badge>Archivée depuis {monthLabel(b.archived_from!.slice(0, 7))}</Badge> : <Badge tone="ok">Active</Badge>}</td>
                  <td>{canEdit && <div className="row" style={{ flexWrap: "nowrap" }}>
                    <Button size="sm" onClick={() => setAuth(b)}>Autoriser des collaborateurs</Button>
                    {b.archived ? <Button size="sm" onClick={() => run(() => api(`/catalog/brands/${encodeURIComponent(b.code)}`, { method: "PATCH", json: { archived_from: "" } }), `${b.name} réactivée.`)}>Réactiver</Button>
                      : <Button size="sm" onClick={() => run(() => api(`/catalog/brands/${encodeURIComponent(b.code)}`, { method: "PATCH", json: { archived_from: month } }), `${b.name} archivée à partir de ${monthLabel(month)}.`)}>Archiver</Button>}
                  </div>}</td>
                </tr>))}</tbody>
            </table></div>
          </Card>
        </>
      )}
      <IntegrationModal added={added} onClose={() => setAdded(null)} />
      <AuthorizeModal brand={auth} onClose={() => setAuth(null)} onDone={(n) => { setAuth(null); done(`${n} collaborateur(s) autorisé(s).`); }} />
    </div>
  );
}

function SiteCard({ site, month, brands, canEdit, run }: { site: SiteRow; month: string; brands: BrandRow[]; canEdit: boolean; run: (f: () => Promise<unknown>, msg: string) => Promise<void> }) {
  const [name, setName] = useState(site.name);
  const [adding, setAdding] = useState(false);
  const active = brands.filter((b) => !b.archived);
  return (
    <Card title={site.name} eyebrow={`Site · ${site.code}`} actions={<div className="row">
      {site.archived ? <Badge>Archivé depuis {monthLabel(site.archived_from!.slice(0, 7))}</Badge> : <Badge tone="ok">Actif</Badge>}
      {canEdit && (site.archived ? <Button size="sm" onClick={() => run(() => api(`/catalog/sites/${encodeURIComponent(site.code)}`, { method: "PATCH", json: { archived_from: "" } }), `${site.name} réactivé.`)}>Réactiver</Button>
        : <Button size="sm" onClick={() => run(() => api(`/catalog/sites/${encodeURIComponent(site.code)}`, { method: "PATCH", json: { archived_from: month } }), `${site.name} archivé à partir de ${monthLabel(month)} (les mois précédents restent intacts).`)}>Archiver à partir de {monthLabel(month)}</Button>)}
    </div>}>
      <div className="stack">
        {canEdit && (
          <form className="row" style={{ alignItems: "flex-end" }} onSubmit={(e) => { e.preventDefault(); void run(() => api(`/catalog/sites/${encodeURIComponent(site.code)}`, { method: "PATCH", json: { name } }), `Site renommé en « ${name} ».`); }}>
            <Field label="Nom affiché" help="Le code du site ne change jamais : affectations et paramètres sont conservés.">{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
            <Button type="submit" disabled={!name.trim() || name === site.name}>Renommer</Button>
          </form>
        )}
        {site.animations.length === 0 ? <EmptyState icon="briefcase" title="Aucune animation ce mois-ci">Ajoutez une marque, ses horaires, ses jours et le nombre de personnes nécessaires.</EmptyState> : (
          <div className="table-wrap"><table className="table table-cards" aria-label={`Animations de ${site.name}`}>
            <thead><tr><th>Marque</th><th>Horaire</th><th>Jours</th><th>Personnes</th><th>Obligatoire</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{site.animations.map((a) => <AnimationRow key={a.id} a={a} month={month} canEdit={canEdit} run={run} />)}</tbody>
          </table></div>
        )}
        {canEdit && !site.archived && (adding ? <NewAnimation site={site} brands={active} month={month} onCancel={() => setAdding(false)} run={run} onDone={() => setAdding(false)} />
          : <div><Button icon="plus" onClick={() => setAdding(true)}>Ajouter une animation</Button></div>)}
      </div>
    </Card>
  );
}

function Weekdays({ value, onChange, disabled, label }: { value: number[]; onChange: (v: number[]) => void; disabled?: boolean; label: string }) {
  return (
    <div className="row weekday-pick" role="group" aria-label={label}>
      {DOW.map((d, i) => (
        <label key={d} className="chip-check"><input type="checkbox" checked={value.includes(i)} disabled={disabled} onChange={(e) => onChange(e.target.checked ? [...value, i].sort() : value.filter((x) => x !== i))} /><span>{d}</span></label>
      ))}
    </div>
  );
}

function AnimationRow({ a, month, canEdit, run }: { a: Animation; month: string; canEdit: boolean; run: (f: () => Promise<unknown>, msg: string) => Promise<void> }) {
  const [v, setV] = useState({ start: a.start, end: a.end, weekdays: a.weekdays, headcount: a.headcount, mandatory: a.mandatory });
  const dirty = JSON.stringify(v) !== JSON.stringify({ start: a.start, end: a.end, weekdays: a.weekdays, headcount: a.headcount, mandatory: a.mandatory });
  const brand = a.brands.map((b) => b.name).join(" + ");
  return (
    <tr>
      <td className="cell-main"><span className="row" style={{ flexWrap: "nowrap" }}><i className="dot" style={{ ["--c" as string]: brandColor(a.brands[0]?.code ?? "") }} /><strong>{brand}</strong></span>
        {a.hypothesis && <Badge tone="warn">Horaire supposé</Badge>}{a.valid_from && <span className="faint"> depuis {monthLabel(a.valid_from.slice(0, 7))}</span>}</td>
      <td data-label="Horaire"><div className="row" style={{ flexWrap: "nowrap" }}>
        <Input aria-label={`Début ${brand}`} type="time" value={v.start} disabled={!canEdit} onChange={(e) => setV({ ...v, start: e.target.value })} style={{ width: "7rem" }} />–
        <Input aria-label={`Fin ${brand}`} type="time" value={v.end} disabled={!canEdit} onChange={(e) => setV({ ...v, end: e.target.value })} style={{ width: "7rem" }} /></div></td>
      <td data-label="Jours"><Weekdays label={`Jours ${brand} ${a.start}`} value={v.weekdays} disabled={!canEdit} onChange={(w) => setV({ ...v, weekdays: w })} /></td>
      <td data-label="Personnes"><Input aria-label={`Personnes ${brand} ${a.start}`} type="number" min={1} max={50} value={v.headcount} disabled={!canEdit} onChange={(e) => setV({ ...v, headcount: Math.max(1, Number(e.target.value) || 1) })} style={{ width: "5rem" }} /></td>
      <td data-label="Obligatoire"><input type="checkbox" aria-label={`Obligatoire ${brand} ${a.start}`} checked={v.mandatory} disabled={!canEdit} onChange={(e) => setV({ ...v, mandatory: e.target.checked })} /></td>
      <td>{canEdit && <div className="row" style={{ flexWrap: "nowrap" }}>
        <Button size="sm" variant="primary" disabled={!dirty || !v.weekdays.length} onClick={() => run(() => api(`/catalog/animations/${a.id}`, { method: "PATCH", json: { from_month: month, start: v.start, end: v.end, weekdays: v.weekdays, headcount: v.headcount, mandatory: v.mandatory } }), `${brand} : modification enregistrée à partir de ${monthLabel(month)}.`)}>Enregistrer</Button>
        <Button size="sm" onClick={() => run(() => api(`/catalog/animations/${a.id}?from_month=${month}`, { method: "DELETE" }), `${brand} ${a.start}–${a.end} arrêté à partir de ${monthLabel(month)}.`)}>Arrêter</Button>
      </div>}</td>
    </tr>
  );
}

function NewAnimation({ site, brands, month, onCancel, onDone, run }: { site: SiteRow; brands: BrandRow[]; month: string; onCancel: () => void; onDone: () => void; run: (f: () => Promise<unknown>, msg: string) => Promise<void> }) {
  const [v, setV] = useState({ brand_code: brands[0]?.code ?? "", start: "09:00", end: "18:00", break_minutes: 60, weekdays: [0, 1, 2, 3, 4], headcount: 1, mandatory: true });
  return (
    <form className="surface-2 stack" style={{ padding: "var(--sp-4)" }} aria-label={`Nouvelle animation — ${site.name}`}
      onSubmit={(e) => { e.preventDefault(); void run(() => api("/catalog/animations", { method: "POST", json: { site_code: site.code, ...v, from_month: month } }), `Animation ajoutée sur ${site.name} à partir de ${monthLabel(month)}.`).then(onDone); }}>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <Field label="Marque">{(p) => <Select {...p} value={v.brand_code} onChange={(e) => setV({ ...v, brand_code: e.target.value })}>{brands.map((b) => <option key={b.code} value={b.code}>{b.name}</option>)}</Select>}</Field>
        <Field label="Début">{(p) => <Input {...p} type="time" value={v.start} onChange={(e) => setV({ ...v, start: e.target.value })} />}</Field>
        <Field label="Fin">{(p) => <Input {...p} type="time" value={v.end} onChange={(e) => setV({ ...v, end: e.target.value })} />}</Field>
        <Field label="Pause (min)">{(p) => <Input {...p} type="number" min={0} max={240} value={v.break_minutes} onChange={(e) => setV({ ...v, break_minutes: Number(e.target.value) || 0 })} style={{ width: "6rem" }} />}</Field>
        <Field label="Personnes nécessaires">{(p) => <Input {...p} type="number" min={1} max={50} value={v.headcount} onChange={(e) => setV({ ...v, headcount: Math.max(1, Number(e.target.value) || 1) })} style={{ width: "6rem" }} />}</Field>
      </div>
      <div><p className="label">Jours d&apos;activité</p><Weekdays label="Jours d'activité" value={v.weekdays} onChange={(w) => setV({ ...v, weekdays: w })} /></div>
      <label className="row"><input type="checkbox" checked={v.mandatory} onChange={(e) => setV({ ...v, mandatory: e.target.checked })} /> Shift obligatoire <span className="faint">— sinon : optionnel, planifié selon le budget</span></label>
      <div className="row modal-actions"><Button onClick={onCancel}>Annuler</Button><Button type="submit" variant="primary" disabled={!v.brand_code || !v.weekdays.length}>Ajouter l&apos;animation</Button></div>
    </form>
  );
}

function AuthorizeModal({ brand, onClose, onDone }: { brand: BrandRow | null; onClose: () => void; onDone: (n: number) => void }) {
  const emps = useApi<Emp[]>(brand ? "/employees" : null);
  const [sel, setSel] = useState<string[]>([]); const [level, setLevel] = useState("priority"); const [busy, setBusy] = useState(false); const [e, setE] = useState("");
  const list = (emps.data ?? []).filter((x) => x.active && brand && !(brand.code in x.brands));
  async function save() {
    if (!brand) return; setBusy(true); setE("");
    try { const r = await api<{ authorized: string[] }>(`/catalog/brands/${encodeURIComponent(brand.code)}/authorize`, { method: "POST", json: { employee_ids: sel, level } }); setSel([]); onDone(r.authorized.length); }
    catch (x) { setE(err(x)); } finally { setBusy(false); }
  }
  return (
    <Modal open={!!brand} onClose={() => !busy && onClose()} title={brand ? `Autoriser sur ${brand.name}` : ""} description="Réglage permanent de la fiche (« Marques et boutiques autorisées »).">
      {brand && <div className="stack">
        {list.length === 0 ? <p className="muted">Tous les collaborateurs actifs sont déjà autorisés sur cette marque.</p> : (
          <ul className="check-list" aria-label="Collaborateurs à autoriser">{list.map((x) => (
            <li key={x.id}><label className="row"><input type="checkbox" checked={sel.includes(x.id)} onChange={(ev) => setSel(ev.target.checked ? [...sel, x.id] : sel.filter((i) => i !== x.id))} />{x.name}</label></li>))}</ul>)}
        <Field label="Priorité">{(p) => <Select {...p} value={level} onChange={(ev) => setLevel(ev.target.value)}><option value="priority">Prioritaire</option><option value="secondary">Secondaire</option><option value="reinforce">Renfort</option></Select>}</Field>
        {e && <Callout kind="bad">{e}</Callout>}
        <div className="row modal-actions"><Button onClick={onClose} disabled={busy}>Annuler</Button><Button variant="primary" onClick={save} disabled={busy || !sel.length}>Autoriser {sel.length || ""}</Button></div>
      </div>}
    </Modal>
  );
}


/** Budget de base d'une marque (heures de travail effectif par mois) : prérempli dans le budget de chaque NOUVEAU mois, ajustable mois par
 *  mois. Le modifier ne change jamais un mois déjà créé. Vide = non renseigné (rien n'est inventé). */
function BaseBudget({ b, canEdit, run }: { b: BrandRow; canEdit: boolean; run: (f: () => Promise<unknown>, msg: string) => Promise<void> }) {
  const cur = b.base_budget_minutes ?? null;
  const [h, setH] = useState(cur === null ? "" : String(cur / 60));
  useEffect(() => setH(cur === null ? "" : String(cur / 60)), [cur]);
  const commit = () => {
    const v = h.trim();
    if (v === "" && cur !== null) void run(() => api(`/catalog/brands/${encodeURIComponent(b.code)}`, { method: "PATCH", json: { clear_base_budget: true } }), `Budget de base de ${b.name} retiré.`);
    else if (v !== "" && Number(v) >= 0 && Math.round(Number(v) * 60) !== cur)
      void run(() => api(`/catalog/brands/${encodeURIComponent(b.code)}`, { method: "PATCH", json: { base_budget_hours: Number(v) } }), `Budget de base de ${b.name} : ${v} h (nouveaux mois uniquement).`);
  };
  return (
    <span className="row" style={{ flexWrap: "nowrap" }}>
      <Input aria-label={`Budget de base ${b.name} (heures par mois)`} type="number" min={0} step={0.5} value={h} disabled={!canEdit} placeholder="Non renseigné"
        onChange={(e) => setH(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") commit(); }} style={{ width: "7.5rem" }} />
      <span className="faint">h</span>
    </span>
  );
}
