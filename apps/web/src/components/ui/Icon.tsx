import type { SVGProps } from "react";

const P: Record<string, string> = {
  dashboard: "M3 3h8v8H3zM13 3h8v5h-8zM13 10h8v11h-8zM3 13h8v8H3z",
  calendar: "M7 3v3M17 3v3M4 8h16M5 5h14a1 1 0 011 1v13a1 1 0 01-1 1H5a1 1 0 01-1-1V6a1 1 0 011-1z",
  wallet: "M3 7a2 2 0 012-2h13v4M3 7v11a2 2 0 002 2h15V9H5a2 2 0 01-2-2zM16 14h2",
  users: "M16 19v-1a4 4 0 00-4-4H7a4 4 0 00-4 4v1M9.5 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM21 19v-1a4 4 0 00-3-3.9M15.5 4.2a3.5 3.5 0 010 6.6",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  sparkles: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
  bell: "M6 9a6 6 0 0112 0c0 6 2 7 2 7H4s2-1 2-7zM10 20a2 2 0 004 0",
  history: "M3 12a9 9 0 109-9 9 9 0 00-7 3.4L3 8M3 3v5h5M12 7v5l3 2",
  swap: "M7 4L3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7",
  lock: "M7 11V8a5 5 0 0110 0v3M6 11h12a1 1 0 011 1v8a1 1 0 01-1 1H6a1 1 0 01-1-1v-8a1 1 0 011-1z",
  alert: "M12 3l10 18H2zM12 10v5M12 18v.5",
  search: "M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.3-4.3",
  sun: "M12 17a5 5 0 100-10 5 5 0 000 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 13A9 9 0 1111 3a7 7 0 0010 10z",
  monitor: "M3 5h18v12H3zM8 21h8M12 17v4",
  undo: "M9 14L4 9l5-5M4 9h10a6 6 0 010 12h-3",
  redo: "M15 14l5-5-5-5M20 9H10a6 6 0 000 12h3",
  check: "M5 12l5 5 9-10",
  x: "M6 6l12 12M18 6L6 18",
  chevL: "M15 6l-6 6 6 6", chevR: "M9 6l6 6-6 6",
  menu: "M4 6h16M4 12h16M4 18h16",
  info: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 11v5M12 8v.5",
  download: "M12 3v12M7 10l5 5 5-5M4 20h16",
  upload: "M12 21V9M7 14l5-5 5 5M4 4h16",
  plus: "M12 5v14M5 12h14",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
  coffee: "M4 8h13v6a5 5 0 01-5 5H9a5 5 0 01-5-5zM17 10h2a2 2 0 010 4h-2M7 2v3M11 2v3",
  logout: "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9",
  grip: "M9 6h.01M9 12h.01M9 18h.01M15 6h.01M15 12h.01M15 18h.01",
  sunrise: "M12 3v4M5 12h2M17 12h2M7 7l1.5 1.5M17 7l-1.5 1.5M4 18h16M8 18a4 4 0 018 0",
  sunset: "M12 7V3M5 12h2M17 12h2M7 7l1.5 1.5M17 7l-1.5 1.5M4 18h16M8 18a4 4 0 018 0M9 21h6",
  briefcase: "M4 8h16a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V9a1 1 0 011-1zM9 8V5a1 1 0 011-1h4a1 1 0 011 1v3",
};

export type IconName = keyof typeof P;

export function Icon({ name, size = 18, ...rest }: { name: IconName; size?: number } & Omit<SVGProps<SVGSVGElement>, "name">) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...rest}>
      <path d={P[name]} />
    </svg>
  );
}
