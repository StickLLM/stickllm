// Copyright (c) 2026 Nink Inc. All rights reserved.

// Package admit is the relay-side half of sticklink relay admission.
//
// derper (-verify-client-url) asks us "may this node key use the relay?". We
// answer from a local copy of the signed allowlist published by the sticklink
// signalling Worker (GET /v1/relay/allowlist). The copy is kept current by:
//
//   - a delta pull every 60 s and a full pull every hour,
//   - an immediate pull when the Worker's change feed pushes {"t":"chg"},
//   - one single-flight pull (at most one per 2 s) when an unknown key asks.
//
// Every document must carry a valid Ed25519 signature by a pinned key
// (domain "sl1/allowlist/v1"). We fail closed: if no document has been
// verified within its TTL (15 min), every key is denied.
package admit
