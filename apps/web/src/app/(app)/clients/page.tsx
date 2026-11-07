"use client";
import { useEffect, useMemo, useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi } from "@/components/hooks";
import { SimulationPreview } from "@/components/planning/SimulationPreview";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, Field, Input, PageHead, SearchInput, Select, SkeletonCard } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { MISSION_STATUS, PRIORITY_LABEL, SKILL_CATEGORY, WEEKDAYS, errText, fmtCHF, fmtH, parseRate, rateInput } from "@/lib/wfm";

type Contact = { name: string; role?: string | null; email?: string | null; phone?: string | null };
type Contract = { id: string; reference: string; start_date: string | null; end_date: string | null; ordered_minutes: number | null; billing_rate_cents: number | null };
type Client = { id: string; code: string; name: string; legal_name: string | null; contacts: Contact[]; billing_rate_cents: number | null; notes: string | null; archived: boolean; brands: { code: string; name: string; billing_rate_cents: number | null }[]; missions: Record<string, number>; contracts: Contract[] };
type Mission = { id: string; code: string; client_id: string; client_name: string; brand_code: string; title: string; site_codes: string[]; start_date: string; end_date: string; weekdays: number[]; start_time: string; end_time: string; break_minutes: number; headcount: number; required_skills: string[]; budget_minutes: number | null; billing_rate_cents: number | null; priority: number; status: string; notes: string | null; days: number; shifts_needed: number; minutes_needed: number; shifts_generated: number; shifts_assigned: number; minutes_assigned: number };
type Catalog = { sites: { code: string; name: string; archived: boolean }[]; brands: { code: string; name: string; archived: boolean }[] };
type Skill = { id: string; code: string; name: string; category: string };
type Elig = { eligible: number; headcount: number; warning: string | null; employees: { employee_id: string; name: string; eligible: boolean; brand_level: string | null; available_days: number; total_days: number; reasons: string[] }[] };
type Impact = { count: number; assigned: number; shifts: { shift_id: string; day: string; site: string; start: string; end: string; employee: string | null; past: boolean }[] };
type Period = { id: string; name: string; start_date: string; end_date: string; status: string };

const hm = (t: string) => t.slice(0, 5);

export default function ClientsAndMissions() {
  const me = useMe();
  const canWrite = me.permissions.includes("referential.write");
  const [tab, setTab] = useState<"missions" | "clients" | "skills">("missions");
  const clients = useApi<Client[]>("/clients");
  const missions = useApi<Mission[]>("/missions");
  const catalog = useApi<Catalog>("/catalog");
  const skills = useApi<Skill[]>("/skills");
  return (
    <>
      <PageHead eyebrow="Demandes de personnel" title="Clients et missions" />
      <div className="seg" role="tablist" aria-label="Clients et missions">
        {([["missions", "Missions"], ["clients", "Clients"], ["skills", "Qualifications"]] as const).map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={tab === k} className="btn" onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === "missions" && <Missions q={missions} clients={clients.data ?? []} catalog={catalog.data} skills={skills.data ?? []} canWrite={canWrite} canOptimize={me.permissions.includes("planning.optimize")} canSeeEmployees={me.permissions.includes("employees.read")} />}
      {tab === "clients" && <Clients q={clients} brands={catalog.data?.brands ?? []} canWrite={canWrite} />}
      {tab === "skills" && <Skills q={skills} canWrite={canWrite} />}
    </>
  );
}

