"use client";
import { Card, Page } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { t } from "@/lib/i18n";

export default function Alerts() {
  const { period } = usePeriod();
  const c = useApi<{ hard_violations: string[] }>(period ? `/periods/${period.id}/conflicts` : null);
  const s = useApi<{ uncovered: { slot_key: string; day: string; start: string }[] }>(period ? `/periods/${period.id}/schedule` : null);
  const runs = useApi<{ id: string }[]>("/runs");
  const diag = useApi<any>(runs.data?.[0] ? `/runs/${runs.data[0].id}/diagnostic` : null);
  return (
    <Page>
      <h1 className="mb-3 text-2xl font-semibold">{t("nav.alerts")}</h1>
      <Card title="Violations de contraintes dures">{c.data?.hard_violations.length ? <ul className="tag-bad list-disc pl-5 text-sm">{c.data.hard_violations.map((v) => <li key={v}>{v}</li>)}</ul> : <p className="tag-ok text-sm">Aucune violation détectée par le vérificateur.</p>}</Card>
      <Card title={`Shifts non couverts (${s.data?.uncovered.length ?? 0})`}><ul className="text-sm">{s.data?.uncovered.map((u) => <li key={u.slot_key}>{u.day} {u.start.slice(0, 5)} — {u.slot_key}</li>)}</ul></Card>
      <Card title="Diagnostic de la dernière exécution"><ul className="space-y-2 text-sm">{[...(diag.data?.report.diagnostics ?? []), ...(diag.data?.report.missing_data ?? [])].map((i: any, n: number) => <li key={n} className="surface p-2"><strong>{i.code}</strong> ({i.severity}) — {i.message}</li>)}</ul></Card>
    </Page>
  );
}
