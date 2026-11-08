// Copyright (c) 2026 Nink Inc. All rights reserved.
package admit

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/coder/websocket"
)

// Syncer keeps a Store current from the Worker.
type Syncer struct {
	Base   string // e.g. https://link.stickllm.com
	Region string
	Token  string // bearer token (never logged)
	Keys   Keys
	Store  *Store
	HTTP   *http.Client
	Now    func() time.Time

	DeltaEvery  time.Duration // 60 s
	FullEvery   time.Duration // 1 h
	UnknownGap  time.Duration // 2 s between unknown-key pulls
	FeedBackoff time.Duration // initial feed reconnect delay

	pullMu      sync.Mutex // single flight
	lastUnknown atomic.Int64
	C           Counters
}

// Counters are the only thing we log.
type Counters struct {
	Allow, Deny, Pulls, PullErrs, Rejected, FeedChg, UnknownPulls atomic.Int64
}

func (s *Syncer) defaults() {
	if s.HTTP == nil {
		s.HTTP = &http.Client{Timeout: 10 * time.Second}
	}
	if s.Now == nil {
		s.Now = time.Now
	}
	if s.DeltaEvery == 0 {
		s.DeltaEvery = 60 * time.Second
	}
	if s.FullEvery == 0 {
		s.FullEvery = time.Hour
	}
	if s.UnknownGap == 0 {
		s.UnknownGap = 2 * time.Second
	}
	if s.FeedBackoff == 0 {
		s.FeedBackoff = time.Second
	}
}

// Pull fetches and applies one document. full forces since=0. A delta that
// does not chain is retried once as a full pull. Concurrent callers share one
// in-flight request.
func (s *Syncer) Pull(ctx context.Context, full bool) error {
	s.defaults()
	s.pullMu.Lock()
	defer s.pullMu.Unlock()
	err := s.pullLocked(ctx, full)
	if errors.Is(err, ErrNotChain) {
		err = s.pullLocked(ctx, true)
	}
	return err
}

func (s *Syncer) pullLocked(ctx context.Context, full bool) error {
	s.C.Pulls.Add(1)
	since := int64(0)
	if !full {
		since = s.Store.Seq()
	}
	u := fmt.Sprintf("%s/v1/relay/allowlist?rg=%s&since=%d", s.Base, url.QueryEscape(s.Region), since)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+s.Token)
	resp, err := s.HTTP.Do(req)
	if err != nil {
		s.C.PullErrs.Add(1)
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		s.C.PullErrs.Add(1)
		return fmt.Errorf("allowlist: HTTP %d", resp.StatusCode)
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 16<<20))
	if err != nil {
		s.C.PullErrs.Add(1)
		return err
	}
	d, err := s.Keys.Verify(raw)
	if err != nil {
		s.C.Rejected.Add(1)
		return err
	}
	if err := s.Store.Apply(d); err != nil {
		if !errors.Is(err, ErrNotChain) {
			s.C.Rejected.Add(1)
		}
		return err
	}
	return nil
}

// Admit answers derper. An unknown key while fresh triggers one rate-limited
// single-flight pull before the final answer (a just-registered key gets in).
func (s *Syncer) Admit(ctx context.Context, nk string) bool {
	s.defaults()
	if !NodeKeyRE.MatchString(nk) {
		s.C.Deny.Add(1)
		return false
	}
	d := s.Store.Check(nk)
	if d == DenyUnknown || d == DenyStale {
		now := s.Now().UnixNano()
		last := s.lastUnknown.Load()
		if now-last >= int64(s.UnknownGap) && s.lastUnknown.CompareAndSwap(last, now) {
			s.C.UnknownPulls.Add(1)
			pctx, cancel := context.WithTimeout(ctx, 3*time.Second)
			_ = s.Pull(pctx, false)
			cancel()
		} else {
			// Another pull may be in flight; wait for it (single flight).
			s.pullMu.Lock()
			s.pullMu.Unlock() //nolint:staticcheck // barrier
		}
		d = s.Store.Check(nk)
	}
	if d == Allow {
		s.C.Allow.Add(1)
		return true
	}
	s.C.Deny.Add(1)
	return false
}

