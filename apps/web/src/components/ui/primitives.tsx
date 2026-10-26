import { forwardRef, useId } from "react";
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";
import { Icon, type IconName } from "./Icon";

export const cx = (...a: (string | false | null | undefined)[]) => a.filter(Boolean).join(" ");

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "default" | "primary" | "ghost" | "danger"; size?: "md" | "sm"; icon?: IconName; iconOnly?: boolean; label?: string };
export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button({ variant = "default", size = "md", icon, iconOnly, label, className, children, type = "button", ...rest }, ref) {
  return (
    <button ref={ref} type={type} aria-label={iconOnly ? label : undefined} className={cx("btn", variant !== "default" && `btn-${variant}`, size === "sm" && "btn-sm", iconOnly && "btn-icon", className)} {...rest}>
      {icon && <Icon name={icon} size={size === "sm" ? 14 : 16} />}
      {!iconOnly && children}
    </button>
  );
});

export function Badge({ tone = "neutral", icon, children, ...rest }: { tone?: "neutral" | "ok" | "warn" | "bad" | "info" | "accent"; icon?: IconName; children: ReactNode } & HTMLAttributes<HTMLSpanElement>) {
  return <span className={cx("badge", tone !== "neutral" && `badge-${tone}`)} {...rest}>{icon && <Icon name={icon} size={12} />}{children}</span>;
}

export function Card({ title, eyebrow, actions, children, className, lift }: { title?: string; eyebrow?: string; actions?: ReactNode; children: ReactNode; className?: string; lift?: boolean }) {
  const id = useId();
  return (
    <section className={cx("glass card rise", lift && "lift", className)} aria-labelledby={title ? id : undefined}>
      {(title || actions) && (
        <header className="card-head">
          <div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}{title && <h2 id={id} className="h2">{title}</h2>}</div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function Field({ label, help, error, children }: { label: string; help?: string; error?: string; children: (p: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode }) {
  const id = useId(); const hid = `${id}-h`;
  return (
    <div className="field">
      <label className="label" htmlFor={id}>{label}</label>
      {children({ id, "aria-describedby": help || error ? hid : undefined, "aria-invalid": error ? true : undefined })}
      {error ? <p id={hid} className="error-text" role="alert">{error}</p> : help ? <p id={hid} className="help">{help}</p> : null}
    </div>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) { return <input ref={ref} className={cx("input", className)} {...p} />; });
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, ...p }, ref) { return <select ref={ref} className={cx("select", className)} {...p} />; });

export function SearchInput(p: InputHTMLAttributes<HTMLInputElement>) {
  return <div className="search"><Icon name="search" size={16} /><input type="search" className="input" {...p} /></div>;
}

export function Tooltip({ text, children }: { text: string; children: ReactNode }) {
  const id = useId();
  return <span className="tip" aria-describedby={id}>{children}<span id={id} role="tooltip" className="tip-bubble">{text}</span></span>;
}

export function Skeleton({ w, h = "1rem", className }: { w?: string; h?: string; className?: string }) {
  return <div className={cx("skeleton", className)} style={{ width: w, height: h }} aria-hidden="true" />;
}
export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return <div className="glass card" role="status" aria-busy="true" aria-label="Chargement"><Skeleton w="40%" h="1.25rem" /><div className="stack" style={{ marginTop: "1rem" }}>{Array.from({ length: lines }, (_, i) => <Skeleton key={i} w={`${90 - i * 12}%`} />)}</div></div>;
}

export function EmptyState({ icon = "info", title, children, action }: { icon?: IconName; title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="empty"><span className="ico"><Icon name={icon} size={22} /></span><p className="h2" style={{ color: "var(--fg)" }}>{title}</p>{children && <p style={{ maxWidth: "36ch" }}>{children}</p>}{action}</div>;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div className="callout" data-kind="bad" role="alert"><Icon name="alert" /><div className="stack" style={{ gap: ".25rem" }}><p className="h2">Une erreur est survenue</p><p className="muted">{message}</p>{onRetry && <div><Button size="sm" onClick={onRetry}>Réessayer</Button></div>}</div></div>;
}

export function Callout({ kind = "info", title, children, icon }: { kind?: "info" | "warn" | "bad" | "ok"; title?: string; children: ReactNode; icon?: IconName }) {
  return <div className="callout" data-kind={kind} role={kind === "bad" ? "alert" : "note"}><Icon name={icon ?? (kind === "ok" ? "check" : kind === "info" ? "info" : "alert")} /><div>{title && <p className="h2">{title}</p>}<div className="muted" style={{ color: "var(--fg)" }}>{children}</div></div></div>;
}

export function Progress({ value, label, color }: { value: number; label: string; color?: string }) {
  return <div className="progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value)}><span style={{ ["--value" as string]: value, ...(color ? { ["--c" as string]: color } : {}) }} /></div>;
}

export function PageHead({ eyebrow, title, children }: { eyebrow?: string; title: string; children?: ReactNode }) {
  return <header className="page-head"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1 className="title">{title}</h1></div>{children && <div className="row">{children}</div>}</header>;
}
