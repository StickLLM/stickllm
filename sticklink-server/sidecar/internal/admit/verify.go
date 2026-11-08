// Copyright (c) 2026 Nink Inc. All rights reserved.
package admit

import (
	"bufio"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strings"
)

// DomAllowlist is the signature domain for allowlist documents.
const DomAllowlist = "sl1/allowlist/v1"

var b64 = base64.RawURLEncoding.Strict()

// NodeKeyRE matches tailscale's text form of a node public key.
var NodeKeyRE = regexp.MustCompile(`^nodekey:[0-9a-f]{64}$`)

// Envelope is the signed wrapper the Worker returns.
type Envelope struct {
	Kid  string `json:"kid"`
	Body string `json:"body"`
	Sig  string `json:"sig"`
}

// Entry is one admitted key and its permit expiry (unix seconds).
type Entry struct {
	K string `json:"k"`
	E int64  `json:"e"`
}

// Doc is the allowlist body.
type Doc struct {
	V     int      `json:"v"`
	Kid   string   `json:"kid"`
	Rg    string   `json:"rg"`
	Seq   int64    `json:"seq"`
	Since int64    `json:"since"`
	Iat   int64    `json:"iat"`
	Exp   int64    `json:"exp"`
	Full  bool     `json:"full"`
	Add   []Entry  `json:"add"`
	Del   []string `json:"del"`
}

// Keys maps kid -> pinned Ed25519 public key.
type Keys map[string]ed25519.PublicKey

// ParseKeys reads "kid base64url-pubkey" lines; '#' starts a comment.
func ParseKeys(r io.Reader) (Keys, error) {
	ks := Keys{}
	sc := bufio.NewScanner(r)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if i := strings.IndexByte(line, '#'); i >= 0 {
			line = strings.TrimSpace(line[:i])
		}
		if line == "" {
			continue
		}
		f := strings.Fields(line)
		if len(f) != 2 {
			return nil, fmt.Errorf("admit-keys: want 'kid pubkey', got %d fields", len(f))
		}
		pk, err := b64.DecodeString(f[1])
		if err != nil || len(pk) != ed25519.PublicKeySize {
			return nil, fmt.Errorf("admit-keys: bad key for kid %q", f[0])
		}
		ks[f[0]] = ed25519.PublicKey(pk)
	}
	if err := sc.Err(); err != nil {
		return nil, err
	}
	if len(ks) == 0 {
		return nil, errors.New("admit-keys: no keys")
	}
	return ks, nil
}

// SignedInput is domain || 0x00 || body.
func SignedInput(domain string, body []byte) []byte {
	out := make([]byte, 0, len(domain)+1+len(body))
	out = append(out, domain...)
	out = append(out, 0)
	return append(out, body...)
}

// Verify checks the envelope signature against the pinned keys and decodes
// the body. It also checks the body's own kid and version.
func (ks Keys) Verify(raw []byte) (*Doc, error) {
	var env Envelope
	if err := json.Unmarshal(raw, &env); err != nil {
		return nil, fmt.Errorf("envelope: %w", err)
	}
	pk, ok := ks[env.Kid]
	if !ok {
		return nil, errors.New("unknown kid")
	}
	body, err := b64.DecodeString(env.Body)
	if err != nil {
		return nil, errors.New("body encoding")
	}
	sig, err := b64.DecodeString(env.Sig)
	if err != nil || len(sig) != ed25519.SignatureSize {
		return nil, errors.New("sig encoding")
	}
	if !ed25519.Verify(pk, SignedInput(DomAllowlist, body), sig) {
		return nil, errors.New("bad signature")
	}
	var d Doc
	if err := json.Unmarshal(body, &d); err != nil {
		return nil, fmt.Errorf("body: %w", err)
	}
	if d.V != 1 || d.Kid != env.Kid {
		return nil, errors.New("version or kid mismatch")
	}
	for _, e := range d.Add {
		if !NodeKeyRE.MatchString(e.K) {
			return nil, errors.New("malformed key in add")
		}
	}
	for _, k := range d.Del {
		if !NodeKeyRE.MatchString(k) {
			return nil, errors.New("malformed key in del")
		}
	}
	return &d, nil
}