// ---- clients ----
function Clients({ q, brands, canWrite }: { q: ReturnType<typeof useApi<Client[]>>; brands: Catalog["brands"]; canWrite: boolean }) {
  const toast = useToast();
  const [edit, setEdit] = useState<Client | "new" | null>(null);
  const [text, setText] = useState("");
  const rows = (q.data ?? []).filter((c) => !text || c.name.toLowerCase().includes(text.toLowerCase()));
  return (
    <>
      <Card title="Entreprises clientes" actions={<div className="row"><div style={{ width: "14rem" }}><SearchInput aria-label="Rechercher un client" placeholder="Rechercher…" value={text} onChange={(e) => setText(e.target.value)} /></div>{canWrite && <Button variant="primary" icon="plus" onClick={() => setEdit("new")}>Nouveau client</Button>}</div>}>
        {q.error ? <ErrorState message={q.error} onRetry={q.reload} /> : q.loading && !q.data ? <SkeletonCard lines={4} /> : !rows.length ? <EmptyState icon="briefcase" title="Aucun client">Enregistrez vos entreprises clientes pour y rattacher marques, contrats et missions.</EmptyState> : (
          <div className="table-wrap"><table className="table table-cards" aria-label="Clients">
            <thead><tr><th>Client</th><th>Marques</th><th>Responsables</th><th>Tarif horaire</th><th>Missions</th><th>État</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{rows.map((c) => (
              <tr key={c.id}><td className="cell-main"><strong>{c.name}</strong><span className="faint"> · {c.code}</span></td>
                <td data-label="Marques"><div className="row">{c.brands.length ? c.brands.map((b) => <Badge key={b.code}>{b.name}</Badge>) : <span className="faint">Aucune</span>}</div></td>
                <td data-label="Responsables">{c.contacts.map((x) => x.name).join(", ") || <span className="faint">Non renseigné</span>}</td>
                <td className="num nowrap" data-label="Tarif horaire">{fmtCHF(c.billing_rate_cents) ?? <span className="faint">Non renseigné</span>}</td>
                <td data-label="Missions"><div className="row">{Object.entries(c.missions).map(([s, n]) => <Badge key={s} tone={MISSION_STATUS[s]?.tone ?? "neutral"}>{n} {MISSION_STATUS[s]?.label.toLowerCase() ?? s}</Badge>)}{!Object.keys(c.missions).length && <span className="faint">Aucune</span>}</div></td>
                <td data-label="État">{c.archived ? <Badge>Archivé</Badge> : <Badge tone="ok">Actif</Badge>}</td>
                <td><Button size="sm" onClick={() => setEdit(c)} aria-label={`Modifier ${c.name}`}>{canWrite ? "Modifier" : "Voir"}</Button></td></tr>))}</tbody>
          </table></div>
        )}
      </Card>
      {edit && <ClientModal client={edit === "new" ? null : edit} brands={brands} canWrite={canWrite} onClose={() => setEdit(null)} onSaved={(m) => { toast.push(m, "ok"); q.reload(); invalidate(); }} />}
    </>
  );
}

