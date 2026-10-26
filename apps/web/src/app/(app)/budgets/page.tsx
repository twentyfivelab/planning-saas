"use client";
import { Card, Page } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { hours } from "@/lib/schedule";
import { t } from "@/lib/i18n";

type Budget = { id: string; brand_code: string; target_minutes: number; requirements_defined: boolean; month: string };

export default function Budgets() {
  const { period } = usePeriod();
  const b = useApi<Budget[]>("/budgets");
  const s = useApi<{ assignments: { allocations: Record<string, number> }[] }>(period ? `/periods/${period.id}/schedule` : null);
  const planned: Record<string, number> = {};
  s.data?.assignments.forEach((a) => Object.entries(a.allocations).forEach(([k, v]) => (planned[k] = (planned[k] ?? 0) + v)));
  const total = (b.data ?? []).reduce((x, y) => x + y.target_minutes, 0);
  return (
    <Page>
      <h1 className="mb-3 text-2xl font-semibold">{t("nav.budgets")}</h1>
      <Card title={`Budgets de travail effectif — total ${hours(total)}`}>
        <div className="overflow-x-auto"><table className="grid"><thead><tr><th>Marque</th><th>Budget</th><th>Planifié</th><th>Restant</th><th>Avancement</th><th>Besoins</th></tr></thead><tbody>
          {(b.data ?? []).map((x) => { const p = planned[x.brand_code] ?? 0; const pct = x.target_minutes ? Math.round((100 * p) / x.target_minutes) : 0;
            return <tr key={x.id}><td>{x.brand_code}</td><td>{hours(x.target_minutes)}</td><td>{hours(p)}</td><td>{hours(x.target_minutes - p)}</td>
              <td><progress aria-label={`${x.brand_code} ${pct}%`} max={100} value={pct} /> {pct}%</td>
              <td>{x.requirements_defined ? "définis" : <strong className="tag-warn">{t("to_fill")} — jours et horaires manquants</strong>}</td></tr>; })}
        </tbody></table></div>
        <p className="muted mt-2 text-sm">Les heures de co-branding sont imputées aux deux budgets sans doubler les heures du collaborateur.</p>
      </Card>
    </Page>
  );
}
