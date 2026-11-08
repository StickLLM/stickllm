# Read-only relay inventory checklist

**Status 2026-11-07 18:28–18:29 EST:** Sticklink completed live inventory.  
Results recorded in `RELAY-INVENTORY-20261107-LIVE.md`. SSH access resolved on
Sticklink’s side — **no private-key transfer to this agent PC required.**

Historical note (pre-inventory): this agent PC may still lack
`~\.ssh\sticklink_relay`; that is no longer blocking.

## Key location (corrected)

Recorded location of the existing ed25519 private key:

- **Sticklink’s assistant computer:** `~/.ssh/sticklink_relay`

It is **not** assumed to live on the offline LAN build box. Secure transfer onto
**this** agent machine still needs arranging by an operator. This checklist does
**not** claim the key has been transferred.

Do **not** paste the key into chat or commit it. After copy:

```powershell
# operator-only, values never into chat
icacls $HOME\.ssh\sticklink_relay /inheritance:r /grant:r "$env:USERNAME:(R)"
```

## Policy until separate cutover approval

- Keep relay admission **deny-all** (whatever unit currently enforces that).
- Do **not** install or enable `sticklink-admit` / change derper verify URL.
- Docs that name `derp-admit` / recovery “~1 minute” are **unverified** until
  this inventory runs against the live host.

## Read-only commands (after key is present locally)

Target: `debian@relay-tor1.stickllm.com` with `-i $HOME\.ssh\sticklink_relay -o IdentitiesOnly=yes`.

```bash
hostname; date -u; uname -a
systemctl list-units --type=service --all '*derp*' '*sticklink*' '*admit*'
systemctl list-unit-files '*derp*' '*sticklink*' '*admit*'
# For each discovered unit (do not assume names):
#   systemctl status <unit> --no-pager
#   systemctl cat <unit>
#   systemctl show <unit> -p FragmentPath -p DropInPaths -p Wants -p After -p Requires
ss -lntp | grep -E ':443|:3478|:9099|:80|:22' || true
curl -sS -o /dev/null -w 'https_root %{http_code}\n' https://127.0.0.1/
curl -sS -m 3 http://127.0.0.1:9099/healthz || echo 'admit_healthz unreachable'
# Read-only file peeks if permitted (no edits):
sudo sed -n '1,80p' /etc/default/derper 2>/dev/null || true
sudo sed -n '1,120p' /etc/systemd/system/derper.service 2>/dev/null || true
```

Capture into `docs/sticklink/RELAY-INVENTORY-<YYYYMMDD>.md`:

1. Exact admit service unit name(s) and binary/script path  
2. Exact derper `Wants=` / `After=` / verify URL  
3. Whether healthz is deny-all stub vs other  
4. Rollback procedure **as observed** (enable previous unit, restore derper deps, restart derper)  
5. Measured wall-clock for a dry-run restart **only if separately approved** — otherwise leave timing **unmeasured**

## Before requesting deployment approval

Report must include: this inventory’s actual configuration + rollback text, E2E
results, **estimate** recurring cost (currency + usage limits unverified until
billing/dashboard confirm), and secret **names** only. Deployment and spending
remain pending until explicit approval.