// Run pulls on a schedule and on feed notifications until ctx is done.
func (s *Syncer) Run(ctx context.Context) {
	s.defaults()
	_ = s.Pull(ctx, true)
	chg := make(chan int64, 1)
	go s.feed(ctx, chg)
	delta := time.NewTicker(s.DeltaEvery)
	full := time.NewTicker(s.FullEvery)
	defer delta.Stop()
	defer full.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-delta.C:
			_ = s.Pull(ctx, false)
		case <-full.C:
			_ = s.Pull(ctx, true)
		case seq := <-chg:
			if seq > s.Store.Seq() || !s.Store.Fresh() {
				_ = s.Pull(ctx, false)
			}
		}
	}
}

// feed holds the WebSocket change feed and forwards seq numbers.
func (s *Syncer) feed(ctx context.Context, out chan<- int64) {
	back := s.FeedBackoff
	for ctx.Err() == nil {
		err := s.feedOnce(ctx, out)
		if ctx.Err() != nil {
			return
		}
		_ = err
		select {
		case <-ctx.Done():
			return
		case <-time.After(back):
		}
		if back < time.Minute {
			back *= 2
		}
	}
}

func (s *Syncer) feedOnce(ctx context.Context, out chan<- int64) error {
	u, err := url.Parse(s.Base)
	if err != nil {
		return err
	}
	switch u.Scheme {
	case "https":
		u.Scheme = "wss"
	case "http":
		u.Scheme = "ws"
	}
	u.Path = "/v1/relay/feed"
	u.RawQuery = "rg=" + url.QueryEscape(s.Region)
	hdr := http.Header{}
	hdr.Set("Authorization", "Bearer "+s.Token)
	dctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	c, _, err := websocket.Dial(dctx, u.String(), &websocket.DialOptions{HTTPHeader: hdr, HTTPClient: s.HTTP})
	cancel()
	if err != nil {
		return err
	}
	defer c.CloseNow()
	c.SetReadLimit(4096)
	// Keepalive: the Worker auto-answers {"t":"ping"} without waking the DO.
	go func() {
		t := time.NewTicker(30 * time.Second)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				if c.Write(ctx, websocket.MessageText, []byte(`{"t":"ping"}`)) != nil {
					return
				}
			}
		}
	}()
	for {
		_, b, err := c.Read(ctx)
		if err != nil {
			return err
		}
		var m struct {
			T   string          `json:"t"`
			Seq json.RawMessage `json:"seq"`
		}
		if json.Unmarshal(b, &m) != nil || m.T != "chg" {
			continue
		}
		seq, err := strconv.ParseInt(string(m.Seq), 10, 64)
		if err != nil {
			continue
		}
		s.C.FeedChg.Add(1)
		select {
		case out <- seq:
		default: // a pull is already queued
		}
	}
}

// Handler serves derper's -verify-client-url POSTs.
func (s *Syncer) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/derp/admit", func(w http.ResponseWriter, r *http.Request) {
		allow := false
		if r.Method == http.MethodPost {
			var req struct {
				NodePublic string
				Source     string
			}
			if json.NewDecoder(io.LimitReader(r.Body, 4096)).Decode(&req) == nil {
				allow = s.Admit(r.Context(), req.NodePublic)
			} else {
				s.C.Deny.Add(1)
			}
		}
		w.Header().Set("Content-Type", "application/json")
		if allow {
			_, _ = io.WriteString(w, "{\"Allow\":true}\n")
		} else {
			_, _ = io.WriteString(w, "{\"Allow\":false}\n")
		}
	})
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		if !s.Store.Fresh() {
			http.Error(w, "stale", http.StatusServiceUnavailable)
			return
		}
		_, _ = io.WriteString(w, "ok\n")
	})
	return mux
}

// Snapshot returns counters for the periodic log line.
func (s *Syncer) Snapshot() map[string]int64 {
	return map[string]int64{
		"allow": s.C.Allow.Load(), "deny": s.C.Deny.Load(), "pulls": s.C.Pulls.Load(),
		"pull_errs": s.C.PullErrs.Load(), "rejected": s.C.Rejected.Load(), "feed_chg": s.C.FeedChg.Load(),
		"unknown_pulls": s.C.UnknownPulls.Load(), "seq": s.Store.Seq(), "keys": int64(s.Store.Len()),
	}
}
