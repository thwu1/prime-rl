// Go implementations of Mugo builtin functions.
// These are used when compiling mugo.go with the Go compiler.
// When Mugo compiles programs, it generates assembly for these builtins.

package main

import "os"

func print(s string) {
	os.Stdout.WriteString(s)
}

func log(s string) {
	os.Stderr.WriteString(s)
}

func getc() int {
	b := make([]byte, 1)
	n, _ := os.Stdin.Read(b)
	if n == 0 {
		return -1
	}
	return int(b[0])
}

func exit(code int) {
	os.Exit(code)
}

func char(n int) string {
	return string(rune(n))
}
