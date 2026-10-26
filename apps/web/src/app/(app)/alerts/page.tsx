"use client";
import Link from "next/link";
import { useApi, usePeriod } from "@/components/hooks";
import { Badge, Callout, Card, EmptyState, ErrorState, PageHead, SkeletonCard } from "@/components/ui/primitives";
import { issueTitle } from "@/lib/issues";
import { dayLabel, timeShort } from "@/lib/schedule";
import { t } from "@/lib/i18n";

type Issue = { code: string; severity: string; message: string; suggestions?: string[]; slots?: string[] };
const TONE = { blocking: "bad", warning: "warn", info: "info" } as const;
const SEV = { blocking: "Bloquant", warning: "Avertissement", info: "Information" } as const;

export default function Alerts() {
  const { period } = usePeriod();
  const c = useApi<{ hard_violations: string[] }>(period ? `/periods/${period.id}/conflicts` : null);
  const s = useApi<{ uncovered: { slot_key: string; day: string; start: string; site: string }[] }>(period ? `/periods/${period.id}/schedule` : null);
  const runs = useApi<{ id: string; status: string }[]>("/runs");
  const lastDone = runs.data?.find((r) => r.status === "termine");
  const diag = useApi<{ report: { missing_data: Issue[]; diagnostics: Issue[] }; status: string }>(lastDone ? `/runs/${lastDone.id}/diagnostic` : null);
  const issues = [...(diag.data?.report.diagnostics ?? []), ...(diag.data?.report.missing_data ?? [])];
  const err = c.error || s.error;
  return (
    <>
      <PageHead eyebrow="Conflits, manques et diagnostic" title={t("nav.alerts")} />
      {err ? <ErrorState message={err} onRetry={() => { c.reload(); s.reload(); }} /> : (c.loading || s.loading) && !c.data ? <SkeletonCard lines={4} /> : (
        <>
          <Card title="Violations de contraintes dures" actions={<Badge tone={c.data?.hard_violations.length ? "bad" : "ok"}>{c.data?.hard_violations.length ?? 0}</Badge>}>
            {c.data?.hard_violations.length ? <ul className="stack" style={{ margin: 0, paddingLeft: "1.1rem" }}>{c.data.hard_violations.map((v) => <li key={v} style={{ color: "var(--bad)" }}>{v}</li>)}</ul>
              : <Callout kind="ok">Aucune violation détectée par le vérificateur indépendant.</Callout>}
          </Card>
          <Card title="Shifts non couverts" actions={<Badge tone={s.data?.uncovered.length ? "warn" : "ok"}>{s.data?.uncovered.length ?? 0}</Badge>}>
            {s.data?.uncovered.length ? <ul className="stack" style={{ margin: 0, paddingLeft: "1.1rem" }}>{s.data.uncovered.map((u) => <li key={u.slot_key}>{dayLabel(u.day)} {timeShort(u.start)} — {u.site}</li>)}</ul>
              : <Callout kind="ok">Tous les shifts définis sont pourvus.</Callout>}
          </Card>
          <Card title="Diagnostic de la dernière génération" actions={<Link href="/generate" className="btn btn-sm">Relancer</Link>}>
            {!issues.length ? <EmptyState icon="info" title="Aucun diagnostic">Lancez une génération pour obtenir un diagnostic.</EmptyState> : (
              <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {issues.map((i, n) => (
                  <li key={n} className="surface" style={{ padding: "var(--sp-3) var(--sp-4)" }}>
                    <div className="row"><Badge tone={TONE[i.severity as keyof typeof TONE] ?? "neutral"}>{SEV[i.severity as keyof typeof SEV] ?? i.severity}</Badge><strong>{issueTitle(i.code)}</strong><span className="mono faint">{i.code}</span></div>
                    <p style={{ margin: "var(--sp-2) 0" }}>{i.message}</p>
                    {!!i.suggestions?.length && <ul className="muted" style={{ margin: 0, paddingLeft: "1.1rem" }}>{i.suggestions.map((x) => <li key={x}>{x}</li>)}</ul>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </>
  );
}
