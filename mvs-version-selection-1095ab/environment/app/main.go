package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"
)

// Version represents a module version as a Path + Version pair.
type Version struct {
	Path    string
	Version string
}

func (v Version) String() string {
	return v.Path + v.Version
}

// Graph holds the module requirement graph.
type Graph struct {
	reqs map[Version][]Version
}

func NewGraph() *Graph {
	return &Graph{reqs: make(map[Version][]Version)}
}

func (g *Graph) AddRequirement(m Version, deps []Version) {
	g.reqs[m] = deps
	for _, d := range deps {
		if _, ok := g.reqs[d]; !ok {
			g.reqs[d] = []Version{}
		}
	}
}

// Required returns the module versions explicitly required by m.
func (g *Graph) Required(m Version) ([]Version, error) {
	if deps, ok := g.reqs[m]; ok {
		return deps, nil
	}
	return nil, fmt.Errorf("missing module: %v", m)
}

// Max returns the maximum of v1 and v2 for path p.
// "none" is less than everything; "" (empty, used for target) is greater than everything.
func (g *Graph) Max(p, v1, v2 string) string {
	if v1 == "none" || v2 == "" {
		return v2
	}
	if v2 == "none" || v1 == "" {
		return v1
	}
	if v1 < v2 {
		return v2
	}
	return v1
}

// Upgrade returns the highest non-hidden version for the given module path.
func (g *Graph) Upgrade(m Version) (Version, error) {
	u := Version{Version: "none"}
	for k := range g.reqs {
		if k.Path == m.Path && g.Max(k.Path, u.Version, k.Version) == k.Version && !strings.HasSuffix(k.Version, ".hidden") {
			u = k
		}
	}
	if u.Path == "" {
		return Version{}, fmt.Errorf("missing module: %s", m.Path)
	}
	return u, nil
}

// Previous returns the version of m.Path immediately prior to m.Version,
// skipping hidden versions. Returns version "none" if no such version exists.
func (g *Graph) Previous(m Version) (Version, error) {
	var p Version
	for k := range g.reqs {
		if k.Path == m.Path && p.Version < k.Version && k.Version < m.Version && !strings.HasSuffix(k.Version, ".hidden") {
			p = k
		}
	}
	if p.Path == "" {
		return Version{Path: m.Path, Version: "none"}, nil
	}
	return p, nil
}

// ParseVersion parses a module version string where path is the first character.
func ParseVersion(s string) Version {
	return Version{Path: s[:1], Version: s[1:]}
}

// ParseGraph reads a graph file and returns a Graph.
func ParseGraph(filename string) (*Graph, error) {
	f, err := os.Open(filename)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	g := NewGraph()
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		parts := strings.SplitN(line, ":", 2)
		if len(parts) != 2 {
			continue
		}
		m := ParseVersion(strings.TrimSpace(parts[0]))
		var deps []Version
		fields := strings.Fields(strings.TrimSpace(parts[1]))
		for _, d := range fields {
			deps = append(deps, ParseVersion(d))
		}
		g.AddRequirement(m, deps)
	}
	return g, scanner.Err()
}

func main() {
	if len(os.Args) < 3 {
		fmt.Fprintf(os.Stderr, "Usage: mvs <graph-file> <command> [args...]\n")
		os.Exit(1)
	}

	graphFile := os.Args[1]
	command := os.Args[2]

	g, err := ParseGraph(graphFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error parsing graph: %v\n", err)
		os.Exit(1)
	}

	var result []Version

	switch command {
	case "build":
		if len(os.Args) != 4 {
			fmt.Fprintf(os.Stderr, "Usage: mvs <graph-file> build <target>\n")
			os.Exit(1)
		}
		target := ParseVersion(os.Args[3])
		result, err = BuildList(g, target)

	case "upgrade-all":
		if len(os.Args) != 4 {
			fmt.Fprintf(os.Stderr, "Usage: mvs <graph-file> upgrade-all <target>\n")
			os.Exit(1)
		}
		target := ParseVersion(os.Args[3])
		result, err = UpgradeAll(g, target)

	case "upgrade":
		if len(os.Args) < 5 {
			fmt.Fprintf(os.Stderr, "Usage: mvs <graph-file> upgrade <target> <mod1> [mod2...]\n")
			os.Exit(1)
		}
		target := ParseVersion(os.Args[3])
		var upgrades []Version
		for _, a := range os.Args[4:] {
			upgrades = append(upgrades, ParseVersion(a))
		}
		result, err = Upgrade(g, target, upgrades...)

	case "downgrade":
		if len(os.Args) < 4 {
			fmt.Fprintf(os.Stderr, "Usage: mvs <graph-file> downgrade <target> [mod1...]\n")
			os.Exit(1)
		}
		allArgs := os.Args[3:]
		target := ParseVersion(allArgs[0])
		var downgrades []Version
		for _, a := range allArgs {
			downgrades = append(downgrades, ParseVersion(a))
		}
		result, err = Downgrade(g, target, downgrades...)

	case "req":
		if len(os.Args) < 4 {
			fmt.Fprintf(os.Stderr, "Usage: mvs <graph-file> req <target> [base1 base2...]\n")
			os.Exit(1)
		}
		target := ParseVersion(os.Args[3])
		var base []string
		for _, a := range os.Args[4:] {
			base = append(base, a)
		}
		result, err = Req(g, target, base)

	default:
		fmt.Fprintf(os.Stderr, "Unknown command: %s\n", command)
		os.Exit(1)
	}

	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	strs := make([]string, len(result))
	for i, v := range result {
		strs[i] = v.String()
	}
	fmt.Println(strings.Join(strs, " "))
}
