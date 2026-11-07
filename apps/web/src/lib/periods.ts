export type PeriodStatus = "draft" | "generated" | "in_review" | "validated" | "published" | "archived";
export type PeriodRow = { id: string; name: string; start_date: string; end_date: string; status: PeriodStatus; status_label: string; assignments: number; wizard_step: number | null; archived_at: string | null; changed_since?: boolean };
export const STATUS_TONE: Record<PeriodStatus, "neutral" | "info" | "ok" | "warn" | "accent"> = { draft: "warn", generated: "info", in_review: "accent", validated: "ok", published: "ok", archived: "neutral" };
/** Un brouillon s'ouvre dans l'assistant (là où on s'était arrêté) ; un planning généré s'ouvre dans le planning. */
export const periodHref = (p: PeriodRow) => (p.status === "draft" ? `/plannings/new?period=${p.id}` : "/planning");
