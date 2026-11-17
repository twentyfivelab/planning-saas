"use client";
import { useState } from "react";
import { useApi, usePeriod } from "@/components/hooks";
import { Badge, Card, EmptyState, ErrorState, Field, PageHead, Select, SkeletonCard } from "@/components/ui/primitives";
import { fmtH } from "@/lib/wfm";

type Cell = { minutes: number; days: number; weekends: number; sundays: number };
type Rep = { months: { key: string; label: string }[]; mean: Cell; note: string;
  employees: { employee_id: string; employee: string; deleted: boolean; months: Cell[]; total: Cell; delta: Cell }[] };

const sign = (v: number, unit = "") => `${v > 0 ? "+" : ""}${String(v).replace(".", ",")}${unit}`;
/** Écart notable : au-delà de 25 % de la moyenne de l'équipe (et d'au moins une unité). */
const tone = (delta: number, mean: number) => (Math.abs(delta) >= Math.max(1, mean * 0.25) ? (delta > 0 ? "warn" : "info") : "neutral");

/** Équité sur plusieurs mois : week-ends, dimanches, jours et heures de chaque collaborateur, comparés à la moyenne de l'équipe. */
export default function Fairness() {
  const { month } = usePeriod();
  const [n, setN] = useState(6);
  const q = useApi<Rep>(month ? `/reports/fairness?to=${month}&months=${n}` : null);
  const r = q.data;
  return (
    <>
      <PageHead eyebrow="Plusieurs mois" title="Équité">
        <Field label="Période">{(p) => <Select {...p} value={n} onChange={(e) => setN(Number(e.target.value))}>{[3, 6, 12].map((k) => <option key={k} value={k}>{k} derniers mois</option>)}</Select>}</Field>
      </PageHead>
      {q.error ? <ErrorState message={q.error} onRetry={q.reload} /> : !r ? <SkeletonCard lines={5} /> : !r.employees.length ? (
        <Card><EmptyState icon="users" title="Aucun planning sur cette période">Les compteurs apparaissent dès qu&apos;un planning existe.</EmptyState></Card>
      ) : (
        <Card title={`${r.months[0].label} – ${r.months[r.months.length - 1].label}`} eyebrow="Écart à la moyenne de l'équipe">
          <p className="help" style={{ marginTop: 0 }}>{r.note} Moyenne de l&apos;équipe : {fmtH(r.mean.minutes)} · {String(r.mean.days).replace(".", ",")} jours · {String(r.mean.weekends).replace(".", ",")} jours de week-end · {String(r.mean.sundays).replace(".", ",")} dimanches.</p>
          <div className="table-wrap" data-testid="fairness"><table className="table table-cards">
            <caption className="sr-only">Équité sur {r.months.length} mois</caption>
            <thead><tr><th>Collaborateur</th><th>Travail effectif</th><th>Jours</th><th>Week-ends</th><th>Dimanches</th><th>Week-ends par mois</th></tr></thead>
            <tbody>{r.employees.map((e) => (
              <tr key={e.employee_id}>
                <td className="cell-main" data-label="Collaborateur">{e.employee}{e.deleted && <span className="muted"> (supprimé·e)</span>}</td>
                <td data-label="Travail effectif" className="num">{fmtH(e.total.minutes)} <Badge tone={tone(e.delta.minutes / 60, r.mean.minutes / 60)}>{sign(Math.round(e.delta.minutes / 6) / 10, " h")}</Badge></td>
                <td data-label="Jours" className="num">{e.total.days} <Badge tone={tone(e.delta.days, r.mean.days)}>{sign(e.delta.days)}</Badge></td>
                <td data-label="Week-ends" className="num">{e.total.weekends} <Badge tone={tone(e.delta.weekends, r.mean.weekends)}>{sign(e.delta.weekends)}</Badge></td>
                <td data-label="Dimanches" className="num">{e.total.sundays} <Badge tone={tone(e.delta.sundays, r.mean.sundays)}>{sign(e.delta.sundays)}</Badge></td>
                <td data-label="Week-ends par mois" className="num nowrap" title={r.months.map((m, i) => `${m.label} : ${e.months[i].weekends}`).join(" · ")}>{e.months.map((c) => c.weekends).join(" · ")}</td>
              </tr>))}</tbody>
          </table></div>
        </Card>
      )}
    </>
  );
}
