package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "Usage: gowal <generate|verify>\n")
		os.Exit(1)
	}

	switch os.Args[1] {
	case "generate":
		genCmd := flag.NewFlagSet("generate", flag.ExitOnError)
		dir := genCmd.String("dir", "", "output directory for WAL data")
		genCmd.Parse(os.Args[2:])
		if *dir == "" {
			fmt.Fprintln(os.Stderr, "--dir is required")
			os.Exit(1)
		}
		generate(*dir)

	case "verify":
		verCmd := flag.NewFlagSet("verify", flag.ExitOnError)
		dir := verCmd.String("dir", "", "WAL directory to verify")
		verCmd.Parse(os.Args[2:])
		if *dir == "" {
			fmt.Fprintln(os.Stderr, "--dir is required")
			os.Exit(1)
		}
		verify(*dir)

	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", os.Args[1])
		os.Exit(1)
	}
}

func generate(dir string) {
	os.MkdirAll(dir, 0755)
	w := NewWALWriter(dir, 20)

	for i := 1; i <= 100; i++ {
		var payload string
		if i%10 == 0 {
			payload = fmt.Sprintf("DEL key_%d", i-5)
		} else {
			payload = fmt.Sprintf("SET key_%d val_%d", i, i)
		}
		term := uint64(1)
		if i > 40 {
			term = 2
		}
		ts := int64(1700000000000000000) + int64(i)*1000000
		w.Append(Entry{
			Index:     uint64(i),
			Term:      term,
			Timestamp: ts,
			Payload:   []byte(payload),
		})
	}
	if err := w.Flush(); err != nil {
		fmt.Fprintf(os.Stderr, "flush error: %v\n", err)
		os.Exit(1)
	}

	state := make(map[string]string)
	for i := 1; i <= 40; i++ {
		if i%10 == 0 {
			delete(state, fmt.Sprintf("key_%d", i-5))
		} else {
			state[fmt.Sprintf("key_%d", i)] = fmt.Sprintf("val_%d", i)
		}
	}
	if err := w.WriteSnapshot(40, 1, state); err != nil {
		fmt.Fprintf(os.Stderr, "snapshot error: %v\n", err)
		os.Exit(1)
	}
	w.CompactBefore(40)

	fmt.Println("WAL data generated successfully")
}

func verify(dir string) {
	matches, _ := filepath.Glob(filepath.Join(dir, "segment_*.wal"))
	sort.Strings(matches)

	allOK := true
	for _, path := range matches {
		entries, err := readSegmentEntries(path)
		if err != nil {
			fmt.Printf("CORRUPT %s: %v\n", filepath.Base(path), err)
			allOK = false
		} else {
			first := entries[0].Index
			last := entries[len(entries)-1].Index
			fmt.Printf("OK      %s: %d entries [%d..%d]\n",
				filepath.Base(path), len(entries), first, last)
		}
	}

	snap, err := ReadSnapshot(dir)
	if err != nil {
		fmt.Printf("CORRUPT snapshot: %v\n", err)
		allOK = false
	} else if snap != nil {
		fmt.Printf("OK      snapshot: through index %d (term %d), %d keys\n",
			snap.LastIndex, snap.LastTerm, len(snap.State))
	} else {
		fmt.Println("        no snapshot found")
	}

	if allOK {
		fmt.Println("\nAll files verified OK")
	} else {
		fmt.Println("\nCorruption detected")
		os.Exit(1)
	}
}
