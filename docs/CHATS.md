# Chats (0.6.0): one chat list for StickLLM and Agent Zero

The StickLLM chat is the simple view and the Agent Zero window is the advanced
view of the same chats. Code: `overlay/usr/local/lib/stickllm_chats.py`.

## Stores

Chats live only in an encrypted store. Both open with the vault passcode.

| Store | Path | Where |
|-------|------|-------|
| `ssd` | `<vault>/chats` | LUKS vault blob, usually on the host SSD |
| `usb` | `/mnt/stickllm-settings/chats` | LUKS settings partition on the stick |

Settings > Chats picks the active store. StickLLM chat APIs stay RAM/browser-only
in Ephemeral mode. Switching Ephemeral/Vault changes where chats are read and
written: it does **not** lock the vault or stop the model / other add-ons, but it
**does** try-restart Agent Zero so its chats bind remounts (see below).

## Layout of a store

```text
chats/
  <id>.json                      StickLLM chat (title, messages, updated)
  agent-zero/<ctxid>/chat.json   Agent Zero chat (A0's own format)
  agent-zero/stickllm-<id>/...   StickLLM chat exported for Agent Zero
  .deleted/<id>                  tombstones (carry deletions across a sync)
```

## How the two views share

- **Agent Zero chats follow session mode.** `stickllm-agent` bind-mounts
  `stickllm_chats.py a0-chats-dir` onto `/a0/usr/chats`:
  - **Vault mode:** `<active store>/agent-zero` (encrypted; persists).
  - **Ephemeral mode:** `/run/stickllm/a0-chats` (host tmpfs/RAM; reboot clears;
    never `<vault>/chats/agent-zero`).
  Mode switch (or chat-store change) `systemctl try-restart`s Agent Zero so the
  bind remounts. Lock vault still stops A0 cleanly. Chats that 0.5.x Agent Zero
  kept in its private state folder migrate into the vault store only (not into
  ephemeral RAM).
- **StickLLM lists both kinds.** The gateway lists `<id>.json` and
  `agent-zero/<ctxid>/chat.json`; an Agent Zero chat opens read-through in the
  chat app.
- **StickLLM chats show in Agent Zero.** Each saved StickLLM chat is also
  written as `agent-zero/stickllm-<id>/chat.json` in Agent Zero's format.
- **Newest wins.** When Agent Zero continued an exported chat (its file is
  newer), the new turns are read back into the StickLLM chat.
- **Atomic writes.** Every chat file is written to a temp file and renamed.
  An unreadable file is reported in the list, never silently dropped.

## Optional sync between stores

With sync on, chats are copied both ways between `ssd` and `usb`: newest file
wins and tombstones carry deletions. Both stores must be open.

## Privacy

Chat text and passcodes are never logged. Agent Zero's chats are only as
private as the store: they never leave the encrypted folder.

## Not verified on hardware

Agent Zero restarting while the store or session mode switches (it is
try-restarted with the new bind mount), and a vault locked while Agent Zero
writes, are covered by unit tests only.
