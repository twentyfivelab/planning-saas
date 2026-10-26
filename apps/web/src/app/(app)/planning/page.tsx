"use client";
import { useMemo, useRef, useState } from "react";
import { Card, Page, useMe } from "@/components/Shell";
import { useApi, usePeriod } from "@/components/hooks";
import { api } from "@/lib/api";
import { Assignment, History, daysBetween, filterAssignments, hours, weekStart, weekdayIdx } from "@/lib/schedule";
import { t } from "@/lib/i18n";

type Schedule = { assignments: Assignment[]; uncovered: { shift_id: string; slot_key: string; day: string; site: string; start: string; end: string }[] };
type Emp = { id: string; code: string; name: string };
const VIEWS = ["month", "week", "day", "employee", "brand"] as const;
type View = (typeof VIEWS)[number];
const DOW = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

export default function PlanningPage() {
  const me = useMe();
  const canEdit = me.permissions.includes("planning.edit");
  const { periods, period, setId } = usePeriod();
  const sched = useApi<Schedule>(period ? `/periods/${period.id}/schedule` : null);
  const emps = useApi<Emp[]>("/employees");
  const [view, setView] = useState<View>("week");
  const [focusDay, setFocusDay] = useState<string>("");
  const [text, setText] = useState(""); const [site, setSite] = useState(""); const [brand, setBrand] = useState(""); const [empF, setEmpF] = useState("");
  const [sel, setSel] = useState<Assignment | null>(null);
  const [conflicts, setConflicts] = useState<string[]>([]);
  const [msg, setMsg] = useState("");
  const history = useRef(new History());
  const [, force] = useState(0);

  const days = useMemo(() => (period ? daysBetween(period.start_date, period.end_date) : []), [period]);
  const day = focusDay || days[0] || "";
  const all = useMemo(() => sched.data?.assignments ?? [], [sched.data]);
  const list = useMemo(() => filterAssignments(all, { text, site, brand, employee: empF }), [all, text, site, brand, empF]);
  const sites = [...new Set(all.map((a) => a.site))]; const brands = [...new Set(all.flatMap((a) => Object.keys(a.allocations)))];

  async function reassign(a: Assignment, to: string, record = true) {
    if (a.locked) { setMsg("Affectation verrouillée."); return; }
    try {
      const r = await api<{ conflicts: string[] }>(`/assignments/${a.assignment_id}`, { method: "PUT", json: { employee_id: to } });
      if (record) history.current.push({ assignmentId: a.assignment_id, from: a.employee_id, to });
      setConflicts(r.conflicts); setMsg(r.conflicts.length ? `${r.conflicts.length} conflit(s) détecté(s)` : "Modification enregistrée"); sched.reload(); force((x) => x + 1);
    } catch (e: any) { setMsg(String(e.message)); }
  }
  async function step(kind: "undo" | "redo") {
    const m = kind === "undo" ? history.current.undo() : history.current.redo(); if (!m) return;
    const target = kind === "undo" ? m.from : m.to;
    const a = all.find((x) => x.assignment_id === m.assignmentId); if (a) await reassign(a, target, false);
  }
  async function toggleLock(a: Assignment) {
    await api(`/assignments/${a.assignment_id}/${a.locked ? "unlock" : "lock"}`, { method: "POST" }); sched.reload(); setSel(null);
  }
  async function editTimes(a: Assignment, f: FormData) {
    try {
      const r = await api<{ conflicts: string[] }>(`/shifts/${a.shift_id}`, { method: "PATCH", json: { start_time: f.get("s"), end_time: f.get("e"), break_minutes: Number(f.get("b")) } });
      setConflicts(r.conflicts); sched.reload(); setSel(null);
    } catch (e: any) { setMsg(String(e.message)); }
  }

  const chip = (a: Assignment) => (
    <button key={a.assignment_id} draggable={canEdit && !a.locked} data-locked={a.locked} className="chip w-full text-left"
      onDragStart={(e) => e.dataTransfer.setData("text/plain", a.assignment_id)} onClick={() => setSel(a)}
      aria-label={`${a.employee}, ${a.site}, ${a.start.slice(0, 5)} à ${a.end.slice(0, 5)}${a.locked ? ", verrouillé" : ""}`}>
      {a.locked ? "🔒 " : ""}{a.start.slice(0, 5)}–{a.end.slice(0, 5)} {a.site}
    </button>
  );
  const drop = (e: React.DragEvent, empId: string, d: string) => {
    e.preventDefault(); const id = e.dataTransfer.getData("text/plain"); const a = all.find((x) => x.assignment_id === id);
    if (a && a.day === d && a.employee_id !== empId) reassign(a, empId);
    else if (a && a.day !== d) setMsg("Un shift ne change pas de jour par glisser-déposer ; modifiez ses horaires.");
  };

  const wk = weekStart(day); const weekDays = days.filter((d) => weekStart(d) === wk);

  return (
    <Page>
      <h1 className="mb-3 text-2xl font-semibold">{t("nav.planning")}</h1>
      <Card actions={<div className="flex flex-wrap gap-2">
        <button className="btn" disabled={!history.current.canUndo} onClick={() => step("undo")}>{t("action.undo")}</button>
        <button className="btn" disabled={!history.current.canRedo} onClick={() => step("redo")}>{t("action.redo")}</button>
        {canEdit && <button className="btn" onClick={async () => { await api(`/periods/${period!.id}/versions`, { method: "POST" }); setMsg("Version enregistrée"); }}>Enregistrer une version</button>}
      </div>}>
        <div className="grid gap-2 md:grid-cols-5">
          <select aria-label="Période" className="input" value={period?.id ?? ""} onChange={(e) => setId(e.target.value)}>{periods.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
          <input aria-label="Recherche" placeholder="Recherche…" className="input" value={text} onChange={(e) => setText(e.target.value)} />
          <select aria-label="Site" className="input" value={site} onChange={(e) => setSite(e.target.value)}><option value="">Tous les sites</option>{sites.map((s) => <option key={s}>{s}</option>)}</select>
          <select aria-label="Marque" className="input" value={brand} onChange={(e) => setBrand(e.target.value)}><option value="">Toutes les marques</option>{brands.map((s) => <option key={s}>{s}</option>)}</select>
          <select aria-label="Collaborateur" className="input" value={empF} onChange={(e) => setEmpF(e.target.value)}><option value="">Tous</option>{emps.data?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select>
        </div>
        <div role="tablist" aria-label="Vues" className="mt-3 flex flex-wrap gap-2">
          {VIEWS.map((v) => <button key={v} role="tab" aria-selected={view === v} className={`btn ${view === v ? "btn-primary" : ""}`} onClick={() => setView(v)}>{t(`view.${v}`)}</button>)}
          {(view === "week" || view === "day") && <select aria-label="Jour" className="input w-auto" value={day} onChange={(e) => setFocusDay(e.target.value)}>{days.map((d) => <option key={d}>{d}</option>)}</select>}
        </div>
        <p role="status" aria-live="polite" className="mt-2 text-sm">{msg}</p>
      </Card>

      {conflicts.length > 0 && <Card title="Conflits immédiats"><ul className="tag-bad list-disc pl-5 text-sm">{conflicts.map((c) => <li key={c}>{c}</li>)}</ul></Card>}
      {!!sched.data?.uncovered.length && <Card title={`Shifts non couverts (${sched.data.uncovered.length})`}><p className="muted text-sm">{sched.data.uncovered.slice(0, 8).map((u) => `${u.day} ${u.site} ${u.start.slice(0, 5)}`).join(" · ")}</p></Card>}

      <Card>
        <div className="overflow-x-auto">
          {view === "month" && (
            <table className="grid" aria-label="Vue mensuelle"><thead><tr>{DOW.map((d) => <th key={d}>{d}</th>)}</tr></thead><tbody>
              {chunkWeeks(days).map((w, i) => <tr key={i}>{w.map((d, j) => <td key={j} className="min-w-28 align-top">{d && <>
                <button className="muted text-xs underline" onClick={() => { setFocusDay(d); setView("day"); }}>{d.slice(8)}</button>
                <div className="space-y-1">{list.filter((a) => a.day === d).slice(0, 3).map(chip)}
                  {list.filter((a) => a.day === d).length > 3 && <span className="muted text-xs">+{list.filter((a) => a.day === d).length - 3}</span>}</div></>}</td>)}</tr>)}
            </tbody></table>)}
          {view === "week" && (
            <table className="grid" aria-label="Vue hebdomadaire"><thead><tr><th>Collaborateur</th>{weekDays.map((d) => <th key={d}>{DOW[weekdayIdx(d)]} {d.slice(8)}</th>)}</tr></thead><tbody>
              {(emps.data ?? []).filter((e) => !empF || e.id === empF).map((e) => <tr key={e.id}><th scope="row" className="text-left">{e.name}</th>
                {weekDays.map((d) => <td key={d} className="min-w-28" onDragOver={(ev) => ev.preventDefault()} onDrop={(ev) => drop(ev, e.id, d)}>
                  {list.filter((a) => a.employee_id === e.id && a.day === d).map(chip)}</td>)}</tr>)}
            </tbody></table>)}
          {view === "day" && (<ul className="space-y-2" aria-label="Vue journalière">{list.filter((a) => a.day === day).map((a) => (
            <li key={a.assignment_id} className="surface flex flex-wrap items-center gap-2 p-2 text-sm">
              <span className="w-28 font-medium">{a.start.slice(0, 5)}–{a.end.slice(0, 5)}</span><span className="w-32">{a.site}</span>
              <span className="muted">{hours(a.presence_minutes)} présence · {hours(a.effective_minutes)} effectives</span>
              <select aria-label={`Collaborateur pour ${a.slot_key}`} className="input ml-auto w-44" value={a.employee_id} disabled={!canEdit || a.locked} onChange={(e) => reassign(a, e.target.value)}>
                {emps.data?.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select>
              <button className="btn" onClick={() => setSel(a)}>Détails</button></li>))}</ul>)}
          {view === "employee" && (<EmployeeView list={list} emps={emps.data ?? []} chip={chip} />)}
          {view === "brand" && (<BrandView list={list} />)}
        </div>
      </Card>

      {sel && (
        <aside role="dialog" aria-label="Détails du shift" className="glass fixed inset-x-3 bottom-3 z-10 mx-auto max-w-xl p-4">
          <h2 className="font-semibold">{sel.employee} — {sel.site}</h2>
          <p className="muted text-sm">{sel.day} · présence {hours(sel.presence_minutes)} · pause {hours(sel.break_minutes)} · effectif {hours(sel.effective_minutes)}</p>
          <p className="text-sm">Imputations : {Object.entries(sel.allocations).map(([k, v]) => `${k} ${hours(v)}`).join(" + ")}</p>
          {canEdit && <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); editTimes(sel, new FormData(e.currentTarget)); }}>
            <label className="text-xs">Début<input name="s" type="time" defaultValue={sel.start.slice(0, 5)} className="input" /></label>
            <label className="text-xs">Fin<input name="e" type="time" defaultValue={sel.end.slice(0, 5)} className="input" /></label>
            <label className="text-xs">Pause (min)<input name="b" type="number" min={0} defaultValue={sel.break_minutes} className="input w-24" /></label>
            <button className="btn btn-primary" disabled={sel.locked}>Modifier l'horaire</button>
            <button type="button" className="btn" onClick={() => toggleLock(sel)}>{sel.locked ? t("action.unlock") : t("action.lock")}</button></form>}
          <button className="btn mt-2" onClick={() => setSel(null)}>Fermer</button>
        </aside>)}
    </Page>
  );
}

