// Copyright (c) 2026 Nink Inc. All rights reserved.
package admit

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// MaxTTL caps how long one verified document keeps us "fresh", whatever the
// document says, measured on our own clock (no trust in clock agreement).
const MaxTTL = 15 * time.Minute

// Store is the local allowlist copy.
type Store struct {
	mu         sync.RWMutex
	region     string
	seq        int64
	keys       map[string]int64 // nodekey -> permit expiry (unix s)
	freshUntil time.Time
	path       string // persistence file ("" = none)
	now        func() time.Time
}

// NewStore makes an empty (stale, deny-all) store.
func NewStore(region, stateDir string, now func() time.Time) *Store {
	s := &Store{region: region, keys: map[string]int64{}, now: now}
	if stateDir != "" {
		s.path = filepath.Join(stateDir, "allowlist-"+region+".json")
	}
	return s
}

// Errors returned by Apply.
var (
	ErrRegion   = errors.New("region mismatch")
	ErrOldSeq   = errors.New("seq went backwards")
	ErrNotChain = errors.New("delta does not start at our seq")
)

// Apply installs a verified document. Full documents replace the set (seq must
// not go backwards); deltas must start exactly at our current seq.
func (s *Store) Apply(d *Doc) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if d.Rg != s.region {
		return ErrRegion
	}
	if d.Seq < s.seq {
		return ErrOldSeq
	}
	if d.Full {
		next := make(map[string]int64, len(d.Add))
		for _, e := range d.Add {
			next[e.K] = e.E
		}
		s.keys = next
	} else {
		if d.Since != s.seq || d.Since == 0 {
			return ErrNotChain
		}
		for _, k := range d.Del {
			delete(s.keys, k)
		}
		for _, e := range d.Add {
			s.keys[e.K] = e.E
		}
	}
	s.seq = d.Seq
	ttl := time.Duration(d.Exp-d.Iat) * time.Second
	if ttl > MaxTTL || ttl <= 0 {
		ttl = MaxTTL
	}
	s.freshUntil = s.now().Add(ttl)
	s.persistLocked()
	return nil
}

// Decision is the admission result and why.
type Decision int

const (
	Allow Decision = iota
	DenyStale
	DenyUnknown
	DenyExpired
)

// Check decides for one key. Fails closed when stale.
func (s *Store) Check(nk string) Decision {
	s.mu.RLock()
	defer s.mu.RUnlock()
	now := s.now()
	if !now.Before(s.freshUntil) {
		return DenyStale
	}
	e, ok := s.keys[nk]
	if !ok {
		return DenyUnknown
	}
	if e <= now.Unix() {
		return DenyExpired
	}
	return Allow
}

// Seq returns the current sequence number (0 = nothing yet).
func (s *Store) Seq() int64 {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.seq
}

// Fresh reports whether a verified document is within its TTL.
func (s *Store) Fresh() bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.now().Before(s.freshUntil)
}

// Len is the number of keys held.
func (s *Store) Len() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.keys)
}

type persisted struct {
	V          int              `json:"v"`
	Rg         string           `json:"rg"`
	Seq        int64            `json:"seq"`
	FreshUntil int64            `json:"fresh_until"`
	Keys       map[string]int64 `json:"keys"`
}

func (s *Store) persistLocked() {
	if s.path == "" {
		return
	}
	b, err := json.Marshal(persisted{V: 1, Rg: s.region, Seq: s.seq, FreshUntil: s.freshUntil.Unix(), Keys: s.keys})
	if err != nil {
		return
	}
	tmp := s.path + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return
	}
	_ = os.Rename(tmp, s.path)
}

// Load restores a persisted copy (so a restart within the TTL keeps serving).
// It never extends freshness beyond what the original document granted.
func (s *Store) Load() error {
	if s.path == "" {
		return nil
	}
	b, err := os.ReadFile(s.path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return err
	}
	var p persisted
	if err := json.Unmarshal(b, &p); err != nil || p.V != 1 || p.Rg != s.region {
		return errors.New("ignoring unreadable state file")
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.seq = p.Seq
	if p.Keys != nil {
		s.keys = p.Keys
	}
	fu := time.Unix(p.FreshUntil, 0)
	if max := s.now().Add(MaxTTL); fu.After(max) {
		fu = max
	}
	s.freshUntil = fu
	return nil
}
