package main


import (
	"fmt"
	"io/ioutil"
	"os"
	"strings"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "Usage: bfvm [-dump] <file.b>\n")
		os.Exit(1)
	}

	dump := false
	fileName := ""
	for _, arg := range os.Args[1:] {
		if arg == "-dump" {
			dump = true
		} else {
			fileName = arg
		}
	}

	if fileName == "" {
		fmt.Fprintf(os.Stderr, "Usage: bfvm [-dump] <file.b>\n")
		os.Exit(1)
	}

	code, err := ioutil.ReadFile(fileName)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %s\n", err)
		os.Exit(1)
	}

	// Strip non-BF characters for cleaner compilation
	cleaned := stripNonBF(string(code))

	compiler := NewCompiler(cleaned)
	instructions := compiler.Compile()

	if dump {
		for i, ins := range instructions {
			name := InsTypeName(ins.Type)
			fmt.Printf("%04d: %s %d\n", i, name, ins.Argument)
		}
		return
	}

	m := NewMachine(instructions, os.Stdin, os.Stdout)
	m.Execute()
}

func stripNonBF(s string) string {
	var b strings.Builder
	for _, c := range s {
		switch c {
		case '+', '-', '<', '>', '[', ']', '.', ',':
			b.WriteRune(c)
		}
	}
	return b.String()
}