function ClientModal({ client, brands, canWrite, onClose, onSaved }: { client: Client | null; brands: Catalog["brands"]; canWrite: boolean; onClose: () => void; onSaved: (m: string) => void }) {
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const [contacts, setContacts] = useState<Contact[]>(client?.contacts ?? []);
  const [linked, setLinked] = useState<string[]>(client?.brands.map((b) => b.code) ?? []);
  async function save(f: FormData) {
    setBusy(true); setErr("");
    try {
      const body = { name: String(f.get("name")), legal_name: String(f.get("legal") || "") || null, billing_rate_cents: parseRate(f.get("rate")), notes: String(f.get("notes") || "") || null, contacts: contacts.filter((c) => c.name.trim()) };
      const saved = client ? await api<Client>(`/clients/${client.id}`, { method: "PUT", json: body }) : await api<Client>("/clients", { method: "POST", json: body });
      const before = client?.brands.map((b) => b.code) ?? [];
      for (const code of brands.map((b) => b.code)) {
        if (linked.includes(code) && !before.includes(code)) await api(`/catalog/brands/${encodeURIComponent(code)}/client`, { method: "PUT", json: { client_id: saved.id } });
        if (!linked.includes(code) && before.includes(code)) await api(`/catalog/brands/${encodeURIComponent(code)}/client`, { method: "PUT", json: { client_id: null } });
      }
      onSaved(client ? `${saved.name} enregistré.` : `Client ${saved.name} créé.`); onClose();
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function addContract(f: FormData, form: HTMLFormElement) {
    if (!client) return;
    try {
      const hours = String(f.get("hours") || "");
      await api(`/clients/${client.id}/contracts`, { method: "POST", json: { reference: String(f.get("ref")), start_date: f.get("start") || null, end_date: f.get("end") || null, ordered_minutes: hours ? Math.round(Number(hours) * 60) : null, billing_rate_cents: parseRate(f.get("rate")) } });
      form.reset(); onSaved("Contrat commercial ajouté."); onClose();
    } catch (e) { setErr(errText(e)); }
  }
  return (
    <Modal open onClose={onClose} title={client ? `Client — ${client.name}` : "Nouveau client"} description="Laissez vide ce qui n'est pas connu : aucun tarif n'est supposé.">
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void save(new FormData(e.currentTarget)); }}>
        <div className="toolbar">
          <Field label="Nom">{(p) => <Input {...p} name="name" required maxLength={200} defaultValue={client?.name} disabled={!canWrite} />}</Field>
          <Field label="Raison sociale">{(p) => <Input {...p} name="legal" maxLength={200} defaultValue={client?.legal_name ?? ""} disabled={!canWrite} />}</Field>
          <Field label="Tarif horaire (CHF)" help="Tarif de facturation par défaut">{(p) => <Input {...p} name="rate" inputMode="decimal" defaultValue={rateInput(client?.billing_rate_cents)} disabled={!canWrite} />}</Field>
        </div>
        <fieldset className="plain-fieldset"><legend className="label">Marques de ce client</legend>
          <div className="row">{brands.filter((b) => !b.archived).map((b) => <label key={b.code} className="chip-check"><input type="checkbox" disabled={!canWrite} checked={linked.includes(b.code)} onChange={(e) => setLinked(e.target.checked ? [...linked, b.code] : linked.filter((x) => x !== b.code))} /><span>{b.name}</span></label>)}</div>
        </fieldset>
        <fieldset className="plain-fieldset"><legend className="label">Responsables</legend>
          <div className="stack" style={{ gap: "var(--sp-2)" }}>
            {contacts.map((c, i) => (
              <div key={i} className="toolbar" role="group" aria-label={`Responsable ${i + 1}`}>
                {(["name", "role", "email", "phone"] as const).map((k) => <Input key={k} aria-label={{ name: "Nom", role: "Fonction", email: "E-mail", phone: "Téléphone" }[k]} placeholder={{ name: "Nom", role: "Fonction", email: "E-mail", phone: "Téléphone" }[k]} value={c[k] ?? ""} disabled={!canWrite} onChange={(e) => setContacts(contacts.map((x, n) => (n === i ? { ...x, [k]: e.target.value } : x)))} />)}
              </div>))}
            {canWrite && <div><Button size="sm" icon="plus" onClick={() => setContacts([...contacts, { name: "" }])}>Ajouter un responsable</Button></div>}
          </div>
        </fieldset>
        <Field label="Notes et règles opérationnelles">{(p) => <textarea {...p} name="notes" className="input" rows={3} maxLength={4000} defaultValue={client?.notes ?? ""} disabled={!canWrite} />}</Field>
        {err && <Callout kind="bad" title="Enregistrement impossible">{err}</Callout>}
        <div className="row modal-actions">{client && canWrite && !Object.keys(client.missions).length && <Button variant="ghost" onClick={async () => { try { await api(`/clients/${client.id}`, { method: "DELETE" }); onSaved("Client supprimé."); onClose(); } catch (e) { setErr(errText(e)); } }}>Supprimer</Button>}{client && canWrite && <Button onClick={async () => { await api(`/clients/${client.id}/archive`, { method: "POST", json: { archived: !client.archived } }); onSaved(client.archived ? "Client réactivé." : "Client archivé : ses missions et plannings restent consultables."); onClose(); }}>{client.archived ? "Réactiver" : "Archiver"}</Button>}<Button onClick={onClose}>Fermer</Button>{canWrite && <Button type="submit" variant="primary" disabled={busy} aria-busy={busy}>Enregistrer</Button>}</div>
      </form>
      {client && (
        <section className="stack" aria-label="Contrats commerciaux" style={{ marginTop: "var(--sp-3)" }}>
          <h3 className="h2">Contrats commerciaux</h3>
          {client.contracts.length > 0 && <div className="table-wrap"><table className="table"><thead><tr><th>Référence</th><th>Période</th><th>Heures commandées</th><th>Tarif</th></tr></thead><tbody>{client.contracts.map((k) => <tr key={k.id}><td>{k.reference}</td><td className="num">{k.start_date ?? "—"} → {k.end_date ?? "—"}</td><td className="num">{k.ordered_minutes === null ? "—" : fmtH(k.ordered_minutes)}</td><td className="num">{fmtCHF(k.billing_rate_cents) ?? "—"}</td></tr>)}</tbody></table></div>}
          {canWrite && <form className="toolbar" aria-label="Nouveau contrat commercial" onSubmit={(e) => { e.preventDefault(); void addContract(new FormData(e.currentTarget), e.currentTarget); }}>
            <Field label="Référence">{(p) => <Input {...p} name="ref" required maxLength={100} />}</Field>
            <Field label="Début">{(p) => <Input {...p} name="start" type="date" />}</Field>
            <Field label="Fin">{(p) => <Input {...p} name="end" type="date" />}</Field>
            <Field label="Heures commandées">{(p) => <Input {...p} name="hours" type="number" min={0} step="any" />}</Field>
            <Field label="Tarif (CHF/h)">{(p) => <Input {...p} name="rate" inputMode="decimal" />}</Field>
            <div style={{ alignSelf: "end" }}><Button type="submit" icon="plus">Ajouter le contrat</Button></div>
          </form>}
        </section>)}
    </Modal>
  );
}

