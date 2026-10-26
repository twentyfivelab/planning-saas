"use client";
import { useEffect, useState } from "react";
import { Button } from "./primitives";

type Pref = "system" | "light" | "dark";
const ORDER: Pref[] = ["system", "light", "dark"];
const LABEL: Record<Pref, string> = { system: "Thème : automatique", light: "Thème : clair", dark: "Thème : sombre" };

export function resolveTheme(pref: Pref, systemDark: boolean): "light" | "dark" { return pref === "system" ? (systemDark ? "dark" : "light") : pref; }

export function applyTheme(pref: Pref) {
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = resolveTheme(pref, dark);
}

export function ThemeToggle() {
  const [pref, setPref] = useState<Pref>("system");
  useEffect(() => {
    const read = (): Pref => { try { const s = localStorage.getItem("theme-pref"); if (s === "light" || s === "dark" || s === "system") return s; } catch {} return "system"; };
    setPref(read());
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => { if (read() === "system") applyTheme("system"); };
    mq.addEventListener("change", on); return () => mq.removeEventListener("change", on);
  }, []);
  const next = () => {
    const n = ORDER[(ORDER.indexOf(pref) + 1) % ORDER.length];
    setPref(n); try { localStorage.setItem("theme-pref", n); } catch {}
    applyTheme(n);
  };
  return <Button onClick={next} icon={pref === "dark" ? "moon" : pref === "light" ? "sun" : "monitor"} aria-label={`${LABEL[pref]} (cliquer pour changer)`}>{LABEL[pref]}</Button>;
}
