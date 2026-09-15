// Command xaesgcm provides a CLI for XAES-256-GCM encrypt/decrypt operations.
// All inputs and outputs are hex-encoded.
//
// Usage:
//
//	xaesgcm encrypt <key_hex> <nonce_hex> <plaintext_hex> [aad_hex]
//	xaesgcm decrypt <key_hex> <nonce_hex> <ciphertext_hex> [aad_hex]
package main

import (
	"encoding/hex"
	"fmt"
	"os"

	xaes "xaes256gcm"
)

func main() {
	if len(os.Args) < 5 {
		fmt.Fprintln(os.Stderr, "Usage: xaesgcm <encrypt|decrypt> <key_hex> <nonce_hex> <data_hex> [aad_hex]")
		os.Exit(1)
	}

	op := os.Args[1]
	key, err := hex.DecodeString(os.Args[2])
	if err != nil {
		fmt.Fprintf(os.Stderr, "invalid key hex: %v\n", err)
		os.Exit(1)
	}
	nonce, err := hex.DecodeString(os.Args[3])
	if err != nil {
		fmt.Fprintf(os.Stderr, "invalid nonce hex: %v\n", err)
		os.Exit(1)
	}
	data, err := hex.DecodeString(os.Args[4])
	if err != nil {
		fmt.Fprintf(os.Stderr, "invalid data hex: %v\n", err)
		os.Exit(1)
	}

	var aad []byte
	if len(os.Args) > 5 && os.Args[5] != "" {
		aad, err = hex.DecodeString(os.Args[5])
		if err != nil {
			fmt.Fprintf(os.Stderr, "invalid aad hex: %v\n", err)
			os.Exit(1)
		}
	}

	cipher, err := xaes.New(key)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	switch op {
	case "encrypt":
		ct := cipher.Seal(nil, nonce, data, aad)
		fmt.Print(hex.EncodeToString(ct))
	case "decrypt":
		pt, err := cipher.Open(nil, nonce, data, aad)
		if err != nil {
			fmt.Fprintf(os.Stderr, "decryption failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Print(hex.EncodeToString(pt))
	default:
		fmt.Fprintf(os.Stderr, "unknown operation: %s (use encrypt or decrypt)\n", op)
		os.Exit(1)
	}
}
