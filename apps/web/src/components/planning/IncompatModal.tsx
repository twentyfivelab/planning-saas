"use client";
import { useEffect, useState } from "react";
import { Badge, Button, Callout, EmptyState } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { api } from "@/lib/api";
import { errText } from "@/lib/wfm";

export type IncompatShift = { slot_id: string; day: string; start: string; end: string; site: string; site_name?: string; brands?: string[] };
export type IncompatItem = {
  kind: "obligatoire" | "preference"; code: string; rule: string; employee_id: string | null; employee_uuid?: string | null; employee: string;
  shifts: IncompatShift[]; days: string[]; reason: string; limit: string | null; reached: string | null; text: string;
};
export type CapNotice = { cap_minutes: number; plan_cap_minutes: number | null; over: { employee: string; minutes: number; label: string }[] };
export type CompatReport = {
  hard: string[]; soft: { text: string; employee: string }[]; items: IncompatItem[]; checked: number; flagged_assignment_ids: string[];
  locked: number; unlocked: number; has_plan: boolean; compatible: boolean;
  params: { mode: "frozen" | "current"; requested: "plan" | "current"; frozen_at: string | null; source: string | null; monthly_cap_minutes: number | null };
  cap_notice?: CapNotice;
  official?: boolean;
  removed_notice?: { employee: string; removed_on: string; assignments: number }[];
};

const DOW = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
export const dayFr = (iso: string) => { const d = new Date(`${iso}T12:00:00`); return `${DOW[d.getDay()]} ${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`; };

function Shifts({ it }: { it: IncompatItem }) {
  const [all, setAll] = useState(false);
  if (!it.shifts.length) return <span className="faint">{it.days.length ? it.days.map(dayFr).join(", ") : it.code === "MIN_DAYS_NOT_REACHED" ? "Tout le mois" : "—"}</span>;
  const list = all ? it.shifts : it.shifts.slice(0, 3);
  return (
    <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {list.map((s) => <li key={s.slot_id} className="nowrap"><strong>{dayFr(s.day)}</strong> · {s.start}–{s.end} · {s.site_name ?? s.site}{s.brands?.length ? ` · ${s.brands.join(" / ")}` : ""}</li>)}
      {it.shifts.length > 3 && <li><button type="button" className="link-btn" onClick={() => setAll(!all)}>{all ? "Réduire" : `… et ${it.shifts.length - 3} autre(s) shift(s)`}</button></li>}
    </ul>
  );
}

function Table({ items }: { items: IncompatItem[] }) {
  return (
    <div className="table-wrap"><table className="table table-cards">
      <thead><tr><th>Collaborateur</th><th>Date · horaires · site · marque</th><th>Règle concernée</th><th>Raison précise</th></tr></thead>
      <tbody>{items.map((it, i) => (
        <tr key={`${it.text}-${i}`}>
          <td className="cell-main nowrap" data-label="Collaborateur"><strong>{it.employee}</strong></td>
          <td data-label="Date · horaires · site"><Shifts it={it} /></td>
          <td data-label="Règle">{it.rule}{it.limit && it.reached && <div className="faint">limite : {it.limit} · atteint : {it.reached}</div>}</td>
          <td data-label="Raison">{it.reason}</td>
        </tr>))}</tbody>
    </table></div>
  );
}

/** Détail des incompatibilités d'un planning : avec SES paramètres (par défaut) ou avec les paramètres actuels (aperçu). */
export function IncompatModal({ open, onClose, periodId, periodName, params = "plan", employeeCode, employeeName }: {
  open: boolean; onClose: () => void; periodId: string; periodName?: string; params?: "plan" | "current"; employeeCode?: string; employeeName?: string;
}) {
  const [data, setData] = useState<CompatReport | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    setData(null); setError("");
    api<CompatReport>(`/periods/${periodId}/compatibility?params=${params}`).then(setData).catch((e) => setError(errText(e)));
  }, [open, periodId, params]);
  const items = (data?.items ?? []).filter((i) => !employeeCode || i.employee_id === employeeCode);
  const hard = items.filter((i) => i.kind === "obligatoire");
  const soft = items.filter((i) => i.kind !== "obligatoire");
  const scope = params === "current" ? "avec les paramètres actuels (s'ils étaient appliqués à ce planning)" : "avec les paramètres de ce planning";
  return (
    <Modal open={open} onClose={onClose} title={`Incompatibilités${periodName ? ` — ${periodName}` : ""}${employeeName ? ` — ${employeeName}` : ""}`} description={`Détail ${scope}. Rien n'est modifié.`}>
      <div className="stack" data-testid="incompat-detail">
        {error && <Callout kind="bad">{error}</Callout>}
        {!data && !error && <div className="skeleton" style={{ height: "10rem" }} aria-hidden="true" />}
        {data && (
          <>
            <p className="row" style={{ margin: 0 }}>
              <Badge tone={hard.length ? "bad" : "ok"} icon={hard.length ? "alert" : "check"}>{hard.length} contrainte{hard.length > 1 ? "s" : ""} obligatoire{hard.length > 1 ? "s" : ""} non respectée{hard.length > 1 ? "s" : ""}</Badge>
              <Badge tone={soft.length ? "warn" : "ok"}>{soft.length} préférence{soft.length > 1 ? "s" : ""} non respectée{soft.length > 1 ? "s" : ""}</Badge>
              <span className="help">{data.checked} affectation(s) vérifiée(s)</span>
            </p>
            {!items.length && <EmptyState icon="check" title="Aucune incompatibilité">Toutes les affectations vérifiées respectent ces paramètres.</EmptyState>}
            {hard.length > 0 && <section className="stack" style={{ gap: "var(--sp-2)" }}>
              <h3 className="h2" style={{ margin: 0 }}>Contraintes obligatoires non respectées</h3>
              <p className="help" style={{ margin: 0 }}>Règles strictes : à corriger (réaffectation manuelle, réoptimisation, ou modification du paramètre en cause).</p>
              <Table items={hard} />
            </section>}
            {soft.length > 0 && <section className="stack" style={{ gap: "var(--sp-2)" }}>
              <h3 className="h2" style={{ margin: 0 }}>Préférences non respectées</h3>
              <p className="help" style={{ margin: 0 }}>Souhaits et objectifs non atteints : ils n&apos;empêchent pas le planning, le moteur les satisfait dans la mesure du possible.</p>
              <Table items={soft} />
            </section>}
            {data.cap_notice && data.cap_notice.over.length > 0 && !employeeCode && <CapNoticeBox notice={data.cap_notice} />}
          </>
        )}
        <div className="row modal-actions"><Button variant="primary" onClick={onClose}>Fermer</Button></div>
      </div>
    </Modal>
  );
}

export function CapNoticeBox({ notice }: { notice: CapNotice }) {
  const cap = Math.round(notice.cap_minutes / 60);
  return (
    <Callout kind="info" title={`Plafond mensuel de ${cap} h : établi après ce planning`}>
      <p style={{ margin: 0 }}>Ce planning a été établi avant l&apos;activation du plafond de {cap} h de travail effectif par collaborateur et par mois. Il le dépasse pour : {notice.over.map((o) => `${o.employee} (${o.label})`).join(", ")}.</p>
      <p style={{ margin: "var(--sp-1) 0 0" }}>Ce dépassement n&apos;est pas compté comme une incompatibilité de ce planning et rien n&apos;a été modifié. Toute nouvelle génération et toute modification manuelle respectent le plafond ; une modification qui réduit les heures reste possible.</p>
    </Callout>
  );
}
