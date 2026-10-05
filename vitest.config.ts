import { defineConfig } from "vitest/config";

// Adapter and search tests run against a music.youtube.com jsdom document so
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
            "web/tests/unit/adapter*.test.ts",
            "web/tests/unit/search*.test.ts",
          ],
          restoreMocks: true,
        },
      },
      {
        test: {
          name: "node",
          environment: "node",
          include: ["web/tests/**/*.test.ts"],
          exclude: [
            "web/tests/unit/adapter*.test.ts",
            "web/tests/unit/search*.test.ts",
          ],
          restoreMocks: true,
        },
      },
    ],
  },
  oxc: {
    target: "es2022",
  },
});
