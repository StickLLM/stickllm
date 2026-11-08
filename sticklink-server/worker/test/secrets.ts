// Copyright (c) 2026 Nink Inc. All rights reserved.
// TEST-ONLY secrets (public test values). Never use outside tests / local dev.
export const TEST_SIGNING_SEED = "nWGxne_9WmC6hEr0kuwsxERJxWl7MmkZcDusAxyuf2A"; // RFC 8032 test 1
export const TEST_RELAY_TOKEN = "test-relay-token-tor1-0123456789";
export const TEST_RELAY_TOKEN_SHA256 = "a0a2aeb2b1e0220c6c958b242b6888f179fd6cd231045fc0891f18e9be09b36f";

export const TEST_SECRETS = {
  IP_PEPPER: "test-pepper",
  SIGNING_KEY: TEST_SIGNING_SEED,
  SIGNING_KID: "test-1",
  RELAY_TOKENS: JSON.stringify({ tor1: TEST_RELAY_TOKEN_SHA256 }),
};
