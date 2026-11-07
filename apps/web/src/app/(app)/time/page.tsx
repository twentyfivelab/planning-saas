"use client";
import { useEffect, useMemo, useState } from "react";
import { useMe } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { MonthSwitcher } from "@/components/MonthSwitcher";
import { Badge, Button, Callout, Card, EmptyState, ErrorState, Field, Input, PageHead, Select, SkeletonCard } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { monthLabel } from "@/lib/months";
import { errText, fmtH } from "@/lib/wfm";

type Entry = { id: string; status: "worked" | "absent"; actual_start: string | null; actual_end: string | null; actual_break_minutes: number | null; worked_minutes: number; late_minutes: number; overtime_minutes: number; absence_reason: string | null; note: string | null; validated: boolean; validated_by: string | null };
type Row = { shift_id: string; employee_id: string; employee: string; day: string; site: string; brands: string[]; planned_start: string; planned_end: string; planned_break_minutes: number; planned_minutes: number; entry: Entry | null };
type Summary = { employees: { employee_id: string; employee: string; planned_minutes: number; worked_minutes: number; validated_minutes: number; overtime_minutes: number; late_minutes: number; absences: number; missing_entries: number }[]; to_validate: number };

export default function TimeTracking() {
  const me = useMe(); const toast = useToast();
  const { period, month, setMonth } = usePeriod();
  const canWrite = me.permissions.includes("time.write"), canValidate = me.permissions.includes("time.validate");
  const [day, setDay] = useState("");
  const today = new Date().toISOString().slice(0, 10);
  // seul un changement de mois réinitialise le jour (pas un simple rechargement des données)
  useEffect(() => { if (period) setDay(today >= period.start_date && today <= period.end_date ? today : period.start_date); else setDay(""); }, [period?.id, today]); // eslint-disable-line react-hooks/exhaustive-deps
  const data = useApi<{ rows: Row[]; summary: Summary }>(period && day ? `/periods/${period.id}/time-entries?day=${day}` : null);
  const all = useApi<{ rows: Row[]; summary: Summary }>(period ? `/periods/${period.id}/time-entries` : null);
  const [edit, setEdit] = useState<Row | null>(null);
  const [status, setStatus] = useState<"worked" | "absent">("worked"); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { setStatus(edit?.entry?.status ?? "worked"); setErr(""); }, [edit]);
  const refresh = () => { data.reload(); all.reload(); };
  async function save(f: FormData) {
    if (!edit) return;
    setBusy(true); setErr("");
    try {
      const body = status === "absent" ? { status, absence_reason: String(f.get("reason") || "") || null, note: String(f.get("note") || "") || null }
        : { status, actual_start: f.get("start"), actual_end: f.get("end"), actual_break_minutes: Number(f.get("break")), note: String(f.get("note") || "") || null };
      await api(`/shifts/${edit.shift_id}/time-entry`, { method: "PUT", json: body });
      toast.push("Heures enregistrées. Le planning prévisionnel reste inchangé.", "ok"); setEdit(null); refresh();
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function validate(r: Row, on: boolean) {
    try { await api(`/time-entries/${r.entry!.id}/${on ? "validate" : "unvalidate"}`, { method: "POST" }); toast.push(on ? "Heures validées." : "Validation retirée.", "ok"); refresh(); }
    catch (e) { toast.push(errText(e), "bad"); }
  }
  const rows = data.data?.rows ?? [];
  const summary = all.data?.summary;
  const sorted = useMemo(() => summary?.employees ?? [], [summary]);
  return (
    <>
      <PageHead eyebrow={monthLabel(month)} title="Heures réelles"><MonthSwitcher month={month} onChange={setMonth} /></PageHead>
      <Callout kind="info">Les heures réelles sont enregistrées à part : elles ne modifient jamais le planning prévisionnel. Une saisie validée puis modifiée doit être revalidée.</Callout>
      {!period ? <Card><EmptyState icon="clock" title={`Aucun planning pour ${monthLabel(month)}`}>Générez d&apos;abord le planning de ce mois.</EmptyState></Card> : (
        <>
          <Card title="Saisie du jour" actions={<Field label="Jour">{(p) => <Input {...p} type="date" value={day} min={period.start_date} max={period.end_date} onChange={(e) => setDay(e.target.value)} />}</Field>}>
            {data.error ? <ErrorState message={data.error} onRetry={data.reload} /> : data.loading && !data.data ? <SkeletonCard lines={4} /> : !rows.length ? <EmptyState icon="calendar" title="Aucun shift ce jour">Aucune affectation à cette date.</EmptyState> : (
              <div className="table-wrap"><table className="table table-cards" aria-label="Heures du jour">
                <thead><tr><th>Collaborateur</th><th>Site et marque</th><th>Prévu</th><th>Réel</th><th>Effectué</th><th>Écarts</th><th>Validation</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>{rows.map((r) => (
                  <tr key={r.shift_id}>
                    <td className="cell-main"><strong>{r.employee}</strong></td>
                    <td data-label="Site et marque">{r.site} · {r.brands.join(" + ")}</td>
                    <td className="num nowrap" data-label="Prévu">{r.planned_start}–{r.planned_end} · {fmtH(r.planned_minutes)}</td>
                    <td className="num nowrap" data-label="Réel">{!r.entry ? <span className="faint">À saisir</span> : r.entry.status === "absent" ? <Badge tone="bad">Absent{r.entry.absence_reason ? ` · ${r.entry.absence_reason}` : ""}</Badge> : `${r.entry.actual_start}–${r.entry.actual_end} · pause ${r.entry.actual_break_minutes} min`}</td>
                    <td className="num nowrap" data-label="Effectué">{r.entry ? fmtH(r.entry.worked_minutes) : "—"}</td>
                    <td data-label="Écarts"><div className="row">{r.entry && r.entry.late_minutes > 0 && <Badge tone="warn">Retard {r.entry.late_minutes} min</Badge>}{r.entry && r.entry.overtime_minutes > 0 && <Badge tone="info">+ {fmtH(r.entry.overtime_minutes)}</Badge>}</div></td>
                    <td data-label="Validation">{r.entry ? (r.entry.validated ? <Badge tone="ok" icon="check">Validée{r.entry.validated_by ? ` · ${r.entry.validated_by}` : ""}</Badge> : <Badge tone="warn">À valider</Badge>) : <span className="faint">—</span>}</td>
                    <td><div className="row" style={{ flexWrap: "nowrap" }}>
                      {canWrite && <Button size="sm" onClick={() => setEdit(r)} aria-label={`Saisir les heures de ${r.employee}`}>Saisir</Button>}
                      {canValidate && r.entry && <Button size="sm" onClick={() => validate(r, !r.entry!.validated)} aria-label={`${r.entry.validated ? "Retirer la validation de" : "Valider"} ${r.employee}`}>{r.entry.validated ? "Retirer" : "Valider"}</Button>}
                    </div></td>
                  </tr>))}</tbody>
              </table></div>
            )}
          </Card>
          <Card title="Prévu et réel par collaborateur" eyebrow={summary ? `${summary.to_validate} saisie(s) à valider` : undefined}>
            {!sorted.length ? <EmptyState icon="users" title="Aucune donnée">Aucune affectation sur ce mois.</EmptyState> : (
              <div className="table-wrap"><table className="table table-cards" aria-label="Heures du mois par collaborateur">
                <thead><tr><th>Collaborateur</th><th>Planifié</th><th>Saisi</th><th>Validé</th><th>Au-delà du prévu</th><th>Retards</th><th>Absences</th><th>Shifts passés sans saisie</th></tr></thead>
                <tbody>{sorted.map((s) => (
                  <tr key={s.employee_id}><td className="cell-main"><strong>{s.employee}</strong></td><td className="num nowrap" data-label="Planifié">{fmtH(s.planned_minutes)}</td><td className="num nowrap" data-label="Saisi">{fmtH(s.worked_minutes)}</td><td className="num nowrap" data-label="Validé">{fmtH(s.validated_minutes)}</td>
                    <td className="num nowrap" data-label="Au-delà du prévu">{fmtH(s.overtime_minutes)}</td><td className="num nowrap" data-label="Retards">{s.late_minutes} min</td><td className="num" data-label="Absences">{s.absences}</td><td className="num" data-label="Sans saisie">{s.missing_entries}</td></tr>))}</tbody>
              </table></div>
            )}
          </Card>
        </>
      )}
      <Modal open={!!edit} onClose={() => !busy && setEdit(null)} title={edit ? `Heures réelles — ${edit.employee}` : ""} description={edit ? `${edit.day} · ${edit.site} · prévu ${edit.planned_start}–${edit.planned_end}, pause ${edit.planned_break_minutes} min` : undefined}>
        {edit && (
          <form className="stack" onSubmit={(e) => { e.preventDefault(); void save(new FormData(e.currentTarget)); }}>
            <Field label="Présence">{(p) => <Select {...p} value={status} onChange={(e) => setStatus(e.target.value as "worked" | "absent")}><option value="worked">Présent</option><option value="absent">Absent</option></Select>}</Field>
            {status === "worked" ? (
              <div className="toolbar">
                <Field label="Arrivée réelle">{(p) => <Input {...p} name="start" type="time" required defaultValue={edit.entry?.actual_start ?? edit.planned_start} />}</Field>
                <Field label="Départ réel">{(p) => <Input {...p} name="end" type="time" required defaultValue={edit.entry?.actual_end ?? edit.planned_end} />}</Field>
                <Field label="Pause prise (min)">{(p) => <Input {...p} name="break" type="number" min={0} max={480} defaultValue={edit.entry?.actual_break_minutes ?? edit.planned_break_minutes} />}</Field>
              </div>
            ) : <Field label="Motif de l'absence">{(p) => <Input {...p} name="reason" maxLength={200} defaultValue={edit.entry?.absence_reason ?? ""} />}</Field>}
            <Field label="Remarque (facultatif)">{(p) => <Input {...p} name="note" maxLength={300} defaultValue={edit.entry?.note ?? ""} />}</Field>
            {err && <Callout kind="bad" title="Enregistrement impossible">{err}</Callout>}
            <div className="row modal-actions"><Button onClick={() => setEdit(null)} disabled={busy}>Annuler</Button><Button type="submit" variant="primary" disabled={busy} aria-busy={busy}>Enregistrer</Button></div>
          </form>
        )}
      </Modal>
    </>
  );
}
