import { FlatCompat } from "@eslint/eslintrc";
const compat = new FlatCompat({ baseDirectory: import.meta.dirname });
const config = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  { ignores: [".next/**", "e2e/**", "next-env.d.ts", "node_modules/**"] },
  // textes français avec apostrophes ; any toléré aux frontières JSON de l'API
  { rules: { "@typescript-eslint/no-explicit-any": "off", "react/no-unescaped-entities": "off" } },
];
export default config;
