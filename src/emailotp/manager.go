// SPDX-License-Identifier: Apache-2.0
// Package emailotp implements the login challenge policy independently of the
// authentication library, account storage, SMTP transport and OAuth clients.
package emailotp

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"os"
	"path/filepath"
	"sync"
	"time"
)

const Lifetime = 15 * time.Minute
const MaxAttempts = 5

type Account interface {
	SetPassword(username, password string) error
	CheckPassword(username, password string) (bool, error)
}
type Sender func(username, password string) error
type Challenge struct {
	Issued   int64 `json:"issued"`
	Attempts int   `json:"attempts"`
	Used     bool  `json:"used"`
}
type Manager struct {
	mu   sync.Mutex
	Path string
	Now  func() time.Time
}

func (m *Manager) now() time.Time {
	if m.Now != nil {
		return m.Now()
	}
	return time.Now()
}
func (m *Manager) load() (map[string]Challenge, error) {
	state := map[string]Challenge{}
	b, err := os.ReadFile(m.Path)
	if os.IsNotExist(err) {
		return state, nil
	}
	if err != nil {
		return nil, err
	}
	if err = json.Unmarshal(b, &state); err != nil || state == nil {
		return nil, errors.New("invalid challenge state")
	}
	return state, nil
}
func (m *Manager) save(state map[string]Challenge) error {
	b, err := json.Marshal(state)
	if err != nil {
		return err
	}
	file, err := os.CreateTemp(filepath.Dir(m.Path), ".email-otp-*")
	if err != nil {
		return err
	}
	defer os.Remove(file.Name())
	if _, err = file.Write(b); err != nil {
		file.Close()
		return err
	}
	if err = file.Sync(); err != nil {
		file.Close()
		return err
	}
	if err = file.Close(); err != nil {
		return err
	}
	return os.Rename(file.Name(), m.Path)
}
func randomPassword() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

// Issue only accepts an already resolved, administrator-created account.
// Cooldown is persisted before any external side effect, including SMTP.
func (m *Manager) Issue(username string, account Account, send Sender) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	state, err := m.load()
	if err != nil {
		return err
	}
	now := m.now().Unix()
	previous, exists := state[username]
	if exists && now < previous.Issued+int64(Lifetime.Seconds()) {
		return nil
	}
	number, err := rand.Int(rand.Reader, big.NewInt(100000000))
	if err != nil {
		return err
	}
	password := fmt.Sprintf("%08d", number.Int64())
	state[username] = Challenge{Issued: now, Used: true}
	if err = m.save(state); err != nil {
		return err
	}
	if err = account.SetPassword(username, password); err != nil {
		return err
	}
	if err = send(username, password); err != nil {
		// SMTP may have accepted mail before a disconnect; do not resend within cooldown.
		replacement, e := randomPassword()
		if e == nil {
			_ = account.SetPassword(username, replacement)
		}
		return err
	}
	state[username] = Challenge{Issued: now}
	return m.save(state)
}

// Consume serializes checking and burning the challenge, then replaces the
// account password before the caller creates a login/OAuth session.
func (m *Manager) Consume(username, password string, account Account) (bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	state, err := m.load()
	if err != nil {
		return false, err
	}
	challenge, exists := state[username]
	if !exists || challenge.Used || challenge.Attempts >= MaxAttempts || m.now().Unix() >= challenge.Issued+int64(Lifetime.Seconds()) {
		return false, nil
	}
	challenge.Attempts++
	state[username] = challenge
	if err = m.save(state); err != nil {
		return false, err
	}
	ok, err := account.CheckPassword(username, password)
	if err != nil || !ok {
		return false, err
	}
	challenge.Used = true
	state[username] = challenge
	if err = m.save(state); err != nil {
		return false, err
	}
	replacement, err := randomPassword()
	if err != nil {
		return false, err
	}
	if err = account.SetPassword(username, replacement); err != nil {
		return false, err
	}
	return true, nil
}
