// Copyright (c) 2026 Nink Inc. All rights reserved.
import { applyD1Migrations, env } from "cloudflare:test";
const e = env as any;
await applyD1Migrations(e.DB, e.TEST_MIGRATIONS);
