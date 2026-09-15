// Package xaes256gcm implements XAES-256-GCM, an extended-nonce AEAD
// construction built on AES-256-GCM. It provides authenticated encryption
// with 256-bit keys and 192-bit nonces.
//
// See /app/spec.md for the full algorithm specification.
package xaes256gcm


import (
	"crypto/aes"
	"crypto/cipher"
	"errors"
)

// XAES256GCM implements the cipher.AEAD interface for XAES-256-GCM.
type XAES256GCM struct {
	key   [32]byte
	k1    [16]byte
	block cipher.Block
}

// New creates a new XAES-256-GCM cipher with the given 32-byte key.
func New(key []byte) (*XAES256GCM, error) {
	if len(key) != 32 {
		return nil, errors.New("xaes256gcm: key must be 32 bytes")
	}
	x := &XAES256GCM{}
	copy(x.key[:], key)

	// Create AES block cipher for CMAC subkey derivation and KDF
	var err error
	x.block, err = aes.NewCipher(x.key[:16])
	if err != nil {
		return nil, err
	}

	x.deriveK1()
	return x, nil
}

// NonceSize returns the required nonce size (24 bytes / 192 bits).
func (x *XAES256GCM) NonceSize() int { return 24 }

// Overhead returns the maximum difference between ciphertext and plaintext
// lengths (16 bytes for the GCM authentication tag).
func (x *XAES256GCM) Overhead() int { return 16 }

// aesEncryptBlock encrypts a single 16-byte block using AES-ECB with the
// instance's block cipher.
func (x *XAES256GCM) aesEncryptBlock(src [16]byte) [16]byte {
	var dst [16]byte
	x.block.Encrypt(dst[:], src[:])
	return dst
}

// deriveK1 computes the CMAC subkey K1 from the encryption key.
//
// Follows NIST SP 800-38B subkey generation:
//  1. L = AES-256_K(0^128)
//  2. If MSB(L) == 0: K1 = L << 1
//     Else: K1 = (L << 1) XOR R_b
func (x *XAES256GCM) deriveK1() {
	// Encrypt the zero block to get L
	var zero [16]byte
	L := x.aesEncryptBlock(zero)

	// Check the most significant bit of L
	msb := (L[0] >> 7) & 1

	// Perform the left shift of L by 1 bit across all 16 bytes
	var shifted [16]byte
	for i := 0; i < 15; i++ {
		shifted[i] = (L[i] << 1) | (L[i+1] & 1)
	}
	shifted[15] = L[15] << 1

	// Apply the R_b feedback polynomial for the GF(2^128) doubling
	if msb == 1 {
		shifted[15] ^= 0xE1
	}

	x.k1 = shifted
}

// deriveKeyAndNonce derives the AES-256-GCM key and nonce from the
// XAES-256-GCM nonce using the CMAC-based KDF.
//
// Constructs M1 and M2 blocks using the counter-mode KDF structure:
//
//	M_i = counter(i) || label || separator || context
//
// where context is the first 12 bytes of the input nonce.
//
// Returns:
//
//	(derivedKey, derivedNonce): 32-byte key and 12-byte nonce
//	for use with standard AES-256-GCM.
func (x *XAES256GCM) deriveKeyAndNonce(nonce []byte) ([]byte, []byte) {
	// Build the two KDF input blocks with counter, label 'X', separator, context
	var m1, m2 [16]byte
	// counter(1) = 0x0001 big-endian, label = 0x58 ('X'), separator = 0x00
	m1[0], m1[1], m1[2], m1[3] = 0x00, 0x00, 0x58, 0x00
	m2[0], m2[1], m2[2], m2[3] = 0x00, 0x01, 0x58, 0x00
	// Context = N[0:12]
	copy(m1[4:], nonce[:12])
	copy(m2[4:], nonce[:12])

	// XOR each block with the CMAC subkey K1
	for i := 0; i < 16; i++ {
		m1[i] ^= x.k1[i]
		m2[i] ^= x.k1[i]
	}

	// Encrypt each masked block to produce 16 bytes of derived key material
	dk1 := x.aesEncryptBlock(m1)
	dk2 := x.aesEncryptBlock(m2)

	derivedKey := make([]byte, 32)
	copy(derivedKey[:16], dk1[:])
	copy(derivedKey[16:], dk2[:])

	// The AES-256-GCM nonce is derived from the input nonce
	derivedNonce := make([]byte, 12)
	copy(derivedNonce, nonce[:12])

	return derivedKey, derivedNonce
}

// Seal encrypts and authenticates plaintext, authenticates the additional
// data, and appends the result to dst, returning the updated slice.
func (x *XAES256GCM) Seal(dst, nonce, plaintext, additionalData []byte) []byte {
	if len(nonce) != x.NonceSize() {
		panic("xaes256gcm: incorrect nonce length")
	}

	dk, dn := x.deriveKeyAndNonce(nonce)
	block, _ := aes.NewCipher(dk)
	gcm, _ := cipher.NewGCM(block)
	return gcm.Seal(dst, dn, plaintext, additionalData)
}

// Open decrypts and authenticates ciphertext, authenticates the additional
// data, and if successful appends the resulting plaintext to dst, returning
// the updated slice.
func (x *XAES256GCM) Open(dst, nonce, ciphertext, additionalData []byte) ([]byte, error) {
	if len(nonce) != x.NonceSize() {
		return nil, errors.New("xaes256gcm: incorrect nonce length")
	}

	dk, dn := x.deriveKeyAndNonce(nonce)
	block, _ := aes.NewCipher(dk)
	gcm, _ := cipher.NewGCM(block)
	return gcm.Open(dst, dn, ciphertext, additionalData)
}
