"use client";
import { useState } from "react";
import { useApi } from "@/components/hooks";
import { Badge, Button, Callout, Card, Field, Input, Select } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";
import { errText } from "@/lib/wfm";

type Req = { id: string; kind: "leave" | "absence" | "swap" | "availability"; status: string; status_label: string; employee: string; colleague: string | null; summary: string;
  note: string | null; decision_note: string | null };
type Mine = { employee: { id: string; name: string }; mine: Req[]; received: Req[]; colleagues: { id: string; name: string }[]; weekly_unavailable: number[] };
const WD = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];
const TONE: Record<string, "warn" | "ok" | "bad" | "neutral" | "info"> = { pending: "warn", awaiting_colleague: "info", approved: "ok", refused: "bad", declined: "bad", cancelled: "neutral" };
const EMPTY = { start_date: "", end_date: "", leave_kind: "conge", on_date: "", partial: false, start_time: "", end_time: "", my_day: "", colleague_id: "", colleague_day: "", note: "" };

/** Demandes du collaborateur : congé, absence (journée ou partie de journée), échange avec un collègue. Rien n'est appliqué sans la
 *  décision d'un responsable ; un échange attend d'abord l'accord du collègue. */
export function MyRequests() {
  const toast = useToast();
  const q = useApi<Mine>("/me/requests");
  const [kind, setKind] = useState<"leave" | "absence" | "swap" | "availability">("leave");
  const [weekly, setWeekly] = useState<number[] | null>(null); // null = valeurs actuelles de la fiche
  const [f, setF] = useState(EMPTY); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof EMPTY, v: string | boolean) => setF((x) => ({ ...x, [k]: v }));
  const currentWeekly = q.data?.weekly_unavailable ?? [];
  const wk = weekly ?? currentWeekly;
  const sameWeekly = [...wk].sort().join() === [...currentWeekly].sort().join();
  const valid = kind === "availability" ? !sameWeekly && wk.length < 7 : kind === "leave" ? !!f.start_date && !!f.end_date && f.end_date >= f.start_date
    : kind === "absence" ? !!f.on_date && (!f.partial || (!!f.start_time && !!f.end_time && f.end_time > f.start_time))
      : !!f.my_day && !!f.colleague_id && !!f.colleague_day;
  async function act(fn: () => Promise<unknown>, msg: string) {
    setBusy(true); setErr("");
    try { await fn(); toast.push(msg, "ok"); q.reload(); invalidate(); return true; } catch (e) { setErr(errText(e)); return false; } finally { setBusy(false); }
  }
  async function submit() {
    const body = kind === "availability" ? { kind, unavailable_weekdays: [...wk].sort(), note: f.note || null } : kind === "leave" ? { kind, start_date: f.start_date, end_date: f.end_date, leave_kind: f.leave_kind, note: f.note || null }
      : kind === "absence" ? { kind, on_date: f.on_date, start_time: f.partial ? f.start_time : null, end_time: f.partial ? f.end_time : null, note: f.note || null }
        : { kind, my_day: f.my_day, colleague_id: f.colleague_id, colleague_day: f.colleague_day, note: f.note || null };
    if (await act(() => api("/me/requests", { method: "POST", json: body }), kind === "swap" ? "Proposition envoyée à votre collègue." : "Demande envoyée à votre responsable.")) { setF(EMPTY); setWeekly(null); }
  }
  const d = q.data;
  return (
    <Card title="Mes demandes" eyebrow="Congés, absences et échanges">
      <div className="stack" data-testid="my-requests">
        {d?.received.some((r) => r.status === "awaiting_colleague") && (
          <Callout kind="info" title="Propositions d'échange reçues">
            <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: "var(--sp-2)" }}>
              {d.received.filter((r) => r.status === "awaiting_colleague").map((r) => (
                <li key={r.id} className="row" data-testid="received-request"><span><strong>{r.employee}</strong> : {r.summary}{r.note ? ` — « ${r.note} »` : ""}</span>
                  <Button size="sm" variant="primary" disabled={busy} onClick={() => act(() => api(`/me/requests/${r.id}/answer`, { method: "POST", json: { accept: true } }), "Accord envoyé : votre responsable doit encore valider.")}>Accepter</Button>
                  <Button size="sm" disabled={busy} onClick={() => act(() => api(`/me/requests/${r.id}/answer`, { method: "POST", json: { accept: false } }), "Proposition refusée.")}>Refuser</Button></li>))}
            </ul>
          </Callout>)}
        <div className="row" style={{ alignItems: "flex-end" }}>
          <Field label="Type de demande">{(p) => <Select {...p} value={kind} onChange={(e) => { setKind(e.target.value as typeof kind); setErr(""); }}>
            <option value="leave">Congé</option><option value="absence">Absence (journée ou partie de journée)</option><option value="swap">Échange avec un collègue</option><option value="availability">Indisponibilités chaque semaine</option></Select>}</Field>
          {kind === "leave" && <>
            <Field label="Du">{(p) => <Input {...p} type="date" value={f.start_date} onChange={(e) => set("start_date", e.target.value)} />}</Field>
            <Field label="Au">{(p) => <Input {...p} type="date" value={f.end_date} onChange={(e) => set("end_date", e.target.value)} />}</Field>
            <Field label="Motif">{(p) => <Select {...p} value={f.leave_kind} onChange={(e) => set("leave_kind", e.target.value)}><option value="conge">Congé</option><option value="formation">Formation</option><option value="maladie">Maladie</option><option value="autre">Autre</option></Select>}</Field>
          </>}
          {kind === "absence" && <>
            <Field label="Jour">{(p) => <Input {...p} type="date" value={f.on_date} onChange={(e) => set("on_date", e.target.value)} />}</Field>
            <label className="row"><input type="checkbox" checked={f.partial} onChange={(e) => set("partial", e.target.checked)} /> Une partie de la journée</label>
            {f.partial && <>
              <Field label="Heure de début">{(p) => <Input {...p} type="time" value={f.start_time} onChange={(e) => set("start_time", e.target.value)} />}</Field>
              <Field label="Heure de fin">{(p) => <Input {...p} type="time" value={f.end_time} onChange={(e) => set("end_time", e.target.value)} />}</Field>
            </>}
          </>}
          {kind === "availability" && (
            <div className="row" role="group" aria-label="Jours où je ne peux pas travailler chaque semaine">{WD.map((d, i) => (
              <label key={d} className="chip-check"><input type="checkbox" checked={wk.includes(i)} onChange={(e) => setWeekly(e.target.checked ? [...wk, i] : wk.filter((x) => x !== i))} /><span>{d}</span></label>))}</div>)}
          {kind === "swap" && <>
            <Field label="Mon shift du">{(p) => <Input {...p} type="date" value={f.my_day} onChange={(e) => set("my_day", e.target.value)} />}</Field>
            <Field label="Avec">{(p) => <Select {...p} value={f.colleague_id} onChange={(e) => set("colleague_id", e.target.value)}><option value="">Choisir…</option>{(d?.colleagues ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>}</Field>
            <Field label="Son shift du">{(p) => <Input {...p} type="date" value={f.colleague_day} onChange={(e) => set("colleague_day", e.target.value)} />}</Field>
          </>}
          <Field label="Message (facultatif)">{(p) => <Input {...p} value={f.note} maxLength={500} onChange={(e) => set("note", e.target.value)} />}</Field>
          <Button variant="primary" disabled={!valid || busy} onClick={submit} aria-busy={busy}>Envoyer</Button>
        </div>
        <p className="help">Rien n&apos;est modifié avant la décision de votre responsable. Un échange attend d&apos;abord l&apos;accord de votre collègue.{kind === "availability" ? " Les indisponibilités hebdomadaires s'appliquent aux prochains plannings ; les plannings déjà créés ne changent pas." : ""}</p>
        {err && <Callout kind="bad" title="Demande non envoyée">{err}</Callout>}
        {!!d?.mine.length && (
          <div className="table-wrap"><table className="table table-cards">
            <caption className="sr-only">Mes demandes</caption>
            <thead><tr><th>Demande</th><th>Statut</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{d.mine.map((r) => (
              <tr key={r.id} data-testid="my-request"><td className="cell-main" data-label="Demande">{r.summary}{r.decision_note ? <span className="help"> — {r.decision_note}</span> : null}</td>
                <td data-label="Statut"><Badge tone={TONE[r.status] ?? "neutral"}>{r.status_label}</Badge></td>
                <td>{["pending", "awaiting_colleague"].includes(r.status) && <Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => api(`/me/requests/${r.id}/cancel`, { method: "POST" }), "Demande annulée.")}>Annuler la demande</Button>}</td></tr>))}</tbody>
          </table></div>)}
      </div>
    </Card>
  );
}
