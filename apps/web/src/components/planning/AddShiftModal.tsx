"use client";
import { useEffect, useMemo, useState } from "react";
import { Button, Callout, Field, Select } from "@/components/ui/primitives";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { useApi } from "@/components/hooks";
import { api } from "@/lib/api";
import { brandColor } from "@/lib/brand";
import { LEVEL_LABEL, type Level } from "@/lib/brandGroups";
import { longDate } from "@/lib/reassign";

type Sched = { template_id: string; template: string; start: string; end: string; site: string; break_minutes: number };
export type AddTarget = { emp: { id: string; name: string; brands?: Record<string, string> }; day: string } | null;

/** Ajout manuel d'un shift : seules les marques autorisées au collaborateur sont proposées, puis uniquement les horaires de cette marque. */
export function AddShiftModal({ target, periodId, onClose, onAdded }: { target: AddTarget; periodId: string; onClose: () => void; onAdded: () => void }) {
  const toast = useToast();
  const schedules = useApi<Record<string, Sched[]>>(target ? "/brand-schedules" : null);
  const brands = useMemo(() => Object.keys(target?.emp.brands ?? {}).sort(), [target]);
  const [brand, setBrand] = useState(""); const [tpl, setTpl] = useState(""); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { setBrand(brands[0] ?? ""); setErr(""); }, [brands, target]);
  const list = (brand && schedules.data?.[brand]) || [];
  useEffect(() => { setTpl(list[0]?.template_id ?? ""); }, [brand, schedules.data]); // eslint-disable-line react-hooks/exhaustive-deps

  async function add() {
    if (!target) return; setBusy(true); setErr("");
    try {
      await api(`/periods/${periodId}/assignments`, { method: "POST", json: { employee_id: target.emp.id, day: target.day, brand_code: brand, template_id: tpl } });
      toast.push(`Shift ajouté pour ${target.emp.name} (verrouillé : la réoptimisation ne le déplacera pas).`, "ok"); onAdded();
    } catch (e: unknown) { setErr(e instanceof Error ? e.message : "Ajout impossible"); }
    finally { setBusy(false); }
  }
  const hh = (t: string) => `${t.slice(0, 2)}h${t.slice(3, 5)}`;
  return (
    <Modal open={!!target} onClose={() => !busy && onClose()} title={target ? `Ajouter un shift — ${target.emp.name}` : ""} description={target ? longDate(target.day) : undefined}>
      {target && (
        <div className="stack">
          {brands.length === 0 ? <Callout kind="warn">Aucune marque autorisée pour ce collaborateur : cochez des marques dans sa fiche.</Callout> : (
            <>
              <Field label="Marque ou boutique" help="Seules les marques autorisées dans la fiche sont proposées.">{(p) => (
                <Select {...p} value={brand} onChange={(e) => setBrand(e.target.value)}>
                  {brands.map((b) => <option key={b} value={b}>{b} — {LEVEL_LABEL[(target.emp.brands?.[b] ?? "priority") as Level]}</option>)}
                </Select>)}</Field>
              <Field label="Horaire" help={list.length ? `Horaires autorisés pour ${brand}` : "Aucun horaire défini pour cette marque."}>{(p) => (
                <Select {...p} value={tpl} onChange={(e) => setTpl(e.target.value)} disabled={!list.length}>
                  {list.map((x) => <option key={x.template_id} value={x.template_id}>{hh(x.start)}–{hh(x.end)} · {x.site} · 1 h de pause = 8 h effectives</option>)}
                </Select>)}</Field>
              {brand && <p className="help"><i className="dot" style={{ ["--c" as string]: brandColor(brand) }} /> Le shift sera verrouillé : aucune réoptimisation ne le déplacera en silence.</p>}
            </>
          )}
          {err && <Callout kind="bad" title="Ajout refusé">{err}</Callout>}
          <div className="row modal-actions"><Button onClick={onClose} disabled={busy}>Annuler</Button><Button variant="primary" onClick={add} disabled={busy || !brand || !tpl}>{busy ? "Ajout…" : "Ajouter le shift"}</Button></div>
        </div>
      )}
    </Modal>
  );
}
