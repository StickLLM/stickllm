// Copyright (c) 2026 Nink Inc. All rights reserved.
import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";
import { TEST_SECRETS } from "./test/secrets.ts";

export default defineConfig(async () => {
  const migrations = await readD1Migrations("./migrations");
  const project = (name: string, include: string[], flag: string) => ({
    plugins: [
      cloudflareTest({
        wrangler: { configPath: "./wrangler.toml" },
        miniflare: { bindings: { ...TEST_SECRETS, FEATURE_SPAKE2_CODE: flag, TEST_MIGRATIONS: migrations } },
      }),
    ],
    test: { name, include, setupFiles: ["./test/apply-migrations.ts"], testTimeout: 30_000 },
  });
  return {
    test: {
      projects: [
        project("worker", ["test/unit/**/*.test.ts", "test/worker/**/*.test.ts"], "1"),
        project("flag-default", ["test/flagoff/**/*.test.ts"], "0"),
      ],
    },
  };
});
