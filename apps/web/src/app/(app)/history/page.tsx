"use client";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { HistoryFeed } from "@/components/HistoryFeed";
import { Card, PageHead } from "@/components/ui/primitives";

function Inner() {
  const sp = useSearchParams();
  const employee = sp.get("employee") ?? undefined;
  const period = sp.get("period") ?? undefined;
  return (
    <>
      <PageHead eyebrow="Qui a modifié quoi, et quand" title="Historique des modifications" />
      <Card className="history-page">
        <HistoryFeed employeeId={employee} periodId={period} />
      </Card>
    </>
  );
}

/** Historique des modifications du planning : ajouts, suppressions, remplacements, échanges, horaires, générations, restaurations, publications. */
export default function History() {
  return <Suspense fallback={null}><Inner /></Suspense>;
}
