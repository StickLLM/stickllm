// Copyright (c) 2026 Nink Inc. All rights reserved.

// sldprobe: connect to a DERP server with a given node key and report whether
// the server admits it. Built inside the tailscale tree via `go build -overlay`
// (see ../run.sh) so the tailscale source is not modified.
//
//	sldprobe -url http://127.0.0.1:3340/derp -genkey            -> prints "privkey:... nodekey:..."
//	sldprobe -url http://127.0.0.1:3340/derp -key privkey:...   -> prints ADMITTED or REJECTED
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"time"

	"tailscale.com/derp"
	"tailscale.com/derp/derphttp"
	"tailscale.com/net/netmon"
	"tailscale.com/types/key"
)

func main() {
	url := flag.String("url", "http://127.0.0.1:3340/derp", "derp URL")
	keyText := flag.String("key", "", "node private key (privkey:hex)")
	gen := flag.Bool("genkey", false, "generate a node key and print 'privkey nodekey'")
	flag.Parse()
	if *gen {
		k := key.NewNode()
		pt, _ := k.MarshalText()
		fmt.Printf("%s %s\n", pt, k.Public().String())
		return
	}
	var k key.NodePrivate
	if err := k.UnmarshalText([]byte(*keyText)); err != nil {
		log.Fatalf("bad -key: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	c, err := derphttp.NewClient(k, *url, func(string, ...any) {}, netmon.NewStatic())
	if err != nil {
		log.Fatal(err)
	}
	defer c.Close()
	if err := c.Connect(ctx); err != nil {
		fmt.Println("REJECTED connect:", err)
		os.Exit(2)
	}
	// Send to ourselves: an admitted client gets ServerInfo and its own packet back.
	_ = c.Send(k.Public(), []byte("sl-probe"))
	res := make(chan string, 1)
	go func() {
		for {
			m, err := c.Recv()
			if err != nil {
				res <- "REJECTED " + err.Error()
				return
			}
			if p, ok := m.(derp.ReceivedPacket); ok && string(p.Data) == "sl-probe" {
				res <- "ADMITTED"
				return
			}
		}
	}()
	select {
	case r := <-res:
		fmt.Println(r)
		if r != "ADMITTED" {
			os.Exit(2)
		}
	case <-time.After(5 * time.Second):
		fmt.Println("REJECTED timeout")
		os.Exit(2)
	}
}
