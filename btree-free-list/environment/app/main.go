package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "Usage: kvtool <dbfile> [command args...]\n")
		fmt.Fprintf(os.Stderr, "Commands:\n")
		fmt.Fprintf(os.Stderr, "  set <key> <value>  - insert or update a key\n")
		fmt.Fprintf(os.Stderr, "  get <key>          - retrieve a value\n")
		fmt.Fprintf(os.Stderr, "  del <key>          - delete a key\n")
		fmt.Fprintf(os.Stderr, "  scan               - list all key-value pairs\n")
		fmt.Fprintf(os.Stderr, "  stats              - show database statistics\n")
		fmt.Fprintf(os.Stderr, "Without a command, reads commands from stdin (batch mode).\n")
		os.Exit(1)
	}

	db := &KV{Path: os.Args[1]}
	if err := db.Open(); err != nil {
		fmt.Fprintf(os.Stderr, "Error opening DB: %v\n", err)
		os.Exit(1)
	}
	defer db.Close()

	if len(os.Args) >= 3 {
		runCommand(db, os.Args[2:])
	} else {
		scanner := bufio.NewScanner(os.Stdin)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" {
				continue
			}
			args := strings.Fields(line)
			runCommand(db, args)
		}
	}
}

func runCommand(db *KV, args []string) {
	if len(args) == 0 {
		return
	}
	switch args[0] {
	case "set":
		if len(args) < 3 {
			fmt.Println("ERR: set requires key and value")
			return
		}
		if err := db.Set([]byte(args[1]), []byte(args[2])); err != nil {
			fmt.Printf("ERR: %v\n", err)
			return
		}
		fmt.Println("OK")
	case "get":
		if len(args) < 2 {
			fmt.Println("ERR: get requires key")
			return
		}
		val, ok := db.Get([]byte(args[1]))
		if ok {
			fmt.Println(string(val))
		} else {
			fmt.Println("NOT_FOUND")
		}
	case "del":
		if len(args) < 2 {
			fmt.Println("ERR: del requires key")
			return
		}
		deleted, err := db.Del([]byte(args[1]))
		if err != nil {
			fmt.Printf("ERR: %v\n", err)
			return
		}
		if deleted {
			fmt.Println("DELETED")
		} else {
			fmt.Println("NOT_FOUND")
		}
	case "scan":
		db.Scan(func(key, val []byte) {
			fmt.Printf("%s=%s\n", string(key), string(val))
		})
	case "stats":
		fi, _ := db.fp.Stat()
		fmt.Printf("file_size=%d\n", fi.Size())
		fmt.Printf("pages_used=%d\n", db.PageCount())
	default:
		fmt.Printf("ERR: unknown command %q\n", args[0])
	}
}
