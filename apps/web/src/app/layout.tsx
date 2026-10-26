import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Planning — planification automatique", description: "Planification multi-tenant sous contraintes" };
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="fr"><body>{children}</body></html>;
}
