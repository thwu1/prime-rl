package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
)

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintf(os.Stderr, "Usage: asmcheck [--json] <file.asm>\n")
		fmt.Fprintf(os.Stderr, "       asmcheck --help\n")
		os.Exit(1)
	}

	jsonOut := false
	file := ""

	for i := 1; i < len(os.Args); i++ {
		switch os.Args[i] {
		case "--help", "-h":
			printHelp()
			return
		case "--json":
			jsonOut = true
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

	analyze(file, jsonOut)
}

func printHelp() {
	help := `asmcheck - Static analysis tool for VM assembly programs

Usage:
  asmcheck <file.asm>         Analyze an assembly program (text output)
  asmcheck --json <file.asm>  Analyze and output results as JSON
  asmcheck --help             Show this help message

Analysis reports:
  - Static instruction count (non-blank, non-comment, non-LABEL lines)
  - Opcode frequency histogram
  - Variable definition and use counts with annotations:
      [MULTI-DEF]   variable is assigned in more than one location
      [DEAD-STORE]  variable is assigned but never read
      [WRITE-ONLY]  same as DEAD-STORE
  - Control flow: labels, jump targets, unused labels
  - Warnings for variables with multiple definitions or zero uses

JSON output (--json) includes all fields in machine-readable format
suitable for programmatic consumption.

Exit codes:
  0   Successful analysis
  1   Error (file not found, usage error)`
	fmt.Println(help)
}

type VarInfo struct {
	Definitions int `json:"definitions"`
	Uses        int `json:"uses"`
}

type Analysis struct {
	File            string         `json:"file"`
	StaticCount     int            `json:"static_instruction_count"`
	TotalLines      int            `json:"total_parsed_lines"`
	OpcodeHistogram map[string]int `json:"opcode_histogram"`
	Variables       map[string]VarInfo `json:"variables"`
	Labels          []string       `json:"labels"`
	JumpTargets     []string       `json:"jump_targets"`
	UnusedLabels    []string       `json:"unused_labels,omitempty"`
	DeadStoreVars   []string       `json:"potential_dead_stores,omitempty"`
	MultiDefVars    []string       `json:"multi_definition_variables,omitempty"`
}

func analyze(path string, jsonOut bool) {
	f, err := os.Open(path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	defer f.Close()

	type Insn struct {
		Op  string
		Arg string
	}

	var insns []Insn
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
		insns = append(insns, Insn{op, arg})
	}

	a := Analysis{
		File:            path,
		OpcodeHistogram: map[string]int{},
		Variables:       map[string]VarInfo{},
		TotalLines:      len(insns),
	}

	jumpTargetSet := map[string]bool{}

	for _, insn := range insns {
		if insn.Op != "LABEL" {
			a.StaticCount++
		}
		a.OpcodeHistogram[insn.Op]++

		switch insn.Op {
		case "STORE":
			if insn.Arg != "" {
				vi := a.Variables[insn.Arg]
				vi.Definitions++
				a.Variables[insn.Arg] = vi
			}
		case "LOAD":
			if insn.Arg != "" {
				vi := a.Variables[insn.Arg]
				vi.Uses++
				a.Variables[insn.Arg] = vi
			}
		case "LABEL":
			if insn.Arg != "" {
				a.Labels = append(a.Labels, insn.Arg)
			}
		case "JUMP", "JUMP_TRUE", "JUMP_FALSE":
			if insn.Arg != "" {
				if !jumpTargetSet[insn.Arg] {
					a.JumpTargets = append(a.JumpTargets, insn.Arg)
					jumpTargetSet[insn.Arg] = true
				}
			}
		}
	}

	labelSet := map[string]bool{}
	for _, l := range a.Labels {
		labelSet[l] = true
	}
	for _, l := range a.Labels {
		if !jumpTargetSet[l] {
			a.UnusedLabels = append(a.UnusedLabels, l)
		}
	}

	for name, vi := range a.Variables {
		if vi.Definitions > 0 && vi.Uses == 0 {
			a.DeadStoreVars = append(a.DeadStoreVars, name)
		}
		if vi.Definitions > 1 {
			a.MultiDefVars = append(a.MultiDefVars, name)
		}
	}
	sort.Strings(a.DeadStoreVars)
	sort.Strings(a.MultiDefVars)

	if jsonOut {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		enc.Encode(a)
	} else {
		printText(a)
	}
}

func printText(a Analysis) {
	fmt.Printf("File: %s\n", a.File)
	fmt.Printf("Static instruction count: %d\n", a.StaticCount)
	fmt.Printf("Total parsed lines (including LABEL): %d\n\n", a.TotalLines)

	fmt.Println("Opcode histogram:")
	var ops []string
	for op := range a.OpcodeHistogram {
		ops = append(ops, op)
	}
	sort.Strings(ops)
	for _, op := range ops {
		fmt.Printf("  %-14s %d\n", op, a.OpcodeHistogram[op])
	}

	fmt.Println("\nVariable analysis:")
	var vars []string
	for v := range a.Variables {
		vars = append(vars, v)
	}
	sort.Strings(vars)
	for _, v := range vars {
		vi := a.Variables[v]
		fmt.Printf("  %-14s %d def(s), %d use(s)", v, vi.Definitions, vi.Uses)
		if vi.Definitions > 1 {
			fmt.Print("  [MULTI-DEF]")
		}
		if vi.Uses == 0 {
			fmt.Print("  [DEAD-STORE]")
		}
		fmt.Println()
	}

	if len(a.Labels) > 0 {
		fmt.Printf("\nLabels: %s\n", strings.Join(a.Labels, ", "))
	} else {
		fmt.Println("\nLabels: (none)")
	}

	if len(a.JumpTargets) > 0 {
		fmt.Printf("Jump targets: %s\n", strings.Join(a.JumpTargets, ", "))
	}

	if len(a.UnusedLabels) > 0 {
		fmt.Printf("\nWarning: unused labels: %s\n", strings.Join(a.UnusedLabels, ", "))
	}

	if len(a.MultiDefVars) > 0 {
		fmt.Printf("Warning: variables with multiple definitions: %s\n",
			strings.Join(a.MultiDefVars, ", "))
	}

	if len(a.DeadStoreVars) > 0 {
		fmt.Printf("Warning: variables assigned but never read: %s\n",
			strings.Join(a.DeadStoreVars, ", "))
	}
}