// ---- missions ----
function Missions({ q, clients, catalog, skills, canWrite, canOptimize, canSeeEmployees }: { q: ReturnType<typeof useApi<Mission[]>>; clients: Client[]; catalog: Catalog | null; skills: Skill[]; canWrite: boolean; canOptimize: boolean; canSeeEmployees: boolean }) {
  const toast = useToast();
  const [status, setStatus] = useState(""); const [client, setClient] = useState("");
  const [form, setForm] = useState<Mission | "new" | null>(null);
  const [open, setOpen] = useState<Mission | null>(null);
  const rows = (q.data ?? []).filter((m) => (!status || m.status === status) && (!client || m.client_id === client));
  const current = open ? q.data?.find((m) => m.id === open.id) ?? open : null;
  const noClient = !clients.length;
  return (
    <>
      <Card title="Missions" actions={canWrite ? <Button variant="primary" icon="plus" disabled={noClient} onClick={() => setForm("new")}>Nouvelle mission</Button> : undefined}>
        {noClient && canWrite && <Callout kind="info">Enregistrez d&apos;abord un client dans l&apos;onglet « Clients ».</Callout>}
        <div className="toolbar" role="search" aria-label="Filtres des missions" style={{ marginBottom: "var(--sp-3)" }}>
          <Field label="Statut">{(p) => <Select {...p} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Tous les statuts</option>{Object.entries(MISSION_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</Select>}</Field>
          <Field label="Client">{(p) => <Select {...p} value={client} onChange={(e) => setClient(e.target.value)}><option value="">Tous les clients</option>{clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>}</Field>
        </div>
        {q.error ? <ErrorState message={q.error} onRetry={q.reload} /> : q.loading && !q.data ? <SkeletonCard lines={4} /> : !rows.length ? <EmptyState icon="briefcase" title="Aucune mission">Une mission confirmée s&apos;ajoute aux besoins du mois : le moteur recherche les collaborateurs admissibles.</EmptyState> : (
          <div className="table-wrap"><table className="table table-cards" aria-label="Missions">
            <thead><tr><th>Mission</th><th>Client</th><th>Marque</th><th>Sites</th><th>Dates</th><th>Horaire</th><th>Postes couverts</th><th>Priorité</th><th>Statut</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{rows.map((m) => (
              <tr key={m.id}><td className="cell-main"><strong>{m.title}</strong></td><td data-label="Client">{m.client_name}</td><td data-label="Marque">{m.brand_code}</td><td data-label="Sites">{m.site_codes.join(", ")}</td>
                <td className="num nowrap" data-label="Dates">{m.start_date} → {m.end_date}</td><td className="num nowrap" data-label="Horaire">{hm(m.start_time)}–{hm(m.end_time)}</td>
                <td className="num nowrap" data-label="Postes couverts">{m.shifts_assigned} / {m.shifts_needed}</td><td data-label="Priorité"><Badge tone={m.priority >= 4 ? "accent" : "neutral"}>{PRIORITY_LABEL[m.priority]}</Badge></td>
                <td data-label="Statut"><Badge tone={MISSION_STATUS[m.status]?.tone}>{MISSION_STATUS[m.status]?.label}</Badge></td>
                <td><Button size="sm" onClick={() => setOpen(m)} aria-label={`Ouvrir ${m.title}`}>Ouvrir</Button></td></tr>))}</tbody>
          </table></div>
        )}
      </Card>
      {form && <MissionForm mission={form === "new" ? null : form} clients={clients} catalog={catalog} skills={skills} onClose={() => setForm(null)} onSaved={(m, impact) => { setForm(null); q.reload(); invalidate(); toast.push(impact?.count ? `Mission enregistrée : ${impact.count} shift(s) déjà planifié(s) ne correspondent plus (voir la mission).` : "Mission enregistrée.", impact?.count ? "warn" : "ok"); setOpen(m); }} />}
      {current && <MissionModal m={current} canWrite={canWrite} canOptimize={canOptimize} canSeeEmployees={canSeeEmployees} onClose={() => setOpen(null)} onEdit={() => { setForm(current); setOpen(null); }} onChanged={() => { q.reload(); invalidate(); }} />}
    </>
  );
}

function MissionForm({ mission, clients, catalog, skills, onClose, onSaved }: { mission: Mission | null; clients: Client[]; catalog: Catalog | null; skills: Skill[]; onClose: () => void; onSaved: (m: Mission, impact?: Impact) => void }) {
  const [client, setClient] = useState(mission?.client_id ?? clients.find((c) => !c.archived)?.id ?? "");
  const owned = clients.find((c) => c.id === client)?.brands.map((b) => b.code) ?? [];
  const brandList = useMemo(() => [...(catalog?.brands ?? [])].filter((b) => !b.archived).sort((a, b) => Number(owned.includes(b.code) === false) - Number(owned.includes(a.code) === false)), [catalog, owned.join("|")]); // eslint-disable-line react-hooks/exhaustive-deps
  const [brand, setBrand] = useState(mission?.brand_code ?? "");
  const [sites, setSites] = useState<string[]>(mission?.site_codes ?? []);
  const [days, setDays] = useState<number[]>(mission?.weekdays ?? [0, 1, 2, 3, 4]);
  const [req, setReq] = useState<string[]>(mission?.required_skills ?? []);
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  async function save(f: FormData) {
    if (!brand || !sites.length || !days.length) { setErr("Choisissez une marque, au moins un site et au moins un jour."); return; }
    setBusy(true); setErr("");
    try {
      const hours = String(f.get("budget") || "");
      const body = { client_id: client, brand_code: brand, title: String(f.get("title")), site_codes: sites, start_date: f.get("start"), end_date: f.get("end"), weekdays: days, start_time: f.get("s"), end_time: f.get("e"), break_minutes: Number(f.get("b")), headcount: Number(f.get("n")), required_skills: req, budget_minutes: hours ? Math.round(Number(hours) * 60) : null, billing_rate_cents: parseRate(f.get("rate")), priority: Number(f.get("prio")), notes: String(f.get("notes") || "") || null };
      if (mission) { const r = await api<Mission & { impact: Impact }>(`/missions/${mission.id}`, { method: "PUT", json: body }); onSaved(r, r.impact); }
      else onSaved(await api<Mission>("/missions", { method: "POST", json: body }));
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title={mission ? `Modifier — ${mission.title}` : "Nouvelle mission"} description="Une mission reste en brouillon tant qu'elle n'est pas confirmée : elle n'entre dans aucun planning.">
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void save(new FormData(e.currentTarget)); }}>
        <Field label="Intitulé">{(p) => <Input {...p} name="title" required maxLength={200} defaultValue={mission?.title} placeholder="ex. Événement de lancement" />}</Field>
        <div className="toolbar">
          <Field label="Client">{(p) => <Select {...p} value={client} required onChange={(e) => setClient(e.target.value)}>{clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>}</Field>
          <Field label="Marque">{(p) => <Select {...p} value={brand} required onChange={(e) => setBrand(e.target.value)}><option value="">Choisir…</option>{brandList.map((b) => <option key={b.code} value={b.code}>{b.name}{owned.includes(b.code) ? "" : " (autre client)"}</option>)}</Select>}</Field>
          <Field label="Priorité" help="Départage la couverture quand tout n'est pas couvrable">{(p) => <Select {...p} name="prio" defaultValue={mission?.priority ?? 3}>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{PRIORITY_LABEL[n]}</option>)}</Select>}</Field>
        </div>
        <fieldset className="plain-fieldset"><legend className="label">Sites</legend><div className="row">{catalog?.sites.filter((s) => !s.archived).map((s) => <label key={s.code} className="chip-check"><input type="checkbox" checked={sites.includes(s.code)} onChange={(e) => setSites(e.target.checked ? [...sites, s.code] : sites.filter((x) => x !== s.code))} /><span>{s.name}</span></label>)}</div></fieldset>
        <div className="toolbar">
          <Field label="Début de mission">{(p) => <Input {...p} name="start" type="date" required defaultValue={mission?.start_date} />}</Field>
          <Field label="Fin de mission">{(p) => <Input {...p} name="end" type="date" required defaultValue={mission?.end_date} />}</Field>
          <Field label="Personnes requises" help="Par site et par jour">{(p) => <Input {...p} name="n" type="number" min={1} max={200} required defaultValue={mission?.headcount ?? 1} />}</Field>
        </div>
        <fieldset className="plain-fieldset"><legend className="label">Jours d&apos;activité</legend><div className="row weekday-pick">{WEEKDAYS.map((d, i) => <label key={d} className="chip-check"><input type="checkbox" checked={days.includes(i)} onChange={(e) => setDays(e.target.checked ? [...days, i].sort() : days.filter((x) => x !== i))} /><span>{d}</span></label>)}</div></fieldset>
        <div className="toolbar">
          <Field label="Prise de poste">{(p) => <Input {...p} name="s" type="time" required defaultValue={mission ? hm(mission.start_time) : "09:00"} />}</Field>
          <Field label="Fin de poste">{(p) => <Input {...p} name="e" type="time" required defaultValue={mission ? hm(mission.end_time) : "18:00"} />}</Field>
          <Field label="Pause (min)">{(p) => <Input {...p} name="b" type="number" min={0} max={240} required defaultValue={mission?.break_minutes ?? 60} />}</Field>
        </div>
        <fieldset className="plain-fieldset"><legend className="label">Qualifications obligatoires</legend>
          {skills.length ? <div className="row">{skills.map((s) => <label key={s.id} className="chip-check"><input type="checkbox" checked={req.includes(s.code)} onChange={(e) => setReq(e.target.checked ? [...req, s.code] : req.filter((x) => x !== s.code))} /><span>{s.name}</span></label>)}</div> : <p className="help">Aucune qualification définie (onglet « Qualifications »).</p>}
          <p className="help">Un collaborateur sans ces qualifications n&apos;est jamais affecté automatiquement à cette mission.</p>
        </fieldset>
        <div className="toolbar">
          <Field label="Heures commandées">{(p) => <Input {...p} name="budget" type="number" min={0} step="any" defaultValue={mission?.budget_minutes != null ? mission.budget_minutes / 60 : ""} />}</Field>
          <Field label="Tarif (CHF/h)" help="Prime sur le tarif de la marque et du client">{(p) => <Input {...p} name="rate" inputMode="decimal" defaultValue={rateInput(mission?.billing_rate_cents)} />}</Field>
        </div>
        <Field label="Notes">{(p) => <textarea {...p} name="notes" className="input" rows={2} maxLength={4000} defaultValue={mission?.notes ?? ""} />}</Field>
        {err && <Callout kind="bad" title="Enregistrement impossible">{err}</Callout>}
        <div className="row modal-actions"><Button onClick={onClose} disabled={busy}>Annuler</Button><Button type="submit" variant="primary" disabled={busy} aria-busy={busy}>Enregistrer</Button></div>
      </form>
    </Modal>
  );
}

function MissionModal({ m, canWrite, canOptimize, canSeeEmployees, onClose, onEdit, onChanged }: { m: Mission; canWrite: boolean; canOptimize: boolean; canSeeEmployees: boolean; onClose: () => void; onEdit: () => void; onChanged: () => void }) {
  const toast = useToast();
  const elig = useApi<Elig>(canSeeEmployees ? `/missions/${m.id}/eligibility` : null);
  const periods = useApi<Period[]>("/periods");
  const [cancel, setCancel] = useState(false); const [reason, setReason] = useState(""); const [release, setRelease] = useState(false);
  const [renew, setRenew] = useState(false);
  const [err, setErr] = useState(""); const [run, setRun] = useState<string | null>(null);
  const [impact, setImpact] = useState<Impact | null>(null);
  useEffect(() => { setRun(null); }, [m.id]);
  const months = (periods.data ?? []).filter((p) => p.start_date <= m.end_date && p.end_date >= m.start_date && p.status !== "archived");
  async function act(path: string, json: unknown, msg: string) {
    setErr("");
    try { const r = await api<{ eligibility?: { warning: string | null }; impact?: Impact; released?: number }>(`/missions/${m.id}/${path}`, { method: "POST", json }); toast.push(r.eligibility?.warning ?? msg, r.eligibility?.warning ? "warn" : "ok"); if (r.impact) setImpact(r.impact); onChanged(); elig.reload(); }
    catch (e) { setErr(errText(e)); }
  }
  async function integrate(pid: string) {
    setErr("");
    try { const r = await api<{ run_id: string }>(`/periods/${pid}/local-reoptimize`, { method: "POST", json: { mission_id: m.id } }); setRun(r.run_id); }
    catch (e) { setErr(errText(e)); }
  }
  const editable = m.status === "draft" || m.status === "confirmed";
  return (
    <Modal open onClose={onClose} title={m.title} description={`${m.client_name} · ${m.brand_code} · ${m.site_codes.join(", ")}`}>
      <div className="stack">
        <div className="row"><Badge tone={MISSION_STATUS[m.status]?.tone}>{MISSION_STATUS[m.status]?.label}</Badge><Badge>{PRIORITY_LABEL[m.priority]}</Badge><Badge>{m.days} jour{m.days > 1 ? "s" : ""}</Badge><Badge>{m.headcount} personne{m.headcount > 1 ? "s" : ""} par site</Badge></div>
        <dl className="facts">
          <div><dt>Dates</dt><dd className="num">{m.start_date} → {m.end_date} ({m.weekdays.map((d) => WEEKDAYS[d]).join(", ")})</dd></div>
          <div><dt>Horaire</dt><dd className="num">{hm(m.start_time)}–{hm(m.end_time)}, pause {m.break_minutes} min</dd></div>
          <div><dt>Besoin</dt><dd className="num">{m.shifts_needed} shifts · {fmtH(m.minutes_needed)}{m.budget_minutes != null ? ` · ${fmtH(m.budget_minutes)} commandées` : ""}</dd></div>
          <div><dt>Couvert</dt><dd className="num">{m.shifts_assigned} shifts · {fmtH(m.minutes_assigned)}</dd></div>
          <div><dt>Qualifications</dt><dd>{m.required_skills.join(", ") || "Aucune"}</dd></div>
          <div><dt>Tarif</dt><dd className="num">{fmtCHF(m.billing_rate_cents) ?? "Tarif de la marque ou du client"}</dd></div>
        </dl>
        {canWrite && editable && (
          <div className="row">
            {m.status === "draft" && <Button variant="primary" icon="check" onClick={() => act("confirm", undefined, "Mission confirmée : elle fait désormais partie des besoins.")}>Confirmer la mission</Button>}
            <Button onClick={onEdit}>Modifier</Button>
            {m.status === "confirmed" && <Button onClick={() => act("complete", undefined, "Mission terminée.")}>Marquer terminée</Button>}
            <Button variant="danger" onClick={() => setCancel(true)}>Annuler la mission</Button>
            {m.status === "draft" && <Button variant="ghost" onClick={async () => { try { await api(`/missions/${m.id}`, { method: "DELETE" }); toast.push("Brouillon supprimé.", "ok"); onChanged(); onClose(); } catch (e) { setErr(errText(e)); } }}>Supprimer le brouillon</Button>}
          </div>)}
        {canWrite && <div className="row"><Button size="sm" onClick={() => setRenew(!renew)} aria-expanded={renew}>Renouveler</Button>{m.status === "cancelled" && m.shifts_generated === 0 && <Button size="sm" variant="ghost" onClick={async () => { try { await api(`/missions/${m.id}`, { method: "DELETE" }); toast.push("Mission supprimée.", "ok"); onChanged(); onClose(); } catch (e) { setErr(errText(e)); } }}>Supprimer</Button>}</div>}
        {renew && <form className="toolbar" aria-label="Renouveler la mission" onSubmit={async (e) => { e.preventDefault(); const f = new FormData(e.currentTarget); try { await api(`/missions/${m.id}/renew`, { method: "POST", json: { start_date: f.get("start"), end_date: f.get("end") } }); toast.push("Renouvellement créé en brouillon.", "ok"); setRenew(false); onChanged(); } catch (x) { setErr(errText(x)); } }}>
          <Field label="Nouveau début">{(p) => <Input {...p} name="start" type="date" required />}</Field><Field label="Nouvelle fin">{(p) => <Input {...p} name="end" type="date" required />}</Field><div style={{ alignSelf: "end" }}><Button type="submit" variant="primary">Créer le renouvellement</Button></div></form>}
        {m.status === "confirmed" && canOptimize && (
          <section className="stack" aria-label="Intégration au planning" style={{ gap: "var(--sp-2)" }}>
            <h3 className="h2">Intégrer au planning</h3>
            {months.length ? <>
              <p className="help">Seuls les shifts de la mission sont affectés ; le reste du planning ne bouge pas. Vous voyez le résultat avant de l&apos;appliquer. Pour un mois non encore généré, lancez sa génération.</p>
              <div className="row">{months.map((p) => <Button key={p.id} icon="sparkles" onClick={() => integrate(p.id)}>{p.name}</Button>)}</div>
            </> : <p className="help">Aucun planning ouvert sur ces dates : la mission sera prise en compte à la prochaine génération du mois.</p>}
            {run && <SimulationPreview runId={run} canApply={canOptimize} onApplied={() => { setRun(null); onChanged(); }} />}
          </section>)}
        {impact && impact.count > 0 && (
          <Callout kind="warn" title={`${impact.count} shift(s) déjà planifié(s) ne correspondent plus à cette mission`}>
            <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>{impact.shifts.slice(0, 6).map((s) => <li key={s.shift_id}>{s.day} · {s.site} · {s.start}–{s.end}{s.employee ? ` · ${s.employee}` : ""}{s.past ? " (passé, conservé)" : ""}</li>)}</ul>
            {canWrite && <div style={{ marginTop: "var(--sp-2)" }}><Button size="sm" onClick={async () => { try { const r = await api<{ released: number; impact: Impact }>(`/missions/${m.id}/release-shifts`, { method: "POST" }); setImpact(r.impact); toast.push(`${r.released} shift(s) à venir retiré(s) du planning.`, "ok"); onChanged(); } catch (e) { setErr(errText(e)); } }}>Retirer les shifts à venir</Button></div>}
          </Callout>)}
        {canSeeEmployees && (
          <section aria-label="Collaborateurs admissibles">
            <h3 className="h2">Collaborateurs admissibles {elig.data && <Badge tone={elig.data.eligible >= m.headcount ? "ok" : "warn"}>{elig.data.eligible}</Badge>}</h3>
            {elig.data?.warning && <Callout kind="warn">{elig.data.warning}</Callout>}
            {elig.data && <ul className="elig-list">{elig.data.employees.map((e) => <li key={e.employee_id} data-ok={e.eligible}><strong>{e.name}</strong>{e.eligible ? <span className="muted"> · {e.available_days}/{e.total_days} jours disponibles</span> : <span className="muted"> · {e.reasons.join(" · ")}</span>}</li>)}</ul>}
          </section>)}
        {err && <Callout kind="bad" title="Opération impossible">{err}</Callout>}
        <div className="row modal-actions"><Button onClick={onClose}>Fermer</Button></div>
      </div>
      <Modal open={cancel} onClose={() => setCancel(false)} title="Annuler cette mission ?" variant="confirm" description="Elle reste dans l'historique ; elle ne sera plus planifiée.">
        <div className="stack">
          <Field label="Motif (facultatif)">{(p) => <Input {...p} value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />}</Field>
          <label className="row"><input type="checkbox" checked={release} onChange={(e) => setRelease(e.target.checked)} /> Retirer aussi les shifts à venir déjà planifiés <span className="faint">— le passé reste intact</span></label>
          <div className="row modal-actions"><Button onClick={() => setCancel(false)}>Ne pas annuler</Button><Button variant="danger" onClick={async () => { setCancel(false); await act("cancel", { reason: reason.trim() || null, release_shifts: release }, "Mission annulée."); }}>Annuler la mission</Button></div>
        </div>
      </Modal>
    </Modal>
  );
}

// ---- qualifications ----
function Skills({ q, canWrite }: { q: ReturnType<typeof useApi<Skill[]>>; canWrite: boolean }) {
  const toast = useToast();
  const [err, setErr] = useState("");
  return (
    <Card title="Qualifications, langues et certifications" eyebrow="Utilisées par les fiches collaborateurs et les missions">
      <div className="stack">
        {canWrite && <form className="toolbar" aria-label="Nouvelle qualification" onSubmit={async (e) => { e.preventDefault(); const form = e.currentTarget; const f = new FormData(form); setErr(""); try { await api("/skills/new", { method: "POST", json: { name: f.get("name"), category: f.get("cat") } }); form.reset(); toast.push("Qualification ajoutée.", "ok"); q.reload(); } catch (x) { setErr(errText(x)); } }}>
          <Field label="Nom">{(p) => <Input {...p} name="name" required maxLength={200} placeholder="ex. Anglais, Formation luxe" />}</Field>
          <Field label="Catégorie">{(p) => <Select {...p} name="cat" defaultValue="competence">{Object.entries(SKILL_CATEGORY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>}</Field>
          <div style={{ alignSelf: "end" }}><Button type="submit" icon="plus">Ajouter</Button></div>
        </form>}
        {err && <Callout kind="bad" title="Ajout impossible">{err}</Callout>}
        {q.error ? <ErrorState message={q.error} onRetry={q.reload} /> : !q.data?.length ? <EmptyState icon="shield" title="Aucune qualification">Définissez les qualifications exigées par vos clients.</EmptyState> : (
          <div className="row">{q.data.map((s) => <Badge key={s.id} tone="neutral">{s.name} <span className="faint">· {SKILL_CATEGORY[s.category] ?? s.category}</span></Badge>)}</div>)}
      </div>
    </Card>
  );
}
