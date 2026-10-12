package emailotp

import (
	"crypto/sha256"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type fakeAccount struct {
	hash    [32]byte
	changes int
}

func (a *fakeAccount) SetPassword(_, p string) error {
	a.hash = sha256.Sum256([]byte(p))
	a.changes++
	return nil
}
func (a *fakeAccount) CheckPassword(_, p string) (bool, error) {
	return a.hash == sha256.Sum256([]byte(p)), nil
}
func setup(t *testing.T) (*Manager, *fakeAccount, *time.Time) {
	t.Helper()
	now := time.Now()
	return &Manager{Path: filepath.Join(t.TempDir(), "state.json"), Now: func() time.Time { return now }}, &fakeAccount{}, &now
}
func TestCooldownSurvivesRestart(t *testing.T) {
	m, a, now := setup(t)
	var password string
	sends := 0
	send := func(_, p string) error { password = p; sends++; return nil }
	if err := m.Issue("user@example.com", a, send); err != nil {
		t.Fatal(err)
	}
	original := password
	fresh := &Manager{Path: m.Path, Now: m.Now}
	if err := fresh.Issue("user@example.com", a, send); err != nil {
		t.Fatal(err)
	}
	if sends != 1 || password != original || a.changes != 1 {
		t.Fatal("cooldown replaced password")
	}
	data, _ := os.ReadFile(m.Path)
	if strings.Contains(string(data), password) {
		t.Fatal("plaintext on disk")
	}
	*now = now.Add(Lifetime)
	if ok, _ := fresh.Consume("user@example.com", password, a); ok {
		t.Fatal("expired password accepted")
	}
	if err := fresh.Issue("user@example.com", a, send); err != nil || sends != 2 {
		t.Fatal("next window failed", err)
	}
}
func TestConcurrentConsumeOnlyOnce(t *testing.T) {
	m, a, _ := setup(t)
	var password string
	if err := m.Issue("u", a, func(_, p string) error { password = p; return nil }); err != nil {
		t.Fatal(err)
	}
	var count atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			ok, err := m.Consume("u", password, a)
			if err != nil {
				t.Error(err)
			}
			if ok {
				count.Add(1)
			}
		}()
	}
	wg.Wait()
	if count.Load() != 1 || a.changes != 2 {
		t.Fatal("password was not consumed exactly once")
	}
	if ok, _ := a.CheckPassword("u", password); ok {
		t.Fatal("account password not rotated")
	}
}
func TestAttemptsAndSMTPFailure(t *testing.T) {
	m, a, _ := setup(t)
	var password string
	_ = m.Issue("u", a, func(_, p string) error { password = p; return nil })
	for i := 0; i < MaxAttempts; i++ {
		if ok, _ := m.Consume("u", "wrong", a); ok {
			t.Fatal("wrong password accepted")
		}
	}
	if ok, _ := m.Consume("u", password, a); ok {
		t.Fatal("attempt limit bypassed")
	}
	m, a, _ = setup(t)
	sends := 0
	if err := m.Issue("u", a, func(_, p string) error { password = p; sends++; return errors.New("smtp") }); err == nil {
		t.Fatal("failure ignored")
	}
	_ = m.Issue("u", a, func(_, p string) error { sends++; return nil })
	if sends != 1 {
		t.Fatal("uncertain SMTP retried")
	}
	if ok, _ := m.Consume("u", password, a); ok {
		t.Fatal("failed issuance accepted")
	}
}
func TestMissingOrCorruptStateFailsClosed(t *testing.T) {
	m, a, _ := setup(t)
	_ = a.SetPassword("u", "old-password")
	if ok, _ := m.Consume("u", "old-password", a); ok {
		t.Fatal("permanent password accepted")
	}
	_ = os.WriteFile(m.Path, []byte("broken"), 0600)
	if ok, err := m.Consume("u", "old-password", a); ok || err == nil {
		t.Fatal("corruption ignored")
	}
	if err := m.Issue("u", a, func(_, p string) error { return nil }); err == nil {
		t.Fatal("state reset silently")
	}
}
