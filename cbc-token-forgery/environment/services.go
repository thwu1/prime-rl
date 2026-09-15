package main

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

const BS = aes.BlockSize

func rb(n int) []byte {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		log.Fatal(err)
	}
	return b
}

func pad(d []byte) []byte {
	n := BS - len(d)%BS
	p := make([]byte, n)
	for i := range p {
		p[i] = byte(n)
	}
	return append(d, p...)
}

func unpad(d []byte) ([]byte, error) {
	if len(d) == 0 || len(d)%BS != 0 {
		return nil, fmt.Errorf("len")
	}
	n := int(d[len(d)-1])
	if n < 1 || n > BS {
		return nil, fmt.Errorf("val")
	}
	for i := len(d) - n; i < len(d); i++ {
		if d[i] != byte(n) {
			return nil, fmt.Errorf("pad")
		}
	}
	return d[:len(d)-n], nil
}

func pt() string {
	return fmt.Sprintf("v2|basic|guest|%s|%010d", hex.EncodeToString(rb(8)), time.Now().Unix())
}

func pv(s string) map[string]string {
	parts := strings.SplitN(s, "|", 5)
	if len(parts) < 5 || parts[0] != "v2" {
		return nil
	}
	return map[string]string{
		"role": parts[1],
		"user": parts[2],
	}
}

func jw(w http.ResponseWriter, code int, d interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(d)
}

type sA struct {
	key []byte
	iv  []byte
	fl  string
}

func nA() *sA {
	return &sA{rb(16), rb(BS), "TBFLAG-" + hex.EncodeToString(rb(16))}
}

func (s *sA) e(p []byte) []byte {
	blk, _ := aes.NewCipher(s.key)
	ct := make([]byte, len(p))
	cipher.NewCTR(blk, s.iv).XORKeyStream(ct, p)
	return ct
}

func (s *sA) d(c []byte) []byte { return s.e(c) }

type sB struct {
	key []byte
	fl  string
}

func nB() *sB {
	return &sB{rb(16), "TBFLAG-" + hex.EncodeToString(rb(16))}
}

func (s *sB) e(p []byte) []byte {
	iv := rb(BS)
	blk, _ := aes.NewCipher(s.key)
	pd := pad(p)
	ct := make([]byte, len(pd))
	cipher.NewCBCEncrypter(blk, iv).CryptBlocks(ct, pd)
	return append(iv, ct...)
}

func (s *sB) d(raw []byte) ([]byte, error) {
	if len(raw) < 2*BS || len(raw)%BS != 0 {
		return nil, fmt.Errorf("len")
	}
	iv, ct := raw[:BS], raw[BS:]
	blk, _ := aes.NewCipher(s.key)
	r := make([]byte, len(ct))
	cipher.NewCBCDecrypter(blk, iv).CryptBlocks(r, ct)
	return unpad(r)
}

type sC struct {
	key []byte
	gcm cipher.AEAD
	fl  string
}

func nC() *sC {
	k := rb(32)
	blk, _ := aes.NewCipher(k)
	g, _ := cipher.NewGCM(blk)
	return &sC{k, g, "TBFLAG-" + hex.EncodeToString(rb(16))}
}

func (s *sC) e(p []byte) []byte {
	nonce := rb(s.gcm.NonceSize())
	return s.gcm.Seal(nonce, nonce, p, nil)
}

func (s *sC) d(raw []byte) ([]byte, error) {
	ns := s.gcm.NonceSize()
	if len(raw) < ns+s.gcm.Overhead() {
		return nil, fmt.Errorf("short")
	}
	return s.gcm.Open(nil, raw[:ns], raw[ns:], nil)
}

func rawSesH(enc func([]byte) []byte) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			w.WriteHeader(405)
			return
		}
		ct := enc([]byte(pt()))
		w.Header().Set("Content-Type", "application/octet-stream")
		w.Write(ct)
	}
}

func rawAuthH(s *sA) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			jw(w, 405, map[string]string{"error": "method"})
			return
		}
		ct, err := io.ReadAll(r.Body)
		if err != nil || len(ct) == 0 {
			jw(w, 400, map[string]string{"error": "body"})
			return
		}
		p := pv(string(s.d(ct)))
		if p == nil {
			jw(w, 400, map[string]string{"error": "format"})
			return
		}
		if p["role"] == "admin" {
			jw(w, 200, map[string]string{"flag": s.fl})
		} else {
			jw(w, 403, map[string]string{"error": "denied", "role": p["role"]})
		}
	}
}

