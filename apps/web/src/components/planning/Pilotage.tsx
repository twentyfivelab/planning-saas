"use client";
import { useApi } from "@/components/hooks";
import { Badge, Card, EmptyState } from "@/components/ui/primitives";
import { BarList } from "@/components/ui/Charts";
import { brandColor } from "@/lib/brand";
import { SOFT_LABEL, fmtH } from "@/lib/wfm";

type EmpRow = { id: string; name: string; minutes: number; target_minutes: number; contract_target: boolean; gap_minutes: number; attainment: number | null; days: number; sundays: number; opens: number; closes: number; max_consecutive: number; sites: number };
export type Pilot = {
  reference_day: string;
  people: { active: number; planned: number; working_today: number; available_today: number; unavailable_today: number; unavailable_names: string[]; under_target: EmpRow[]; near_limits: { name: string; detail: string }[] };
  planning: { shifts: number; mandatory: number; covered: number; uncovered: number; uncovered_minutes: number; coverage_rate: number | null; pending_replacements: number; hard_violations: number; soft_unsatisfied: number; soft_detail: Record<string, number> };
  brands: { code: string; minutes: number }[]; budgets: { brand: string; target_minutes: number; planned_minutes: number; remaining_minutes: number; strict: boolean }[];
  sites: { code: string; name: string; minutes: number }[];
  equity: { employees: EmpRow[]; gap_to_targets_minutes: number; sundays_min: number; sundays_max: number; max_consecutive: number };
  finance: { planned_minutes: number; actual_minutes: number; validated_minutes: number; cost_planned_cents?: number | null; cost_actual_cents?: number | null; billable_planned_cents?: number | null; margin_planned_cents?: number | null; complete?: boolean } | null;
};

/** Pilotage du mois : collaborateurs, remplacements, sites, budgets et répartition, à partir des données enregistrées. */
export function Pilotage({ periodId }: { periodId: string }) {
  const q = useApi<Pilot>(`/periods/${periodId}/dashboard`);
  const d = q.data;
  if (!d) return null;
  const rows = [...d.equity.employees].sort((a, b) => (a.attainment ?? 0) - (b.attainment ?? 0));
  const maxSite = Math.max(1, ...d.sites.map((s) => s.minutes));
  return (
    <>
      <div className="grid-kpi" data-testid="pilotage">
        <Card eyebrow={`Le ${new Date(d.reference_day).toLocaleDateString("fr-CH", { timeZone: "UTC", day: "numeric", month: "long" })}`} title="Collaborateurs" lift>
          <p className="kpi-value num">{d.people.working_today} <span className="muted" style={{ fontSize: "var(--text-md)" }}>au travail</span></p>
          <p className="kpi-sub">{d.people.active} actifs · {d.people.planned} planifiés ce mois · {d.people.available_today} disponibles · {d.people.unavailable_today} indisponibles</p>
        </Card>
        <Card eyebrow="À traiter" title="Remplacements en attente" lift>
          <p className="kpi-value num">{d.planning.pending_replacements + d.planning.uncovered}</p>
          <p className="kpi-sub">{d.planning.pending_replacements} titulaire(s) indisponible(s) · {d.planning.uncovered} shift(s) non couvert(s), {fmtH(d.planning.uncovered_minutes)}</p>
        </Card>
      </div>
      <div className="grid-2">
        <Card title="Heures par site" eyebrow="Travail effectif">
          {d.sites.length ? <BarList data={d.sites.map((s) => ({ key: s.code, label: s.name, value: s.minutes / 60, max: maxSite / 60, right: fmtH(s.minutes) }))} /> : <EmptyState icon="briefcase" title="Aucune heure">Aucun shift planifié.</EmptyState>}
        </Card>
        <Card title="Budgets restants" eyebrow="Planifié / budget">
          {d.budgets.length ? <BarList data={d.budgets.map((b) => ({ key: b.brand, label: b.brand, value: b.planned_minutes / 60, max: Math.max(1, b.target_minutes) / 60, color: brandColor(b.brand), right: `reste ${fmtH(b.remaining_minutes)}` }))} /> : <EmptyState icon="wallet" title="Aucun budget ce mois">Saisissez les budgets dans l&apos;assistant du mois.</EmptyState>}
        </Card>
      </div>
      <div className="grid-2">
        {d.people.near_limits.length > 0 && <Card title="Proches de leurs limites"><ul className="stack" style={{ margin: 0, paddingLeft: "1.1rem" }}>{d.people.near_limits.map((n) => <li key={n.name + n.detail}><strong>{n.name}</strong> <span className="muted">— {n.detail}</span></li>)}</ul></Card>}
        {d.planning.soft_unsatisfied > 0 && <Card title="Préférences non satisfaites" eyebrow={`${d.planning.soft_unsatisfied} au total`}><ul className="stack" style={{ margin: 0, paddingLeft: "1.1rem" }}>{Object.entries(d.planning.soft_detail).map(([k, v]) => <li key={k}>{SOFT_LABEL[k] ?? k} : <strong className="num">{v}</strong></li>)}</ul></Card>}
      </div>
      <Card title="Répartition par collaborateur" eyebrow="Objectif : contrat s'il est renseigné, sinon part équitable calculée">
        <div className="table-wrap"><table className="table table-cards" aria-label="Répartition par collaborateur">
          <thead><tr><th>Collaborateur</th><th>Heures</th><th>Objectif</th><th>Atteinte</th><th>Jours</th><th>Dimanches</th><th>Ouvertures</th><th>Fermetures</th><th>Jours d&apos;affilée</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.id}><td className="cell-main"><strong>{r.name}</strong></td><td className="num nowrap" data-label="Heures">{fmtH(r.minutes)}</td><td className="num nowrap" data-label="Objectif">{fmtH(r.target_minutes)}{!r.contract_target && <span className="faint"> (calculé)</span>}</td>
            <td className="num" data-label="Atteinte">{r.attainment === null ? "—" : <Badge tone={r.attainment < 90 ? "warn" : r.attainment > 110 ? "info" : "ok"}>{r.attainment} %</Badge>}</td><td className="num" data-label="Jours">{r.days}</td><td className="num" data-label="Dimanches">{r.sundays}</td><td className="num" data-label="Ouvertures">{r.opens}</td><td className="num" data-label="Fermetures">{r.closes}</td><td className="num" data-label="Jours d'affilée">{r.max_consecutive}</td></tr>)}</tbody>
        </table></div>
      </Card>
    </>
  );
}
