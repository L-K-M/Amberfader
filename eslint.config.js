import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "build/**",
      "node_modules/**",
      "coverage/**",
      "native/**",
      "packaging/**",
      "scripts/*.sh",
      ".venv/**",
      "eslint.config.js",
      "extension/src/protocol/validators.gen.js",
      "extension/src/protocol/validators.gen.d.ts",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    files: ["**/*.ts", "**/*.mts"],
    languageOptions: {
      parserOptions: {
        projectService: {
          allowDefaultProject: ["*.js", "*.mjs", "scripts/*.mjs"],
        },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // The TS compiler resolves identifiers; no-undef only produces false
      // positives on WebExtension and DOM globals.
      "no-undef": "off",
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      "@typescript-eslint/no-confusing-void-expression": "off",
      "no-console": ["warn", { allow: ["error", "warn"] }],
    },
  },
  {
    files: ["**/*.mjs", "**/*.js"],
    ...tseslint.configs.disableTypeChecked,
    languageOptions: {
      globals: {
        process: "readonly",
        console: "readonly",
        Buffer: "readonly",
        URL: "readonly",
        fetch: "readonly",
        Response: "readonly",
        AbortSignal: "readonly",
        AbortController: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        ReadableStream: "readonly",
      },
    },
    rules: {
      ...tseslint.configs.disableTypeChecked.rules,
      "no-console": "off",
    },
  },
  {
    files: ["extension/tests/**/*.ts"],
    rules: {
      "@typescript-eslint/no-non-null-assertion": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/unbound-method": "off",
      // Fakes implement async interfaces synchronously on purpose.
      "@typescript-eslint/require-await": "off",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
);
