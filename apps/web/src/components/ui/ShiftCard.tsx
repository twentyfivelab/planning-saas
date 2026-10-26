import { Icon } from "./Icon";
import { brandVars, brandColor } from "@/lib/brand";
import { KIND_LABEL, fmtHM, mainBrand, shiftKind, timeShort, type Assignment } from "@/lib/schedule";
import { splitShares } from "@/lib/metrics";
import { Tooltip } from "./primitives";

/** Carte de shift : marque (couleur + libellé), site, horaires, durée effective, pause, verrouillage, alerte, répartition co-branding. */
export function ShiftCard({ a, size = "sm", alerts = [], dragging, draggable, onOpen, onDragStart, onDragEnd, showEmployee }: {
  a: Assignment; size?: "sm" | "lg"; alerts?: string[]; dragging?: boolean; draggable?: boolean; showEmployee?: boolean;
  onOpen: (a: Assignment) => void; onDragStart?: (a: Assignment) => void; onDragEnd?: () => void;
}) {
  const brand = mainBrand(a.allocations);
  const shares = splitShares(a.allocations);
  const kind = shiftKind(a.start, a.end);
  const brands = Object.keys(a.allocations).join(" + ");
  const label = `${a.employee}, ${brands}, ${a.site}, ${timeShort(a.start)} à ${timeShort(a.end)}, ${fmtHM(a.effective_minutes)} effectives, pause ${a.break_minutes} min${a.locked ? ", verrouillé" : ""}${alerts.length ? `, ${alerts.length} alerte(s)` : ""}`;
  return (
    <button type="button" className={`shift ${size === "lg" ? "shift-lg" : ""}`} style={brandVars(brand)} draggable={draggable} data-dragging={dragging || undefined}
      data-locked={a.locked || undefined} data-alert={alerts.length > 0 || undefined} aria-label={label} title={alerts.join("\n") || undefined}
      onClick={() => onOpen(a)} onDragStart={(e) => { e.dataTransfer.setData("text/plain", a.assignment_id); e.dataTransfer.effectAllowed = "move"; onDragStart?.(a); }} onDragEnd={onDragEnd}>
      <span className="shift-time">
        <span>{timeShort(a.start)}–{timeShort(a.end)}</span>
        <span className="shift-flags">
          {a.locked && <Tooltip text="Verrouillé : conservé lors d'une réoptimisation"><Icon name="lock" size={12} /></Tooltip>}
          {alerts.length > 0 && <Icon name="alert" size={12} style={{ color: "var(--warn)" }} />}
        </span>
      </span>
      {showEmployee && <span style={{ fontWeight: 600 }}>{a.employee}</span>}
      <span className="shift-meta">
        <span>{brands}</span>{!a.site.split("/").every((p) => brands.includes(p)) && <span>{a.site}</span>}
      </span>
      <span className="shift-meta num" aria-hidden="true">
        <span className="nowrap">{fmtHM(a.effective_minutes)} · pause {a.break_minutes >= 60 && a.break_minutes % 60 === 0 ? `${a.break_minutes / 60} h` : `${a.break_minutes} min`}</span>{size === "lg" && <span>{KIND_LABEL[kind]}</span>}
      </span>
      {shares.length > 1 && (
        <span className="splitbar" aria-hidden="true">{shares.map((s) => <span key={s.brand} style={{ ["--share" as string]: s.pct, ["--c" as string]: brandColor(s.brand) }} />)}</span>
      )}
      {shares.length > 1 && size === "lg" && <span className="shift-meta">{shares.map((s) => `${s.brand} ${fmtHM(s.minutes)}`).join(" · ")}</span>}
    </button>
  );
}
