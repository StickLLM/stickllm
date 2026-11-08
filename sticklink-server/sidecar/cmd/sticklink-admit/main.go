// Copyright (c) 2026 Nink Inc. All rights reserved.

// sticklink-admit is derper's admission controller for sticklink relays.
// It replaces the deny-all derp-admit.py stub on 127.0.0.1:9099.
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"sort"
	"strings"
	"syscall"
	"time"

	"stickllm.com/sticklink/sidecar/internal/admit"
)

func main() {
	listen := flag.String("listen", "127.0.0.1:9099", "address derper's -verify-client-url points at")
	base := flag.String("base", "https://link.stickllm.com", "signalling Worker base URL")
	region := flag.String("region", "tor1", "relay region id")
	tokenFile := flag.String("token-file", "/etc/sticklink/admit-token", "file holding the relay bearer token")
	keysFile := flag.String("keys", "/etc/sticklink/admit-keys", "pinned signing keys: 'kid base64url-pubkey' per line")
	stateDir := flag.String("state", "/var/lib/sticklink-admit", "state directory (\"\" disables persistence)")
	statsEvery := flag.Duration("stats", 10*time.Minute, "how often to log counters")
	flag.Parse()

	tok, err := os.ReadFile(*tokenFile)
	if err != nil {
		log.Fatalf("token file: %v", err)
	}
	f, err := os.Open(*keysFile)
	if err != nil {
		log.Fatalf("keys file: %v", err)
	}
	keys, err := admit.ParseKeys(f)
	f.Close()
	if err != nil {
		log.Fatal(err)
	}

	store := admit.NewStore(*region, *stateDir, time.Now)
	if err := store.Load(); err != nil {
		log.Printf("state: %v", err)
	}
	s := &admit.Syncer{Base: strings.TrimRight(*base, "/"), Region: *region, Token: strings.TrimSpace(string(tok)), Keys: keys, Store: store}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go s.Run(ctx)
	go func() {
		t := time.NewTicker(*statsEvery)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				logStats(s.Snapshot())
			}
		}
	}()

	srv := &http.Server{Addr: *listen, Handler: s.Handler(), ReadHeaderTimeout: 5 * time.Second, ErrorLog: log.New(discard{}, "", 0)}
	go func() {
		<-ctx.Done()
		sctx, c := context.WithTimeout(context.Background(), 3*time.Second)
		defer c()
		_ = srv.Shutdown(sctx)
	}()
	log.Printf("sticklink-admit listening on %s region=%s", *listen, *region)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatal(err)
	}
	logStats(s.Snapshot())
}

// logStats prints counters only: no keys, no IPs.
func logStats(m map[string]int64) {
	ks := make([]string, 0, len(m))
	for k := range m {
		ks = append(ks, k)
	}
	sort.Strings(ks)
	var b strings.Builder
	for _, k := range ks {
		fmt.Fprintf(&b, "%s=%d ", k, m[k])
	}
	log.Print(strings.TrimSpace(b.String()))
}

type discard struct{}

func (discard) Write(p []byte) (int, error) { return len(p), nil }
