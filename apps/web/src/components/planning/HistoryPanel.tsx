"use client";
import { Badge, Callout, EmptyState } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useApi } from "@/components/hooks";
import type { HistoryRow } from "@/lib/manualShift";
import { hourRange, longDate } from "@/lib/reassign";

const when = (iso: string) => new Date(iso).toLocaleString("fr-CH", { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Zurich" });

/** Historique des modifications manuelles : quel collaborateur a été remplacé, par qui, quand. */
export function HistoryPanel({ open, periodId, employeeId, onClose }: { open: boolean; periodId: string; employeeId?: string; onClose: () => void }) {
  const h = useApi<HistoryRow[]>(open ? `/periods/${periodId}/history${employeeId ? `?employee_id=${employeeId}` : ""}` : null);
  return (
    <Modal open={open} onClose={onClose} title="Historique des modifications" description={employeeId ? "Modifications concernant le collaborateur filtré." : "Attributions, transferts et retraits manuels de la période."}>
      {h.error ? <Callout kind="bad" title="Chargement impossible">{h.error}</Callout> : !h.data?.length ? <EmptyState title="Aucune modification manuelle">Les attributions, transferts et retraits apparaîtront ici.</EmptyState> : (
        <ol className="history-list" aria-label="Modifications manuelles">
          {h.data.map((r) => (
            <li key={r.id} className="history-item">
              <div className="row"><Badge tone={r.kind === "Retrait" ? "bad" : r.kind === "Transfert" || r.kind === "Réaffectation" ? "info" : "ok"}>{r.kind}</Badge>{r.forced && <Badge tone="warn" icon="alert">Dérogation</Badge>}<span className="faint num">{when(r.at)}</span></div>
              <p><strong>{r.from && r.to ? `${r.from} remplacé·e par ${r.to}` : r.to ? `${r.to} ajouté·e` : `${r.from} retiré·e`}</strong>{" "}
                {r.day && <span className="muted">· {longDate(r.day)}{r.site ? ` · ${r.site}` : ""}{r.start && r.end ? ` · ${hourRange(r.start, r.end)}` : ""}</span>}</p>
              <p className="help">Par {r.by}{r.reason ? ` — motif : ${r.reason}` : ""}</p>
              {r.issues.length > 0 && <ul className="help" style={{ margin: 0, paddingLeft: "1.1rem" }}>{r.issues.map((i) => <li key={i}>{i}</li>)}</ul>}
            </li>))}
        </ol>
      )}
    </Modal>
  );
}
