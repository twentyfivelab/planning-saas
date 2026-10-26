"use client";
import { Card, Page } from "@/components/Shell";
import { usePeriod, useApi } from "@/components/hooks";
import { hours } from "@/lib/schedule";
import { t } from "@/lib/i18n";

type Run = { id: string; status: string; result_status: string | null; mode: string | null; duration_s: number | null };

export default function Dashboard() {
  const { period } = usePeriod();
  const sched = useApi<any>(period ? `/periods/${period.id}/schedule` : null);
  const conf = useApi<{ hard_violations: string[] }>(period ? `/periods/${period.id}/conflicts` : null);
  const runs = useApi<Run[]>("/runs");
  const a = sched.data?.assignments ?? [];
  const total = a.reduce((s: number, x: any) => s + x.effective_minutes, 0);
  const last = runs.data?.[0];
  return (
    <Page>
      <h1 className="mb-3 text-2xl font-semibold">{t("nav.dashboard")}{period ? ` — ${period.name}` : ""}</h1>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card title="Heures planifiées"><p className="text-3xl font-semibold">{hours(total)}</p><p className="muted text-sm">{a.length} affectations</p></Card>
        <Card title="Shifts non couverts"><p className="text-3xl font-semibold">{sched.data?.uncovered?.length ?? "–"}</p></Card>
        <Card title="Violations dures"><p className={`text-3xl font-semibold ${conf.data?.hard_violations.length ? "tag-bad" : "tag-ok"}`}>{conf.data?.hard_violations.length ?? "–"}</p></Card>
        <Card title="Dernière génération">
          <p className="font-semibold">{last?.result_status ?? last?.status ?? "Aucune"}</p>
          {last?.mode === "simulation_exploratoire" && <p className="tag-warn text-sm">{t("exploratory")}</p>}
        </Card>
      </div>
      <Card title="Données à renseigner">
        <ul className="list-disc pl-5 text-sm">
          <li>Contrats individuels (taux d'activité, plafonds) — <strong>{t("to_fill")}</strong></li>
          <li>Jours et horaires Lindt et Toblerone (64 h chacun) — <strong>{t("to_fill")}</strong></li>
          <li>Disponibilités complètes, congés et absences</li>
          <li>Validation juridique des règles de repos et de durée</li>
        </ul>
      </Card>
    </Page>
  );
}
