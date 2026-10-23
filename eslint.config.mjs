// Lints the browser runtime (src/rational/static/*.js). Run: npx eslint@9
import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["src/rational/static/**/*.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "script", globals: globals.browser },
    rules: { eqeqeq: "error", "no-var": "error", "prefer-const": "error" },
  },
];
