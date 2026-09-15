package main

/*
 * Go round-trip verifier for the float serialization pipeline.
 * Reads /app/results.json and checks that every "shortest" string
 * parses back to the exact same IEEE 754 double using strconv.ParseFloat.
 *
 * Build: go build -o verify verify.go
 * Run:   ./verify
 */


import (
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"strconv"
)

type Entry struct {
	ID       int    `json:"id"`
	HexBits  string `json:"hex_bits"`
	Category string `json:"category"`
	Shortest string `json:"shortest"`
	Notation string `json:"notation"`
}

type Output struct {
	Results []Entry                `json:"results"`
	Summary map[string]interface{} `json:"summary"`
}

func main() {
	data, err := os.ReadFile("/app/results.json")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Cannot read /app/results.json: %v\n", err)
		os.Exit(1)
	}

	var output Output
	if err := json.Unmarshal(data, &output); err != nil {
		fmt.Fprintf(os.Stderr, "Invalid JSON in results.json: %v\n", err)
		os.Exit(1)
	}

	if len(output.Results) == 0 {
		fmt.Fprintf(os.Stderr, "No results found in results.json\n")
		os.Exit(1)
	}

	failures := 0
	for _, e := range output.Results {
		bs, err := hex.DecodeString(e.HexBits)
		if err != nil || len(bs) != 8 {
			fmt.Fprintf(os.Stderr, "ID %d: invalid hex_bits '%s'\n", e.ID, e.HexBits)
			failures++
			continue
		}
		bits := binary.BigEndian.Uint64(bs)
		original := math.Float64frombits(bits)

		// NaN: just check the string is "NaN"
		if math.IsNaN(original) {
			if e.Shortest != "NaN" {
				fmt.Fprintf(os.Stderr, "ID %d [%s]: NaN expected 'NaN', got '%s'\n",
					e.ID, e.Category, e.Shortest)
				failures++
			}
			continue
		}

		// Parse the shortest string using Go's strconv
		parsed, err := strconv.ParseFloat(e.Shortest, 64)
		if err != nil {
			fmt.Fprintf(os.Stderr, "ID %d [%s]: cannot parse '%s': %v\n",
				e.ID, e.Category, e.Shortest, err)
			failures++
			continue
		}

		parsedBits := math.Float64bits(parsed)
		if parsedBits != bits {
			fmt.Fprintf(os.Stderr, "ID %d [%s]: '%s' -> %016X, expected %s\n",
				e.ID, e.Category, e.Shortest, parsedBits, e.HexBits)
			failures++
		}
	}

	if failures > 0 {
		fmt.Fprintf(os.Stderr, "\nFAIL: %d of %d entries failed round-trip verification\n",
			failures, len(output.Results))
		os.Exit(1)
	}
	fmt.Printf("PASS: all %d entries verified (bit-exact round-trip via strconv.ParseFloat)\n",
		len(output.Results))
}
