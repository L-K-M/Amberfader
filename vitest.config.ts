import { defineConfig } from "vitest/config";

// Adapter/search/probe tests run against a music.youtube.com jsdom document so
// location.search and same-origin replaceState behave like the real page;
// everything else runs under node.
export default defineConfig({
  test: {
    projects: [
      {
        test: {
          name: "jsdom",
          environment: "jsdom",
          environmentOptions: {
            jsdom: { url: "https://music.youtube.com/" },
          },
          include: [
            "extension/tests/unit/adapter*.test.ts",
            "extension/tests/unit/search*.test.ts",
            "extension/tests/unit/probe*.test.ts",
            "extension/tests/unit/popup*.test.ts",
          ],
          restoreMocks: true,
        },
      },
      {
        test: {
          name: "node",
          environment: "node",
          include: ["extension/tests/**/*.test.ts"],
          exclude: [
            "extension/tests/unit/adapter*.test.ts",
            "extension/tests/unit/search*.test.ts",
            "extension/tests/unit/probe*.test.ts",
            "extension/tests/unit/popup*.test.ts",
          ],
          restoreMocks: true,
        },
      },
    ],
  },
  esbuild: {
    target: "es2022",
  },
});
