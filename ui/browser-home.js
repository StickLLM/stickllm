/* StickLLM Browser home — stick vs remote; A0 Tor/offline vs workstation DIY. */
(function () {
  "use strict";
  const WEB_LABELS = {
    internet: "Internet",
    tor: "Tor mode",
    none: "No internet",
  };
  const A0_LABELS = {
    internet: "Agent Zero: Internet",
    tor: "Agent Zero: Tor",
    none: "Agent Zero: No internet",
  };
  const host = String(location.hostname || "").toLowerCase();
  const onStickLoopback = host === "127.0.0.1" || host === "localhost" || host === "[::1]";

  const clientPill = document.getElementById("clientPill");
  const clientLabel = document.getElementById("clientLabel");
  const sessionPill = document.getElementById("sessionPill");
  const sessionLabel = document.getElementById("sessionLabel");
  const privacyPill = document.getElementById("privacyPill");
  const privacyLabel = document.getElementById("privacyLabel");
  const pill = document.getElementById("modePill");
  const label = document.getElementById("modeLabel");
  const note = document.getElementById("modeNote");
  const hint = document.getElementById("modeHint");
  const callout = document.getElementById("remoteCallout");
  if (!pill || !label || !note || !sessionPill || !sessionLabel || !privacyPill || !privacyLabel || !clientPill || !clientLabel) return;

  function a0Title(key, j) {
    if (key === "tor" && j && j.tor_ready === false) return "Agent Zero: Tor — starting…";
    if (key === "tor" && j && j.tor_ready) return "Agent Zero: Tor";
    return A0_LABELS[key] || A0_LABELS.internet;
  }

  function stickNote(key, j, stickPrivate) {
    const parts = [];
    if (key === "tor") {
      if (j && j.tor_ready === false) {
        parts.push("Tor is starting on the StickLLM USB Stick.");
      }
      parts.push("Agent Zero and other StickLLM applications use Tor when accessing the internet.");
      if (stickPrivate) {
        parts.push("This Browser window uses Tor and is Incognito — history and cookies are not kept.");
      } else {
        parts.push("This Browser window uses Tor.");
      }
    } else if (key === "none") {
      parts.push("Agent Zero and other StickLLM applications have No internet (public web blocked).");
      if (stickPrivate) {
        parts.push("This Browser window is Incognito — history and cookies are not kept.");
      }
    } else {
      parts.push("Agent Zero and other StickLLM applications use the normal Internet uplink.");
      if (stickPrivate) {
        parts.push("This Browser window is Incognito — history and cookies are not kept.");
      } else {
        parts.push("This Browser window uses normal browsing.");
      }
    }
    return parts.join(" ");
  }

  function paint(j) {
    const mode = (j && j.mode) || "internet";
    const key = WEB_LABELS[mode] ? mode : "internet";
    pill.dataset.mode = key;
    label.textContent = a0Title(key, j);

    const session = (j && j.session_mode) === "vault" ? "vault" : "ephemeral";
    const stickPrivate = (j && typeof j.private_browsing === "boolean")
      ? j.private_browsing
      : session !== "vault";

    sessionPill.dataset.mode = session;
    sessionLabel.textContent = session === "vault" ? "Vault mode" : "Ephemeral mode";

    if (onStickLoopback) {
      clientPill.dataset.mode = "stick";
      clientLabel.textContent = "StickLLM USB Stick";
      privacyPill.dataset.mode = stickPrivate ? "incognito" : "normal";
      privacyLabel.textContent = stickPrivate ? "Incognito" : "Normal browsing";
      if (callout) { callout.dataset.show = "0"; callout.textContent = ""; }
      if (hint) { hint.textContent = ""; hint.hidden = true; }
      note.textContent = stickNote(key, j, stickPrivate);
    } else {
      clientPill.dataset.mode = "remote";
      clientLabel.textContent = "Remote web client";
      privacyPill.dataset.mode = "remote";
      privacyLabel.textContent = "Your workstation browser";

      if (callout) {
        callout.dataset.show = "1";
        callout.innerHTML =
          "<p><strong>This is not the StickLLM USB Stick screen.</strong> " +
          "Tor and Incognito for <em>this tab</em> on your phone or PC do <strong>not</strong> " +
          "come from StickLLM — you must install Tor (for example Tor Browser) and/or turn on " +
          "Incognito / Private mode <strong>yourself</strong> on this workstation.</p>" +
          "<p><strong>On the StickLLM USB Stick,</strong> when Web mode is Tor, " +
          "<strong>Agent Zero and other StickLLM applications</strong> use Tor when accessing " +
          "the internet — even while you control the stick from this remote client.</p>";
      }
      if (hint) {
        hint.hidden = false;
        hint.textContent = "This tab uses your device’s network and history settings. StickLLM apps on the USB Stick follow the stick Web mode.";
      }

      const parts = [];
      if (key === "tor") {
        parts.push(
          j && j.tor_ready === false
            ? "On the StickLLM USB Stick, Agent Zero and other StickLLM apps are starting Tor."
            : "On the StickLLM USB Stick, Agent Zero and other StickLLM applications use Tor when accessing the internet."
        );
      } else if (key === "none") {
        parts.push("On the StickLLM USB Stick, Agent Zero and other StickLLM applications have No internet (public web blocked).");
      } else {
        parts.push("On the StickLLM USB Stick, Agent Zero and other StickLLM applications can use the normal Internet uplink.");
      }
      parts.push(
        session === "vault"
          ? "Stick session: Vault."
          : "Stick session: Ephemeral (stick chats stay off the vault SSD blob)."
      );
      if (stickPrivate) {
        parts.push("StickLLM USB Stick Desktop Browser opens Incognito; this remote tab does not.");
      } else {
        parts.push("StickLLM USB Stick Desktop Browser uses normal browsing; this remote tab uses your browser.");
      }
      note.textContent = parts.join(" ");
    }

    document.title = "StickLLM · " + clientLabel.textContent + " · " +
      sessionLabel.textContent + " · " + label.textContent;
  }

  async function refresh() {
    try {
      const r = await fetch("/api/web-mode", { cache: "no-store" });
      const j = await r.json().catch(() => ({}));
      if (r.ok) paint(j);
      else paint({ mode: "internet", note: "Could not read Web mode (" + r.status + ")." });
    } catch (_) {
      paint({ mode: "internet", note: "StickLLM is unreachable — is the stick UI service up?" });
    }
  }

  refresh();
  setInterval(refresh, 4000);
})();