func sesH(enc func([]byte) []byte) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			jw(w, 405, map[string]string{"error": "method"})
			return
		}
		ct := enc([]byte(pt()))
		jw(w, 200, map[string]string{"token": hex.EncodeToString(ct)})
	}
}

func authHB(s *sB) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			jw(w, 405, map[string]string{"error": "method"})
			return
		}
		var rq map[string]string
		if err := json.NewDecoder(r.Body).Decode(&rq); err != nil {
			jw(w, 400, map[string]string{"error": "json"})
			return
		}
		ct, err := hex.DecodeString(rq["token"])
		if err != nil {
			jw(w, 400, map[string]string{"error": "hex"})
			return
		}
		if len(ct) < 2*BS || len(ct)%BS != 0 {
			jw(w, 400, map[string]string{"error": "length"})
			return
		}
		p, err := s.d(ct)
		if err != nil {
			jw(w, 500, map[string]string{"error": "decrypt"})
			return
		}
		m := pv(string(p))
		if m == nil {
			jw(w, 400, map[string]string{"error": "format"})
			return
		}
		if m["role"] == "admin" {
			jw(w, 200, map[string]string{"flag": s.fl})
		} else {
			jw(w, 403, map[string]string{"error": "denied"})
		}
	}
}

func authHC(s *sC) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			jw(w, 405, map[string]string{"error": "method"})
			return
		}
		var rq map[string]string
		if err := json.NewDecoder(r.Body).Decode(&rq); err != nil {
			jw(w, 400, map[string]string{"error": "json"})
			return
		}
		ct, err := hex.DecodeString(rq["token"])
		if err != nil {
			jw(w, 400, map[string]string{"error": "hex"})
			return
		}
		p, err := s.d(ct)
		if err != nil {
			jw(w, 400, map[string]string{"error": "auth"})
			return
		}
		m := pv(string(p))
		if m == nil {
			jw(w, 400, map[string]string{"error": "format"})
			return
		}
		if m["role"] == "admin" {
			jw(w, 200, map[string]string{"flag": s.fl})
		} else {
			jw(w, 403, map[string]string{"error": "denied"})
		}
	}
}

func hH(w http.ResponseWriter, r *http.Request) {
	jw(w, 200, map[string]string{"status": "ok"})
}

func wv(port int, flag string, mb []byte) {
	dir := "/var/run/svc"
	os.MkdirAll(dir, 0755)
	fh := sha256.Sum256([]byte(flag))
	os.WriteFile(fmt.Sprintf("%s/%d.fh", dir, port), []byte(hex.EncodeToString(fh[:])), 0644)
	mode := make([]byte, len(mb))
	copy(mode, mb)
	mac := hmac.New(sha256.New, []byte(flag))
	mac.Write(mode)
	os.WriteFile(fmt.Sprintf("%s/%d.mm", dir, port), []byte(hex.EncodeToString(mac.Sum(nil))), 0644)
}

func main() {
	a := nA()
	b := nB()
	c := nC()

	wv(5001, a.fl, []byte{99, 116, 114})
	wv(5002, b.fl, []byte{99, 98, 99})
	wv(5003, c.fl, []byte{103, 99, 109})

	m1 := http.NewServeMux()
	m1.HandleFunc("/api/session", rawSesH(a.e))
	m1.HandleFunc("/api/auth", rawAuthH(a))
	m1.HandleFunc("/api/health", hH)

	m2 := http.NewServeMux()
	m2.HandleFunc("/api/session", sesH(b.e))
	m2.HandleFunc("/api/auth", authHB(b))
	m2.HandleFunc("/api/health", hH)

	m3 := http.NewServeMux()
	m3.HandleFunc("/api/session", sesH(c.e))
	m3.HandleFunc("/api/auth", authHC(c))
	m3.HandleFunc("/api/health", hH)

	var wg sync.WaitGroup
	wg.Add(3)

	go func() {
		defer wg.Done()
		log.Fatal(http.ListenAndServe(":5001", m1))
	}()
	go func() {
		defer wg.Done()
		log.Fatal(http.ListenAndServe(":5002", m2))
	}()
	go func() {
		defer wg.Done()
		srv := &http.Server{
			Addr:    ":5003",
			Handler: m3,
			TLSConfig: &tls.Config{
				MinVersion: tls.VersionTLS12,
			},
		}
		log.Fatal(srv.ListenAndServeTLS("/app/certs/server.crt", "/app/certs/server.key"))
	}()

	log.Println("Services ready: 5001 (binary), 5002 (HTTP), 5003 (HTTPS)")
	wg.Wait()
}
