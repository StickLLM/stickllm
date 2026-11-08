/**
 * Injected into Agent Zero HTML by sticklink_asset_sw.js.
 * Same-origin iframe → parent.__sticklinkMux. WebSocket only (HTTP via SW).
 * Also: Enter-to-send (iOS soft keyboard Return) — A0 mobile often only wires the button.
 */
(function () {
  try {
    if (window.__sticklinkWsBridged) return;
    window.__sticklinkWsBridged = true;
    const mux = window.parent && window.parent.__sticklinkMux;
    if (!mux || typeof mux.openWebSocket !== "function") {
      console.error("[sticklink] a0_ws_bridge: no parent mux");
      return;
    }
    const OrigWS = window.WebSocket;
    function tunnel(url) {
      try {
        const u = new URL(String(url), location.href);
        const p = u.pathname || "";
        return (
          p.startsWith("/agent-zero") ||
          p.startsWith("/socket.io") ||
          p.indexOf("socket.io") >= 0
        );
      } catch (_) {
        return /socket\.io/i.test(String(url));
      }
    }
    window.WebSocket = function StickLinkWS(url, protocols) {
      if (!tunnel(url)) return new OrigWS(url, protocols);
      return mux.openWebSocket(String(url), protocols);
    };
    window.WebSocket.CONNECTING = 0;
    window.WebSocket.OPEN = 1;
    window.WebSocket.CLOSING = 2;
    window.WebSocket.CLOSED = 3;
    window.WebSocket.prototype = OrigWS.prototype;
  } catch (e) {
    console.error("[sticklink] a0_ws_bridge failed", e);
  }

  function sendNow() {
    try {
      const s = window.Alpine && Alpine.store && Alpine.store("chatInput");
      if (s && typeof s.activateSendButton === "function") {
        s.activateSendButton();
        return true;
      }
      if (s && typeof s.sendMessage === "function") {
        s.sendMessage();
        return true;
      }
      if (typeof window.sendMessage === "function") {
        window.sendMessage();
        return true;
      }
      const b = document.getElementById("send-button");
      if (b) {
        b.click();
        return true;
      }
    } catch (_) {}
    return false;
  }

  function onEnter(e) {
    if (e.key !== "Enter" && e.keyCode !== 13) return;
    if (e.shiftKey || e.isComposing || e.keyCode === 229) return;
    const t = e.target;
    if (!t || !t.closest) return;
    if (!t.closest("#chat-input, #chat-input-container, .chat-input, [data-chat-input]")) return;
    e.preventDefault();
    e.stopPropagation();
    sendNow();
  }
  document.addEventListener("keydown", onEnter, true);
  document.addEventListener("keypress", onEnter, true);
})();
