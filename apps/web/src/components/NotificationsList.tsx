"use client";
import { useApi } from "@/components/hooks";
import { Badge, Button, Card, EmptyState, ErrorState } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { invalidate } from "@/lib/invalidate";

export type Note = { id: string; kind: string; title: string; body: string | null; read: boolean; at: string; payload?: { month?: string; period_id?: string } | null };
type Notes = { unread: number; items: Note[] };

const fmt = (iso: string) => new Intl.DateTimeFormat("fr-CH", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Zurich" }).format(new Date(iso));

/** Notifications du compte connecté (publications, demandes, couverture d'une marque ajoutée…), avec lien vers le planning concerné. */
export function NotificationsList({ empty }: { empty: string }) {
  const n = useApi<Notes>("/notifications");
  async function read(id?: string) { await api(id ? `/notifications/${id}/read` : "/notifications/read-all", { method: "POST" }); n.reload(); invalidate(); }
  const open = (x: Note) => {
    if (x.payload?.month) { try { localStorage.setItem("planning:month", x.payload.month); } catch { /* préférence locale seulement */ } }
    if (!x.read) void read(x.id);
    window.location.assign("/planning");
  };
  return (
    <Card title="Notifications" actions={n.data?.unread ? <Button size="sm" onClick={() => read()}>Tout marquer comme lu</Button> : undefined}>
      {n.error ? <ErrorState message={n.error} onRetry={n.reload} /> : !n.data?.items.length ? <EmptyState icon="bell" title="Aucune notification">{empty}</EmptyState> : (
        <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0, gap: "var(--sp-2)" }} data-testid="notifications">
          {n.data.items.map((x) => (
            <li key={x.id} className="surface" style={{ padding: "var(--sp-3)" }} data-testid="notification" data-kind={x.kind} data-read={x.read}>
              <div className="spread"><div><strong>{x.title}</strong>{!x.read && <> <Badge tone="accent">Nouveau</Badge></>}
                <p className="muted" style={{ margin: 0 }}>{x.body}</p><p className="help" style={{ margin: 0 }}><time dateTime={x.at}>{fmt(x.at)}</time></p></div>
                <div className="row">
                  {x.kind.startsWith("coverage_") && x.payload?.month && <Button size="sm" onClick={() => open(x)}>Ouvrir le planning</Button>}
                  {!x.read && <Button size="sm" variant="ghost" onClick={() => read(x.id)}>Marquer comme lu</Button>}
                </div></div>
            </li>))}
        </ul>)}
    </Card>
  );
}
