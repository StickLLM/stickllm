// Copyright (c) 2026 Nink Inc. All rights reserved.
// One FeedDO per relay region. sticklink-admit holds a hibernatable WebSocket
// here; on any permit change we push {"t":"chg","seq":N} so the sidecar pulls
// at once (pull-on-change). Idle sockets cost nothing: pings are auto-answered.
import { DurableObject } from "cloudflare:workers";
import type { Env } from "./config";

export class FeedDO extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('{"t":"ping"}', '{"t":"pong"}'));
  }

  async fetch(req: Request): Promise<Response> {
    const seq = Number(new URL(req.url).searchParams.get("seq") ?? 0);
    const pair = new WebSocketPair();
    this.ctx.acceptWebSocket(pair[1]);
    pair[1].send(JSON.stringify({ t: "chg", seq }));
    return new Response(null, { status: 101, webSocket: pair[0] });
  }

  async notify(seq: number): Promise<void> {
    const msg = JSON.stringify({ t: "chg", seq });
    for (const ws of this.ctx.getWebSockets()) {
      try {
        ws.send(msg);
      } catch {
        /* closed */
      }
    }
  }

  subscribers(): number {
    return this.ctx.getWebSockets().length;
  }

  async webSocketMessage(): Promise<void> {
    /* sidecar sends nothing but auto-answered pings */
  }
  async webSocketClose(ws: WebSocket, code: number): Promise<void> {
    try {
      ws.close(code === 1005 ? 1000 : code, "bye");
    } catch {
      /* already closed */
    }
  }
}
