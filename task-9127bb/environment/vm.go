package main

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
)

type Value struct {
	IsStr bool
	Num   int64
	Str   string
}

func (v Value) String() string {
	if v.IsStr {
		return fmt.Sprintf("%q", v.Str)
	}
	return strconv.FormatInt(v.Num, 10)
}

type Insn struct {
	Op  string
	Arg string
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "Usage: vm [--trace] <file.asm>\n")
		fmt.Fprintf(os.Stderr, "       vm --help\n")
		os.Exit(1)
	}

	trace := false
	file := ""

	for i := 1; i < len(os.Args); i++ {
		switch os.Args[i] {
		case "--help", "-h":
			printHelp()
			return
		case "--trace":
			trace = true
		default:
			if file != "" {
				fmt.Fprintf(os.Stderr, "Error: unexpected argument: %s\n", os.Args[i])
				os.Exit(1)
			}
			file = os.Args[i]
		}
	}

	if file == "" {
		fmt.Fprintf(os.Stderr, "Error: no input file specified\n")
		os.Exit(1)
	}

	insns, labels := load(file)
	run(insns, labels, trace)
}

func printHelp() {
	help := `vm - Stack-based virtual machine

Usage:
  vm <file.asm>              Execute an assembly program
  vm --trace <file.asm>      Execute with instruction-level tracing
  vm --help                  Show this help message

Tracing:
  When --trace is enabled, each instruction is logged to stderr before
  execution, showing the program counter, instruction, and current stack
  state. A summary of total instructions executed is printed at the end.
  Program output (stdout) is unaffected by tracing.

  Trace format per line:
    [pc] INSTRUCTION              stack: [values...]

  At end of execution:
    --- N instructions executed ---

Exit codes:
  0   Successful execution (HALT reached or end of program)
  1   Error (file not found, parse error, runtime error)`
	fmt.Println(help)
}

func load(path string) ([]Insn, map[string]int) {
	f, err := os.Open(path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	defer f.Close()

	var insns []Insn
	labels := map[string]int{}
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		parts := strings.SplitN(line, " ", 2)
		op := parts[0]
		arg := ""
		if len(parts) > 1 {
			arg = parts[1]
		}
		if op == "LABEL" {
			labels[arg] = len(insns)
		}
		insns = append(insns, Insn{Op: op, Arg: arg})
	}
	return insns, labels
}

func formatStack(stack []Value) string {
	if len(stack) == 0 {
		return "[]"
	}
	parts := make([]string, len(stack))
	for i, v := range stack {
		parts[i] = v.String()
	}
	return "[" + strings.Join(parts, ", ") + "]"
}