function chunkWeeks(days: string[]) {
  if (!days.length) return [];
  const cells: (string | null)[] = Array(weekdayIdx(days[0])).fill(null).concat(days);
  while (cells.length % 7) cells.push(null);
  return Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7));
}

function EmployeeView({ list, emps, chip }: { list: Assignment[]; emps: Emp[]; chip: (a: Assignment) => React.ReactNode }) {
  const [id, setId] = useState("");
  const mine = list.filter((a) => a.employee_id === (id || emps[0]?.id));
  const total = mine.reduce((s, a) => s + a.effective_minutes, 0);
  return <div aria-label="Vue par collaborateur"><select aria-label="Collaborateur" className="input mb-2 w-60" value={id || emps[0]?.id} onChange={(e) => setId(e.target.value)}>{emps.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select>
    <p className="mb-2 text-sm">{mine.length} jours · {hours(total)} effectives (sans contrat renseigné : aucun plafond affiché)</p>
    <div className="grid gap-1 sm:grid-cols-3 lg:grid-cols-5">{mine.map((a) => <div key={a.assignment_id}><span className="muted text-xs">{a.day}</span>{chip(a)}</div>)}</div></div>;
}

function BrandView({ list }: { list: Assignment[] }) {
  const by: Record<string, number> = {}; const sites: Record<string, number> = {};
  list.forEach((a) => { sites[a.site] = (sites[a.site] ?? 0) + 1; Object.entries(a.allocations).forEach(([b, m]) => (by[b] = (by[b] ?? 0) + m)); });
  return <div aria-label="Vue par marque ou site" className="grid gap-3 md:grid-cols-2">
    <table className="grid"><caption className="text-left font-medium">Heures effectives par marque</caption><tbody>{Object.entries(by).map(([b, m]) => <tr key={b}><td>{b}</td><td>{hours(m)}</td></tr>)}</tbody></table>
    <table className="grid"><caption className="text-left font-medium">Shifts par site</caption><tbody>{Object.entries(sites).map(([s, n]) => <tr key={s}><td>{s}</td><td>{n}</td></tr>)}</tbody></table></div>;
}
