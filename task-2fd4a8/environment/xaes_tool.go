package main

import (
	"crypto/aes"
	"crypto/cipher"
	"encoding/hex"
	"fmt"
	"os"
)

func deriveKey(key, nonce []byte) (kx []byte, nx []byte) {
	block, err := aes.NewCipher(key)
	if err != nil {
		fmt.Fprintf(os.Stderr, "aes.NewCipher: %v\n", err)
		os.Exit(1)
	}

	L := make([]byte, 16)
	block.Encrypt(L, make([]byte, 16))

	msb := L[0] >> 7
	K1 := make([]byte, 16)
	for i := 0; i < 15; i++ {
		K1[i] = (L[i] << 1) | (L[i+1] >> 7)
	}
	K1[15] = L[15] << 1
	if msb == 1 {
		K1[15] ^= 0x87
	}

	M1 := make([]byte, 16)
	M1[1] = 0x01
	M1[2] = 0x58
	copy(M1[4:], nonce[:12])

	M2 := make([]byte, 16)
	M2[1] = 0x02
	M2[2] = 0x58
	copy(M2[4:], nonce[:12])

	for i := range M1 {
		M1[i] ^= K1[i]
		M2[i] ^= K1[i]
	}
	kx = make([]byte, 32)
	block.Encrypt(kx[:16], M1)
	block.Encrypt(kx[16:], M2)

	nx = make([]byte, 12)
	copy(nx, nonce[12:])
	return kx, nx
}

func xaesEncrypt(key, nonce, pt, aad []byte) ([]byte, error) {
	kx, nx := deriveKey(key, nonce)
	block, err := aes.NewCipher(kx)
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	return gcm.Seal(nil, nx, pt, aad), nil
}

func xaesDecrypt(key, nonce, ct, aad []byte) ([]byte, error) {
	kx, nx := deriveKey(key, nonce)
	block, err := aes.NewCipher(kx)
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	return gcm.Open(nil, nx, ct, aad)
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "Usage: xaes_tool <command> [args...]\n")
		fmt.Fprintf(os.Stderr, "Commands:\n")
		fmt.Fprintf(os.Stderr, "  encrypt    <key_hex> <nonce_hex> <plaintext_hex> [aad_hex]\n")
		fmt.Fprintf(os.Stderr, "  decrypt    <key_hex> <nonce_hex> <ciphertext_hex> [aad_hex]\n")
		fmt.Fprintf(os.Stderr, "  derive-key <key_hex> <nonce_hex>\n")
		os.Exit(1)
	}

	cmd := os.Args[1]

	switch cmd {
	case "encrypt":
		if len(os.Args) < 5 {
			fmt.Fprintf(os.Stderr, "Usage: xaes_tool encrypt <key_hex> <nonce_hex> <plaintext_hex> [aad_hex]\n")
			os.Exit(1)
		}
		key, err := hex.DecodeString(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "bad key hex: %v\n", err)
			os.Exit(1)
		}
		nonce, err := hex.DecodeString(os.Args[3])
		if err != nil {
			fmt.Fprintf(os.Stderr, "bad nonce hex: %v\n", err)
			os.Exit(1)
		}
		pt, err := hex.DecodeString(os.Args[4])
		if err != nil {
			fmt.Fprintf(os.Stderr, "bad plaintext hex: %v\n", err)
			os.Exit(1)
		}
		var aad []byte
		if len(os.Args) > 5 {
			aad, err = hex.DecodeString(os.Args[5])
			if err != nil {
				fmt.Fprintf(os.Stderr, "bad aad hex: %v\n", err)
				os.Exit(1)
			}
		}
		ct, err := xaesEncrypt(key, nonce, pt, aad)
		if err != nil {
			fmt.Fprintf(os.Stderr, "encrypt error: %v\n", err)
			os.Exit(1)
		}
		fmt.Println(hex.EncodeToString(ct))

	case "decrypt":
		if len(os.Args) < 5 {
			fmt.Fprintf(os.Stderr, "Usage: xaes_tool decrypt <key_hex> <nonce_hex> <ciphertext_hex> [aad_hex]\n")
			os.Exit(1)
		}
		key, err := hex.DecodeString(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "bad key hex: %v\n", err)
			os.Exit(1)
		}
		nonce, err := hex.DecodeString(os.Args[3])
		if err != nil {
			fmt.Fprintf(os.Stderr, "bad nonce hex: %v\n", err)
			os.Exit(1)
		}
		ct, err := hex.DecodeString(os.Args[4])
		if err != nil {
			fmt.Fprintf(os.Stderr, "bad ciphertext hex: %v\n", err)
			os.Exit(1)
		}
		var aad []byte
		if len(os.Args) > 5 {
			aad, err = hex.DecodeString(os.Args[5])
			if err != nil {
				fmt.Fprintf(os.Stderr, "bad aad hex: %v\n", err)
				os.Exit(1)
			}
		}
		pt, err := xaesDecrypt(key, nonce, ct, aad)
		if err != nil {
			fmt.Fprintf(os.Stderr, "decrypt failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Println(hex.EncodeToString(pt))

	case "derive-key":
		if len(os.Args) < 4 {
			fmt.Fprintf(os.Stderr, "Usage: xaes_tool derive-key <key_hex> <nonce_hex>\n")
			os.Exit(1)
		}
		key, err := hex.DecodeString(os.Args[2])
		if err != nil {
			fmt.Fprintf(os.Stderr, "bad key hex: %v\n", err)
			os.Exit(1)
		}
		nonce, err := hex.DecodeString(os.Args[3])
		if err != nil {
			fmt.Fprintf(os.Stderr, "bad nonce hex: %v\n", err)
			os.Exit(1)
		}
		kx, nx := deriveKey(key, nonce)
		fmt.Printf("Kx=%s\nNx=%s\n", hex.EncodeToString(kx), hex.EncodeToString(nx))

	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", cmd)
		os.Exit(1)
	}
}
