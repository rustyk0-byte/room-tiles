import { defineConfig } from "vitest/config";
import { themeData } from "./theme-data.mjs";

export default defineConfig({
  test: {
    environment: "happy-dom",
    include: ["src/**/*.test.ts"],
  },
  define: { THEME_DATA: JSON.stringify(themeData()) },
  esbuild: {
    // Lit's reactive properties need TypeScript's (not the standard) class fields
    tsconfigRaw: { compilerOptions: { useDefineForClassFields: false } },
  },
});
