/**
 * StickLink Method C transport performance sink.
 * Aggregates mux/SW/DC timings for cold vs warm A0 loads.
 */
(function (global) {
  const g = global;
  if (g.__sticklinkPerf) return;

  const t0 = performance.now();
  const state = {
    t0,
    marks: {},
    http: [], // {id,method,path,queuedAt,startAt,ttfbMs,doneMs,status,bytes,chunks,waitedMs,inflightAtStart}
    sw: [], // {path, swStart, hostReplyMs, totalMs, status, bytes}
    dc: [], // {t, bufferedAmount, inflightHttp}
    totals: {
      httpCount: 0,
      httpBytes: 0,
      httpWireEst: 0, // body * 4/3 for b64
      maxInflight: 0,
      maxBuffered: 0,
      compressClaims: 0, // responses claiming content-encoding
    },
    render: {
      htmlFirstByteMs: null,
      htmlDoneMs: null,
      iframeNavMs: null,
      chatInputVisibleMs: null,
      alpineReadyMs: null,
    },
  };

  function now() {
    return performance.now();
  }

  function mark(name) {
    state.marks[name] = now() - state.t0;
  }

  function sampleDc(dc, inflight) {
    let ba = 0;
    try {
      ba = dc && typeof dc.bufferedAmount === "number" ? dc.bufferedAmount : 0;
    } catch (_) {}
    state.dc.push({ t: now() - t0, bufferedAmount: ba, inflightHttp: inflight || 0 });
    if (ba > state.totals.maxBuffered) state.totals.maxBuffered = ba;
  }

  function onHttpStart(meta) {
    state.totals.httpCount++;
    if (meta.inflightAtStart > state.totals.maxInflight) {
      state.totals.maxInflight = meta.inflightAtStart;
    }
    state.http.push(meta);
    return meta;
  }

  function onHttpDone(id, patch) {
    const row = state.http.find((h) => h.id === id);
    if (!row) return;
    Object.assign(row, patch);
    if (patch.bytes) {
      state.totals.httpBytes += patch.bytes;
      state.totals.httpWireEst += Math.ceil(patch.bytes * 4 / 3);
    }
    if (patch.contentEncoding) state.totals.compressClaims++;
  }

  function onSw(entry) {
    state.sw.push(entry);
  }

  function summary() {
    const done = state.http.filter((h) => h.doneMs != null);
    const durations = done.map((h) => h.doneMs - h.startAt);
    durations.sort((a, b) => a - b);
    const pct = (p) =>
      durations.length
        ? durations[Math.min(durations.length - 1, Math.floor((p / 100) * durations.length))]
        : null;
    const overlapping = estimateOverlap(done);
    return {
      elapsedMs: now() - t0,
      marks: { ...state.marks },
      render: { ...state.render },
      http: {
        count: state.totals.httpCount,
        completed: done.length,
        bytes: state.totals.httpBytes,
        wireEstB64: state.totals.httpWireEst,
        maxInflight: state.totals.maxInflight,
        compressClaims: state.totals.compressClaims,
        p50Ms: pct(50),
        p95Ms: pct(95),
        maxMs: durations.length ? durations[durations.length - 1] : null,
        avgMs: durations.length
          ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length)
          : null,
        overlapRatio: overlapping.ratio,
        sequentialHint: overlapping.ratio < 1.3,
        topSlow: [...done]
          .sort((a, b) => b.doneMs - b.startAt - (a.doneMs - a.startAt))
          .slice(0, 12)
          .map((h) => ({
            path: h.path,
            ms: Math.round(h.doneMs - h.startAt),
            ttfbMs: h.ttfbMs != null ? Math.round(h.ttfbMs - h.startAt) : null,
            bytes: h.bytes,
            waitedMs: h.waitedMs || 0,
          })),
      },
      sw: {
        count: state.sw.length,
        avgHostHopMs: state.sw.length
          ? Math.round(
              state.sw.reduce((a, s) => a + (s.hostReplyMs || 0), 0) / state.sw.length,
            )
          : null,
      },
      dc: {
        samples: state.dc.length,
        maxBuffered: state.totals.maxBuffered,
        lastBuffered: state.dc.length ? state.dc[state.dc.length - 1].bufferedAmount : 0,
      },
    };
  }

  /** Rough concurrency: sum(dur)/span — 1.0 ≈ fully sequential. */
  function estimateOverlap(done) {
    if (!done.length) return { ratio: 0, span: 0, busy: 0 };
    const start = Math.min(...done.map((h) => h.startAt));
    const end = Math.max(...done.map((h) => h.doneMs));
    const span = end - start || 1;
    const busy = done.reduce((a, h) => a + (h.doneMs - h.startAt), 0);
    return { ratio: busy / span, span, busy };
  }

  function dumpJson() {
    return JSON.stringify(
      {
        summary: summary(),
        http: state.http,
        sw: state.sw.slice(-200),
        dc: state.dc.slice(-200),
      },
      null,
      2,
    );
  }

  g.__sticklinkPerf = {
    state,
    mark,
    sampleDc,
    onHttpStart,
    onHttpDone,
    onSw,
    summary,
    dumpJson,
    now,
    resetBase() {
      state.t0 = now();
      state.http.length = 0;
      state.sw.length = 0;
      state.dc.length = 0;
      state.marks = {};
      state.totals.httpCount = 0;
      state.totals.httpBytes = 0;
      state.totals.httpWireEst = 0;
      state.totals.maxInflight = 0;
      state.totals.maxBuffered = 0;
      state.totals.compressClaims = 0;
      state.render = {
        htmlFirstByteMs: null,
        htmlDoneMs: null,
        iframeNavMs: null,
        chatInputVisibleMs: null,
        alpineReadyMs: null,
      };
    },
  };
})(typeof window !== "undefined" ? window : self);
