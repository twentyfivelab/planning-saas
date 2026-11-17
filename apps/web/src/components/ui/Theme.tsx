"use client";
import { useEffect, useState } from "react";
import { Button } from "./primitives";

/** Thème clair rose et blanc : identité par défaut, quel que soit le réglage du système. Le mode sombre (rose profond) n'est appliqué
 *  que sur choix explicite de l'utilisateur. Un ancien réglage « automatique » est ramené au thème clair. */
type Pref = "light" | "dark";
const LABEL: Record<Pref, string> = { light: "Thème : clair", dark: "Thème : sombre" };

export function resolveTheme(pref: string | null | undefined): Pref { return pref === "dark" ? "dark" : "light"; }

export function applyTheme(pref: Pref) {
  document.documentElement.dataset.theme = resolveTheme(pref);
}

export function ThemeToggle() {
  const [pref, setPref] = useState<Pref>("light");
  useEffect(() => { try { setPref(resolveTheme(localStorage.getItem("theme-pref"))); } catch { /* stockage indisponible : thème clair */ } }, []);
  const next = () => {
    const n: Pref = pref === "light" ? "dark" : "light";
    setPref(n); try { localStorage.setItem("theme-pref", n); } catch { /* préférence non mémorisée */ }
    applyTheme(n);
  };
  return <Button onClick={next} icon={pref === "dark" ? "moon" : "sun"} aria-label={`${LABEL[pref]} (cliquer pour changer)`}>{LABEL[pref]}</Button>;
}
