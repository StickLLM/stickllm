# StickLLM Issues Log

Lightweight product/bug log (same spirit as [FEATURES.md](FEATURES.md)). Not a GitHub Issues mirror.

**How to add an entry**
1. Pick the next `ISS-NNN` ID.
2. Put new open items at the top of **Open**.
3. Fill: ID, date, mode (Local / Term / Server / all), status, summary, notes/repro.
4. When fixed, move to **Closed** (or set status Closed) with a one-line resolution.

---

## Open

### ISS-012 — stickllm-kiosk usermod + world-writable /run/stickllm
| | |
|---|---|
| **ID** | ISS-012 |
| **Mode** | Local |
| **Severity** | MEDIUM |
| **Status** | Open (deferred in v0.3 — avoid breaking Local) |
| **Summary** | `stickllm-kiosk` runs **usermod** at runtime and does `chmod 777 /run/stickllm` plus **666** on logs; pair files live there. |

### ISS-013 — Chromium launched with --no-sandbox
| | |
|---|---|
| **ID** | ISS-013 |
| **Mode** | Local |
| **Severity** | MEDIUM |
| **Status** | Open (deferred in v0.3 — avoid breaking Local) |
| **Summary** | Chromium is launched with `--no-sandbox`. |

### ISS-014 — Hardcoded DRM/NVIDIA/threads/model/runtime/serial paths
| | |
|---|---|
| **ID** | ISS-014 |
| **Severity** | LOW |
| **Status** | Open (partial: threads/CPU in v0.3; DRM auto-pick deferred) |
| **Summary** | Hardcoded `/dev/dri/card0`, device indices, runtime paths. |

### ISS-015 — Build hook || true, chmod gaps, services, MOTD, hosts
| | |
|---|---|
| **ID** | ISS-015 |
| **Severity** | LOW |
| **Status** | Open (partial in v0.3 hook; fail-hard cleanup deferred) |
| **Summary** | Hook soft-fails; MOTD/hosts/chmod completeness. |

### ISS-017 — Delete patch-iso scripts and weston/cog/pixman fallbacks
| | |
|---|---|
| **ID** | ISS-017 |
| **Mode** | Local |
| **Severity** | CLEANUP |
| **Status** | Open (deferred until ISS-010 HW-proven) |
| **Summary** | Delete patch-iso / weston/cog/pixman fallbacks after kiosk reproducibility is solid. |

---

## Closed (v0.3.0)

### ISS-019 — GRUB theme selected entry invisible
| **Status** | Closed (v0.3) |
| **Resolution** | Removed empty `selected_item_pixmap_style`; set visible `selected_item_color = #7dffb3`. |

### ISS-018 — CPU fallback broken (no NVIDIA)
| **Status** | Closed (v0.3) |
| **Resolution** | Ship `llama-server-cpu`; `stickllm-llama-start` picks CUDA vs `-ngl 0`; no hard `/dev/nvidia*` unit deps; Running only after `/health`; RAM fits on CPU; gateway friendly errors. |

### ISS-011 — download-model sha256 only warned
| **Status** | Closed (v0.3) |
| **Resolution** | Missing/mismatched sha256 fatal; verify `.partial` before `mv`. |

### ISS-010 — Build cannot reproduce the working kiosk
| **Status** | Closed (v0.3) |
| **Resolution** | `docker-build-live.sh` copies `stickllm.list.chroot` (cage/chromium/seatd/libinput); kiosk script/unit in overlay + hook enable. |

### ISS-009 — Gateway pairing / token weaknesses
| **Status** | Closed (v0.3) |
| **Resolution** | Rate limit + code expiry; `hmac.compare_digest`; no plaintext pending token; CSP headers. |

### ISS-008 — sudoers NOPASSWD overly broad
| **Status** | Closed (v0.3) |
| **Resolution** | Narrow command list; remove sudo-group membership for `stickllm`/`user`. |

### ISS-007 — Hardcoded stickllm password + SSH password login
| **Status** | Closed (v0.3) |
| **Resolution** | Random per-boot SSH password via `stickllm-ssh-bootstrap`; shown on Term console. |

### ISS-006 — llama binds 0.0.0.0:8080 as root
| **Status** | Closed (v0.3) |
| **Resolution** | Bind `127.0.0.1` only; run as `stickllm-llama` (+ root ExecStartPre for modprobe). |

### ISS-005 — Server console download ETA stuck
| **Status** | Closed (v0.3) |
| **Resolution** | Stable ETA phase key + bytes-based ETA from `download-progress.json`. |

### ISS-003 — “API Key” naming confusing
| **Status** | Closed (v0.3) |
| **Resolution** | Removed API key copy/console hints (aligned with ISS-004). |

### ISS-002 — Server console refresh too aggressive
| **Status** | Closed (v0.3) |
| **Resolution** | bootstatus poll/repaint ~10s. |

### ISS-001 — Web lookup broken on Local
| **Status** | Closed (v0.3) |
| **Resolution** | Local `ensure_network`; WiFi UI → NM profile on DATA; status `online` bit; Web needs uplink. |

### ISS-016 — Conflicting nvidia-drm modprobe confs
| **Status** | Closed (v0.3) |
| **Resolution** | Keep `stickllm-nvidia-drm.conf` only (v0.2 behavior); remove duplicate. |

### ISS-004 — Decide whether to keep/expose LAN OpenAI API
| **Status** | Closed (v0.3) |
| **Resolution** | External `/v1/chat/completions` returns 410 without StickLLM UI client header; UI uses `/api/chat`. |
