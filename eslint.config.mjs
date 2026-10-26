// Lints the browser runtime (src/rational/static/*.js). Self-contained on purpose: no plugins, no
// shared configs, nothing to install. Run with: npx --yes eslint@10.12.0 src/rational/static

// ESLint 10's "recommended" rules, listed so the config needs no package.
const recommended = [
  "constructor-super", "for-direction", "getter-return", "no-async-promise-executor", "no-case-declarations",
  "no-class-assign", "no-compare-neg-zero", "no-cond-assign", "no-const-assign", "no-constant-binary-expression",
  "no-constant-condition", "no-control-regex", "no-debugger", "no-delete-var", "no-dupe-args",
  "no-dupe-class-members", "no-dupe-else-if", "no-dupe-keys", "no-duplicate-case", "no-empty",
  "no-empty-character-class", "no-empty-pattern", "no-empty-static-block", "no-ex-assign",
  "no-extra-boolean-cast", "no-fallthrough", "no-func-assign", "no-global-assign", "no-import-assign",
  "no-invalid-regexp", "no-irregular-whitespace", "no-loss-of-precision", "no-misleading-character-class",
  "no-new-native-nonconstructor", "no-nonoctal-decimal-escape", "no-obj-calls", "no-octal",
  "no-prototype-builtins", "no-redeclare", "no-regex-spaces", "no-self-assign", "no-setter-return",
  "no-shadow-restricted-names", "no-sparse-arrays", "no-this-before-super", "no-unassigned-vars", "no-undef",
  "no-unexpected-multiline", "no-unreachable", "no-unsafe-finally", "no-unsafe-negation",
  "no-unsafe-optional-chaining", "no-unused-labels", "no-unused-private-class-members", "no-unused-vars",
  "no-useless-assignment", "no-useless-backreference", "no-useless-catch", "no-useless-escape", "no-with",
  "preserve-caught-error", "require-yield", "use-isnan", "valid-typeof",
];

// The browser APIs the runtime uses; anything else is reported by no-undef.
const browser = [
  "AbortController", "CSS", "CustomEvent", "DOMParser", "Element", "Event", "EventSource", "FormData",
  "HTMLInputElement", "HTMLOptionElement", "HTMLSelectElement", "HTMLTextAreaElement", "URL", "URLSearchParams",
  "WebSocket", "clearTimeout", "console", "document", "fetch", "history", "location", "matchMedia", "navigator",
  "queueMicrotask", "setTimeout", "window",
];

export default [
  {
    files: ["src/rational/static/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: Object.fromEntries(browser.map((name) => [name, "readonly"])),
    },
    rules: {
      ...Object.fromEntries(recommended.map((rule) => [rule, "error"])),
      eqeqeq: "error",
      "no-var": "error",
      "prefer-const": "error",
    },
  },
];