func run(insns []Insn, labels map[string]int, trace bool) {
	var stack []Value
	vars := map[string]Value{}
	reader := bufio.NewReader(os.Stdin)
	pc := 0
	traceCount := 0

	push := func(v Value) {
		stack = append(stack, v)
	}

	pop := func() Value {
		if len(stack) == 0 {
			fmt.Fprintf(os.Stderr, "Stack underflow at pc=%d\n", pc)
			os.Exit(1)
		}
		v := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		return v
	}

	for pc < len(insns) {
		insn := insns[pc]

		if trace {
			insnStr := insn.Op
			if insn.Arg != "" {
				insnStr += " " + insn.Arg
			}
			fmt.Fprintf(os.Stderr, "[%3d] %-25s stack: %s\n",
				pc, insnStr, formatStack(stack))
			traceCount++
		}

		switch insn.Op {
		case "LABEL":
			pc++
		case "PUSH_INT":
			n, _ := strconv.ParseInt(insn.Arg, 10, 64)
			push(Value{Num: n})
			pc++
		case "PUSH_STR":
			push(Value{IsStr: true, Str: insn.Arg})
			pc++
		case "LOAD":
			v, ok := vars[insn.Arg]
			if !ok {
				fmt.Fprintf(os.Stderr, "Undefined variable: %s at pc=%d\n", insn.Arg, pc)
				os.Exit(1)
			}
			push(v)
			pc++
		case "STORE":
			vars[insn.Arg] = pop()
			pc++
		case "DROP":
			pop()
			pc++
		case "DUP":
			v := pop()
			push(v)
			push(v)
			pc++
		case "SWAP":
			b, a := pop(), pop()
			push(b)
			push(a)
			pc++
		case "ADD":
			b, a := pop(), pop()
			push(Value{Num: a.Num + b.Num})
			pc++
		case "SUB":
			b, a := pop(), pop()
			push(Value{Num: a.Num - b.Num})
			pc++
		case "MUL":
			b, a := pop(), pop()
			push(Value{Num: a.Num * b.Num})
			pc++
		case "DIV":
			b, a := pop(), pop()
			if b.Num == 0 {
				fmt.Fprintf(os.Stderr, "Division by zero at pc=%d\n", pc)
				os.Exit(1)
			}
			push(Value{Num: a.Num / b.Num})
			pc++
		case "MOD":
			b, a := pop(), pop()
			if b.Num == 0 {
				fmt.Fprintf(os.Stderr, "Modulo by zero at pc=%d\n", pc)
				os.Exit(1)
			}
			push(Value{Num: a.Num % b.Num})
			pc++
		case "NEG":
			v := pop()
			push(Value{Num: -v.Num})
			pc++
		case "NOT":
			v := pop()
			if v.Num == 0 {
				push(Value{Num: 1})
			} else {
				push(Value{Num: 0})
			}
			pc++
		case "CMP_EQ":
			b, a := pop(), pop()
			if a.Num == b.Num {
				push(Value{Num: 1})
			} else {
				push(Value{Num: 0})
			}
			pc++
		case "CMP_NE":
			b, a := pop(), pop()
			if a.Num != b.Num {
				push(Value{Num: 1})
			} else {
				push(Value{Num: 0})
			}
			pc++
		case "CMP_LT":
			b, a := pop(), pop()
			if a.Num < b.Num {
				push(Value{Num: 1})
			} else {
				push(Value{Num: 0})
			}
			pc++
		case "CMP_LE":
			b, a := pop(), pop()
			if a.Num <= b.Num {
				push(Value{Num: 1})
			} else {
				push(Value{Num: 0})
			}
			pc++
		case "CMP_GT":
			b, a := pop(), pop()
			if a.Num > b.Num {
				push(Value{Num: 1})
			} else {
				push(Value{Num: 0})
			}
			pc++
		case "CMP_GE":
			b, a := pop(), pop()
			if a.Num >= b.Num {
				push(Value{Num: 1})
			} else {
				push(Value{Num: 0})
			}
			pc++
		case "PRINT":
			v := pop()
			if v.IsStr {
				fmt.Print(v.Str)
			} else {
				fmt.Print(v.Num)
			}
			pc++
		case "PRINTLN":
			v := pop()
			if v.IsStr {
				fmt.Println(v.Str)
			} else {
				fmt.Println(v.Num)
			}
			pc++
		case "READ_INT":
			line, err := reader.ReadString('\n')
			if err != nil && line == "" {
				fmt.Fprintf(os.Stderr, "Read error: %v\n", err)
				os.Exit(1)
			}
			line = strings.TrimSpace(line)
			n, err := strconv.ParseInt(line, 10, 64)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Invalid integer input: %s\n", line)
				os.Exit(1)
			}
			push(Value{Num: n})
			pc++
		case "JUMP":
			idx, ok := labels[insn.Arg]
			if !ok {
				fmt.Fprintf(os.Stderr, "Unknown label: %s at pc=%d\n", insn.Arg, pc)
				os.Exit(1)
			}
			pc = idx
		case "JUMP_TRUE":
			v := pop()
			if v.Num != 0 {
				pc = labels[insn.Arg]
			} else {
				pc++
			}
		case "JUMP_FALSE":
			v := pop()
			if v.Num == 0 {
				pc = labels[insn.Arg]
			} else {
				pc++
			}
		case "HALT":
			if trace {
				fmt.Fprintf(os.Stderr, "\n--- %d instructions executed ---\n", traceCount)
			}
			return
		default:
			fmt.Fprintf(os.Stderr, "Unknown instruction: %s at pc=%d\n", insn.Op, pc)
			os.Exit(1)
		}
	}

	if trace {
		fmt.Fprintf(os.Stderr, "\n--- %d instructions executed ---\n", traceCount)
	}
}
