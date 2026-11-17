import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Planning — planification automatique", description: "Planification multi-tenant sous contraintes" };
export const viewport: Viewport = { width: "device-width", initialScale: 1, colorScheme: "light dark" };

// Thème posé avant hydratation (pas de flash) : préférence enregistrée, sinon réglage du système.
const THEME_SCRIPT = `(function(){try{document.documentElement.dataset.theme=localStorage.getItem('theme-pref')==='dark'?'dark':'light'}catch(e){document.documentElement.dataset.theme='light'}})()`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} /></head>
      <body>{children}</body>
    </html>
  );
}
