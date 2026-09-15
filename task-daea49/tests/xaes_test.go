// Tests for XAES-256-GCM Go implementation correctness.
//
// Verifies the implementation against hardcoded test vectors derived from the
// specification, covering both CMAC subkey derivation code paths and an
// accumulated test vector hash using SHA-256 CTR PRNG.
//

package xaes256gcm

import (
	"bytes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"testing"
)

// Test vector data
type testVector struct {
	name       string
	keyHex     string
	nonceHex   string
	ptHex      string
	aadHex     string
	ctHex      string
}

var testVectors = []testVector{
	{
		name:     "MSB(L)=0, no polynomial feedback",
		keyHex:   "df3f619804a92fdb4057192dc43dd748ea778adc52bc498ce80524c014b81119",
		nonceHex: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		ptHex:    "7465737420766563746f72206f6e65",
		aadHex:   "61616431",
		ctHex:    "bf69fc60fa8d13d40d0fa9865bca7d222dfcac5e8a147a54300fcdbf0bcbe8",
	},
	{
		name:     "MSB(L)=1, polynomial feedback applied",
		keyHex:   "b40711a88c7039756fb8a73827eabe2c0fe5a0346ca7e0a104adc0fc764f528d",
		nonceHex: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
		ptHex:    "7465737420766563746f722074776f",
		aadHex:   "61616432",
		ctHex:    "de34f0984522b2433ac92666e39414156ce57090de85652ec13b28dd90a858",
	},
	{
		name:     "empty plaintext, auth-only",
		keyHex:   "0000000000000000000000000000000000000000000000000000000000000000",
		nonceHex: "ffffffffffffffffffffffffffffffffffffffffffffffff",
		ptHex:    "",
		aadHex:   "6f6e6c792d616164",
		ctHex:    "199509ea809003e7a053d4a342111fac",
	},
	{
		name:     "no AAD",
		keyHex:   "4242424242424242424242424242424242424242424242424242424242424242",
		nonceHex: "131313131313131313131313131313131313131313131313",
		ptHex:    "6e6f206161642068657265",
		aadHex:   "",
		ctHex:    "24221eea02c5f8c8554122bd7aeb30021fdd715698225871b325d0",
	},
	{
		name:     "interoperability vector",
		keyHex:   "e2e41db53dfd24e4bc267e0e1e7753bf4b1d37a5dc1ba5e63579e04a7dc94e9c",
		nonceHex: "aabbccddeeff00112233445566778899aabbccddeeff0011",
		ptHex:    "63726f73732d6c616e677561676520696e7465726f7065726162696c6974792074657374",
		aadHex:   "696e7465726f702d6161642d7631",
		ctHex:    "127e63e742db6b3d117ef0198a578dcebb64354dd376e0a8a47e5671984fa78695cd53f69ea80afa720e521d1938fd5f5fa1cb57",
	},
}

func mustDecodeHex(s string) []byte {
	b, err := hex.DecodeString(s)
	if err != nil {
		panic("bad hex: " + err.Error())
	}
	return b
}

func TestInterfaceCompliance(t *testing.T) {
	// Compile-time check that *XAES256GCM implements cipher.AEAD
	var _ cipher.AEAD = (*XAES256GCM)(nil)

	c, err := New(make([]byte, 32))
	if err != nil {
		t.Fatal(err)
	}
	if c.NonceSize() != 24 {
		t.Errorf("NonceSize() = %d, want 24", c.NonceSize())
	}
	if c.Overhead() != 16 {
		t.Errorf("Overhead() = %d, want 16", c.Overhead())
	}
}

func TestKnownVectors(t *testing.T) {
	for _, tv := range testVectors {
		t.Run(tv.name, func(t *testing.T) {
			key := mustDecodeHex(tv.keyHex)
			nonce := mustDecodeHex(tv.nonceHex)
			pt := mustDecodeHex(tv.ptHex)
			aad := mustDecodeHex(tv.aadHex)
			expectedCT := mustDecodeHex(tv.ctHex)

			c, err := New(key)
			if err != nil {
				t.Fatalf("New() error: %v", err)
			}

			got := c.Seal(nil, nonce, pt, aad)
			if !bytes.Equal(got, expectedCT) {
				t.Errorf("Seal mismatch:\n  got:  %x\n  want: %x", got, expectedCT)
			}
		})
	}
}

func TestDecryption(t *testing.T) {
	for _, tv := range testVectors {
		t.Run(tv.name, func(t *testing.T) {
			key := mustDecodeHex(tv.keyHex)
			nonce := mustDecodeHex(tv.nonceHex)
			expectedPT := mustDecodeHex(tv.ptHex)
			aad := mustDecodeHex(tv.aadHex)
			ct := mustDecodeHex(tv.ctHex)

			c, err := New(key)
			if err != nil {
				t.Fatalf("New() error: %v", err)
			}

			got, err := c.Open(nil, nonce, ct, aad)
			if err != nil {
				t.Fatalf("Open() error: %v", err)
			}
			if !bytes.Equal(got, expectedPT) {
				t.Errorf("Open mismatch:\n  got:  %x\n  want: %x", got, expectedPT)
			}
		})
	}
}

