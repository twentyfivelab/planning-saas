import { cx } from "./primitives";

/** Anneau de progression (SVG, sans dépendance). */
export function Ring({ value, label, size = 112, stroke = 12, color = "var(--accent)", children }: { value: number; label: string; size?: number; stroke?: number; color?: string; children?: React.ReactNode }) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, v = Math.max(0, Math.min(100, value));
  return (
    <div style={{ position: "relative", width: size, height: size }} role="img" aria-label={`${label} : ${Math.round(v)} %`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--solid-3)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round" strokeDasharray={`${(c * v) / 100} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} style={{ transition: "stroke-dasharray .6s var(--ease)" }} />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center" }}>{children}</div>
    </div>
  );
}

export type BarDatum = { key: string; label: string; value: number; max?: number; color?: string; right?: string; note?: React.ReactNode };

/** Liste de barres horizontales (heures par marque / collaborateur). `max` commun si non précisé. */
export function BarList({ data, className }: { data: BarDatum[]; className?: string }) {
  const max = Math.max(1, ...data.map((d) => d.max ?? d.value));
  return (
    <div className={cx("bars", className)} role="list">
      {data.map((d) => (
        <div key={d.key} className="bar-row" role="listitem">
          <span style={{ display: "inline-flex", alignItems: "center", gap: ".5rem", minWidth: 0 }}>
            {d.color && <i className="dot" style={{ ["--c" as string]: d.color }} />}<span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.label}</span>
          </span>
          <div className="progress" role="progressbar" aria-label={d.label} aria-valuemin={0} aria-valuemax={Math.round(d.max ?? max)} aria-valuenow={Math.round(d.value)}>
            <span style={{ ["--value" as string]: (100 * d.value) / (d.max ?? max), ["--c" as string]: d.color ?? "var(--accent)" }} />
          </div>
          <span className="num" style={{ textAlign: "right", whiteSpace: "nowrap" }}>{d.right ?? Math.round(d.value)} {d.note}</span>
        </div>
      ))}
    </div>
  );
}