func TestRoundTrip(t *testing.T) {
	cases := []struct {
		name   string
		ptSize int
		aad    []byte
	}{
		{"basic", 20, []byte("some metadata")},
		{"empty_plaintext", 0, []byte("aad-only")},
		{"empty_aad", 100, nil},
		{"large", 65536, []byte("large-test")},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			key := make([]byte, 32)
			nonce := make([]byte, 24)
			if _, err := rand.Read(key); err != nil {
				t.Fatal(err)
			}
			if _, err := rand.Read(nonce); err != nil {
				t.Fatal(err)
			}

			pt := make([]byte, tc.ptSize)
			if tc.ptSize > 0 {
				if _, err := rand.Read(pt); err != nil {
					t.Fatal(err)
				}
			}

			c, err := New(key)
			if err != nil {
				t.Fatalf("New() error: %v", err)
			}

			ct := c.Seal(nil, nonce, pt, tc.aad)
			recovered, err := c.Open(nil, nonce, ct, tc.aad)
			if err != nil {
				t.Fatalf("Open() error: %v", err)
			}
			if !bytes.Equal(recovered, pt) {
				t.Error("round-trip plaintext mismatch")
			}
		})
	}
}

func TestSealDstAppend(t *testing.T) {
	// Verify Seal appends to dst (cipher.AEAD contract)
	key := make([]byte, 32)
	nonce := make([]byte, 24)
	rand.Read(key)
	rand.Read(nonce)

	c, _ := New(key)

	prefix := []byte("PREFIX")
	result := c.Seal(prefix, nonce, []byte("hello"), nil)

	if !bytes.HasPrefix(result, prefix) {
		t.Error("Seal did not append to dst")
	}
}

func TestInvalidKeySize(t *testing.T) {
	_, err := New(make([]byte, 16))
	if err == nil {
		t.Error("expected error for 16-byte key")
	}
	_, err = New(make([]byte, 64))
	if err == nil {
		t.Error("expected error for 64-byte key")
	}
}

func TestTamperedCiphertextRejected(t *testing.T) {
	key := make([]byte, 32)
	nonce := make([]byte, 24)
	rand.Read(key)
	rand.Read(nonce)

	c, _ := New(key)
	ct := c.Seal(nil, nonce, []byte("secret"), []byte("aad"))

	tampered := make([]byte, len(ct))
	copy(tampered, ct)
	tampered[0] ^= 0xFF

	_, err := c.Open(nil, nonce, tampered, []byte("aad"))
	if err == nil {
		t.Error("expected error for tampered ciphertext")
	}
}

func TestWrongAADRejected(t *testing.T) {
	key := make([]byte, 32)
	nonce := make([]byte, 24)
	rand.Read(key)
	rand.Read(nonce)

	c, _ := New(key)
	ct := c.Seal(nil, nonce, []byte("data"), []byte("correct"))

	_, err := c.Open(nil, nonce, ct, []byte("wrong"))
	if err == nil {
		t.Error("expected error for wrong AAD")
	}
}

// sha256CtrPRNG generates deterministic pseudo-random bytes using SHA-256
// in counter mode. Must match the Python implementation in test_state.py.
func sha256CtrPRNG(seed []byte, n int) []byte {
	result := make([]byte, 0, n+32)
	for ctr := uint32(0); len(result) < n; ctr++ {
		var buf []byte
		buf = append(buf, seed...)
		ctrBytes := make([]byte, 4)
		binary.BigEndian.PutUint32(ctrBytes, ctr)
		buf = append(buf, ctrBytes...)
		h := sha256.Sum256(buf)
		result = append(result, h[:]...)
	}
	return result[:n]
}

func TestAccumulated1000(t *testing.T) {
	const expectedHash = "2bdb71ed2de2ae4f98d641893903eb11668079586e10a07a02259d5430909b2c"

	seedHash := sha256.Sum256([]byte("XAES-256-GCM accumulated test vectors v2"))
	rng := sha256CtrPRNG(seedHash[:], 500000)
	offset := 0

	draw := func(n int) []byte {
		result := rng[offset : offset+n]
		offset += n
		return result
	}

	acc := sha256.New()

	for i := 0; i < 1000; i++ {
		key := draw(32)
		nonce := draw(24)
		ptLen := i % 128
		aadLen := i % 64
		plaintext := draw(ptLen)
		aad := draw(aadLen)

		c, err := New(key)
		if err != nil {
			t.Fatalf("New() error at iteration %d: %v", i, err)
		}

		ct := c.Seal(nil, nonce, plaintext, aad)
		acc.Write(ct)

		// Verify round-trip
		recovered, err := c.Open(nil, nonce, ct, aad)
		if err != nil {
			t.Fatalf("Open() error at iteration %d: %v", i, err)
		}
		if !bytes.Equal(recovered, plaintext) {
			t.Fatalf("round-trip mismatch at iteration %d", i)
		}
	}

	got := hex.EncodeToString(acc.Sum(nil))
	if got != expectedHash {
		t.Errorf("accumulated hash mismatch:\n  got:  %s\n  want: %s", got, expectedHash)
	}
}
