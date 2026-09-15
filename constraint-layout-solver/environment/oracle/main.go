package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sort"
)

type rect struct {
	X      int `json:"x"`
	Y      int `json:"y"`
	Width  int `json:"width"`
	Height int `json:"height"`
}

type constraint struct {
	kind   string
	value  int
	weight int
	num    int
	den    int
	inner  *constraint
}

func parseConstraint(raw json.RawMessage) constraint {
	var m map[string]json.RawMessage
	json.Unmarshal(raw, &m)
	var kind string
	json.Unmarshal(m["type"], &kind)
	c := constraint{kind: kind}
	switch kind {
	case "Length", "Percentage":
		json.Unmarshal(m["value"], &c.value)
	case "Ratio":
		json.Unmarshal(m["numerator"], &c.num)
		json.Unmarshal(m["denominator"], &c.den)
	case "Fill":
		c.weight = 1
		if w, ok := m["weight"]; ok {
			json.Unmarshal(w, &c.weight)
		}
	case "Min", "Max":
		json.Unmarshal(m["value"], &c.value)
		if innerRaw, ok := m["inner"]; ok {
			inner := parseConstraint(innerRaw)
			c.inner = &inner
		}
	}
	return c
}

func unwrapBounds(c constraint, usable int) (int, int, constraint) {
	lo, hi := 0, usable
	cur := c
	for (cur.kind == "Min" || cur.kind == "Max") && cur.inner != nil {
		if cur.kind == "Min" {
			if cur.value > lo {
				lo = cur.value
			}
		} else {
			if cur.value < hi {
				hi = cur.value
			}
		}
		cur = *cur.inner
	}
	if lo > hi {
		hi = lo
	}
	return lo, hi, cur
}

func resolveBase(c constraint, usable int) int {
	switch c.kind {
	case "Length":
		return c.value
	case "Percentage":
		return usable * c.value / 100
	case "Ratio":
		if c.den == 0 {
			return 0
		}
		return usable * c.num / c.den
	}
	return 0
}

type remEntry struct {
	r float64
	i int
}

func distribute(total int, weights []int) []int {
	k := len(weights)
	if k == 0 {
		return nil
	}
	tw := 0
	for _, w := range weights {
		tw += w
	}
	if tw == 0 {
		each := total / k
		extra := total - each*k
		out := make([]int, k)
		for i := range out {
			out[i] = each
			if i < extra {
				out[i]++
			}
		}
		return out
	}
	exact := make([]float64, k)
	fl := make([]int, k)
	for i, w := range weights {
		exact[i] = float64(total) * float64(w) / float64(tw)
		fl[i] = int(exact[i])
	}
	deficit := total
	for _, f := range fl {
		deficit -= f
	}
	ent := make([]remEntry, k)
	for i := range ent {
		ent[i] = remEntry{exact[i] - float64(fl[i]), i}
	}
	sort.SliceStable(ent, func(a, b int) bool {
		if ent[a].r != ent[b].r {
			return ent[a].r > ent[b].r
		}
		return ent[a].i < ent[b].i
	})
	bonus := make(map[int]bool)
	for j := 0; j < deficit && j < k; j++ {
		bonus[ent[j].i] = true
	}
	out := make([]int, k)
	for i := range out {
		out[i] = fl[i]
		if bonus[i] {
			out[i]++
		}
	}
	return out
}

func clamp(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func solveSizes(usable int, cs []constraint) []int {
	n := len(cs)
	sz := make([]int, n)
	lo := make([]int, n)
	hi := make([]int, n)
	isF := make([]bool, n)
	fw := make([]int, n)
	for i := range cs {
		mn, mx, base := unwrapBounds(cs[i], usable)
		lo[i] = mn
		hi[i] = mx
		if base.kind == "Fill" {
			isF[i] = true
			w := base.weight
			if w < 0 {
				w = 0
			}
			fw[i] = w
		} else {
			sz[i] = clamp(resolveBase(base, usable), mn, mx)
		}
	}
	done := make([]bool, n)
	for i := range done {
		done[i] = !isF[i]
	}
	for iter := 0; iter < n+5; iter++ {
		used := 0
		for i := 0; i < n; i++ {
			if done[i] {
				used += sz[i]
			}
		}
		rem := usable - used
		if rem < 0 {
			rem = 0
		}
		var open []int
		for i := 0; i < n; i++ {
			if !done[i] {
				open = append(open, i)
			}
		}
		if len(open) == 0 {
			break
		}
		ws := make([]int, len(open))
		for j, i := range open {
			ws[j] = fw[i]
		}
		alloc := distribute(rem, ws)
		for j, i := range open {
			sz[i] = alloc[j]
		}
		changed := false
		for _, i := range open {
			cl := clamp(sz[i], lo[i], hi[i])
			if cl != sz[i] {
				sz[i] = cl
				done[i] = true
				changed = true
			}
		}
		if !changed {
			break
		}
	}
	tot := 0
	for _, s := range sz {
		tot += s
	}
	if tot > usable && tot > 0 {
		a := distribute(usable, sz)
		for i := range sz {
			sz[i] = a[i]
			if sz[i] < 0 {
				sz[i] = 0
			}
		}
	}
	for i := range sz {
		if sz[i] < 0 {
			sz[i] = 0
		}
	}
	return sz
}

func positions(sz []int, leftover, spacing int, flex string, n int) []int {
	if n == 0 {
		return nil
	}
	pos := make([]int, n)
	sp := func(i int) int {
		if i < n-1 {
			return spacing
		}
		return 0
	}
	switch {
	case flex == "START" || leftover <= 0:
		p := 0
		for i := 0; i < n; i++ {
			pos[i] = p
			p += sz[i] + sp(i)
		}
	case flex == "END":
		p := leftover
		for i := 0; i < n; i++ {
			pos[i] = p
			p += sz[i] + sp(i)
		}
	case flex == "CENTER":
		p := leftover / 2
		for i := 0; i < n; i++ {
			pos[i] = p
			p += sz[i] + sp(i)
		}
	case flex == "SPACE_BETWEEN":
		if n == 1 {
			pos[0] = 0
		} else {
			ge := leftover / (n - 1)
			gx := leftover % (n - 1)
			p := 0
			for i := 0; i < n; i++ {
				pos[i] = p
				if i < n-1 {
					e := 0
					if i < gx {
						e = 1
					}
					p += sz[i] + spacing + ge + e
				}
			}
		}
	}
	return pos
}

func doSplit(area rect, cs []constraint, dir string, spacing int, flex string) []rect {
	n := len(cs)
	if n == 0 {
		return []rect{}
	}
	if dir == "" {
		dir = "HORIZONTAL"
	}
	if flex == "" {
		flex = "START"
	}
	var totalSpace int
	if dir == "HORIZONTAL" {
		totalSpace = area.Width
	} else {
		totalSpace = area.Height
	}
	usable := totalSpace
	if n > 1 {
		usable -= (n - 1) * spacing
	}
	if usable < 0 {
		usable = 0
	}
	sz := solveSizes(usable, cs)
	used := 0
	for _, s := range sz {
		used += s
	}
	lo := usable - used
	if lo < 0 {
		lo = 0
	}
	pos := positions(sz, lo, spacing, flex, n)
	rects := make([]rect, n)
	for i := 0; i < n; i++ {
		if dir == "HORIZONTAL" {
			rects[i] = rect{area.X + pos[i], area.Y, sz[i], area.Height}
		} else {
			rects[i] = rect{area.X, area.Y + pos[i], area.Width, sz[i]}
		}
	}
	return rects
}

// --- Tree layout (compose mode) ---

type treeNode struct {
	Type            string            `json:"type"`
	Name            string            `json:"name,omitempty"`
	IntrinsicWidth  int               `json:"intrinsic_width,omitempty"`
	IntrinsicHeight int               `json:"intrinsic_height,omitempty"`
	Direction       string            `json:"direction,omitempty"`
	Constraints     []json.RawMessage `json:"constraints,omitempty"`
	Children        []treeNode        `json:"children,omitempty"`
	Spacing         int               `json:"spacing,omitempty"`
	Flex            string            `json:"flex,omitempty"`
	Sizing          string            `json:"sizing,omitempty"`
}

func constraintMinContribution(c constraint) int {
	switch c.kind {
	case "Length":
		return c.value
	case "Percentage", "Ratio", "Fill":
		return 0
	case "Min":
		if c.inner == nil {
			return c.value
		}
		inner := constraintMinContribution(*c.inner)
		if c.value > inner {
			return c.value
		}
		return inner
	case "Max":
		if c.inner == nil {
			return c.value
		}
		inner := constraintMinContribution(*c.inner)
		if c.value < inner {
			return c.value
		}
		return inner
	}
	return 0
}

func computeIntrinsicWidth(node treeNode) int {
	if node.Type == "leaf" {
		return node.IntrinsicWidth
	}
	n := len(node.Children)
	if n == 0 {
		return 0
	}
	dir := node.Direction
	if dir == "" {
		dir = "HORIZONTAL"
	}
	if dir == "HORIZONTAL" {
		total := 0
		for i, child := range node.Children {
			childIntr := computeIntrinsicWidth(child)
			consMin := 0
			if i < len(node.Constraints) {
				consMin = constraintMinContribution(parseConstraint(node.Constraints[i]))
			}
			v := childIntr
			if consMin > v {
				v = consMin
			}
			total += v
		}
		if n > 1 {
			total += (n - 1) * node.Spacing
		}
		return total
	}
	maxW := 0
	for _, child := range node.Children {
		w := computeIntrinsicWidth(child)
		if w > maxW {
			maxW = w
		}
	}
	return maxW
}

func computeIntrinsicHeight(node treeNode) int {
	if node.Type == "leaf" {
		return node.IntrinsicHeight
	}
	n := len(node.Children)
	if n == 0 {
		return 0
	}
	dir := node.Direction
	if dir == "" {
		dir = "HORIZONTAL"
	}
	if dir == "VERTICAL" {
		total := 0
		for i, child := range node.Children {
			childIntr := computeIntrinsicHeight(child)
			consMin := 0
			if i < len(node.Constraints) {
				consMin = constraintMinContribution(parseConstraint(node.Constraints[i]))
			}
			v := childIntr
			if consMin > v {
				v = consMin
			}
			total += v
		}
		if n > 1 {
			total += (n - 1) * node.Spacing
		}
		return total
	}
	maxH := 0
	for _, child := range node.Children {
		h := computeIntrinsicHeight(child)
		if h > maxH {
			maxH = h
		}
	}
	return maxH
}

func composeTree(area rect, node treeNode) map[string]rect {
	result := make(map[string]rect)

	if node.Type == "leaf" {
		name := node.Name
		if name == "" {
			name = "unnamed"
		}
		result[name] = area
		return result
	}

	n := len(node.Children)
	if n == 0 {
		return result
	}

	dir := node.Direction
	if dir == "" {
		dir = "HORIZONTAL"
	}
	flex := node.Flex
	if flex == "" {
		flex = "START"
	}

	cs := make([]constraint, n)
	for i, rc := range node.Constraints {
		cs[i] = parseConstraint(rc)
	}

	// Apply auto-sizing: wrap constraint in Min(intrinsic, original)
	for i, child := range node.Children {
		sizing := child.Sizing
		if sizing == "" {
			sizing = "fixed"
		}
		if sizing == "auto" {
			var intrinsic int
			if dir == "HORIZONTAL" {
				intrinsic = computeIntrinsicWidth(child)
			} else {
				intrinsic = computeIntrinsicHeight(child)
			}
			if intrinsic > 0 {
				inner := cs[i]
				cs[i] = constraint{kind: "Min", value: intrinsic, inner: &inner}
			}
		}
	}

	subRects := doSplit(area, cs, dir, node.Spacing, flex)

	for i, child := range node.Children {
		if i < len(subRects) {
			childResult := composeTree(subRects[i], child)
			for k, v := range childResult {
				result[k] = v
			}
		}
	}

	return result
}

// --- JSON I/O ---

func solveSplit(data []byte) ([]byte, error) {
	var raw struct {
		Area struct {
			X      int `json:"x"`
			Y      int `json:"y"`
			Width  int `json:"width"`
			Height int `json:"height"`
		} `json:"area"`
		Constraints []json.RawMessage `json:"constraints"`
		Direction   string            `json:"direction"`
		Spacing     int               `json:"spacing"`
		Flex        string            `json:"flex"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, err
	}
	area := rect{raw.Area.X, raw.Area.Y, raw.Area.Width, raw.Area.Height}
	cs := make([]constraint, len(raw.Constraints))
	for i, rc := range raw.Constraints {
		cs[i] = parseConstraint(rc)
	}
	rects := doSplit(area, cs, raw.Direction, raw.Spacing, raw.Flex)
	return json.Marshal(rects)
}

func solveCompose(data []byte) ([]byte, error) {
	var raw struct {
		Area struct {
			X      int `json:"x"`
			Y      int `json:"y"`
			Width  int `json:"width"`
			Height int `json:"height"`
		} `json:"area"`
		Tree treeNode `json:"tree"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, err
	}
	area := rect{raw.Area.X, raw.Area.Y, raw.Area.Width, raw.Area.Height}
	result := composeTree(area, raw.Tree)
	return json.Marshal(result)
}

func solve(data []byte) ([]byte, error) {
	var modeCheck struct {
		Mode string `json:"mode"`
	}
	json.Unmarshal(data, &modeCheck)

	if modeCheck.Mode == "compose" {
		return solveCompose(data)
	}
	return solveSplit(data)
}

const helpText = `Usage: layout-oracle [--help] [--batch]

Reads a JSON layout query from stdin and writes the result as JSON to stdout.

Modes:
  (default)  Read one JSON query from stdin, write one JSON result to stdout.
  --batch    Read one JSON query per line (JSONL), write one result per line.

--- Split mode (default) ---

Partitions a rectangular area into sub-regions based on constraints.

Input format:
{
  "area": {"x": 0, "y": 0, "width": 100, "height": 50},
  "constraints": [
    {"type": "Length", "value": 30},
    {"type": "Fill", "weight": 1},
    {"type": "Percentage", "value": 25},
    {"type": "Ratio", "numerator": 1, "denominator": 3},
    {"type": "Min", "value": 20, "inner": {"type": "Fill", "weight": 1}},
    {"type": "Max", "value": 40, "inner": {"type": "Fill", "weight": 1}}
  ],
  "direction": "HORIZONTAL",
  "spacing": 0,
  "flex": "START"
}

Output: JSON array of rectangles.

--- Compose mode ---

Resolves a hierarchical layout tree to named leaf rectangles.
Set "mode": "compose" in the input JSON.

Input format:
{
  "mode": "compose",
  "area": {"x": 0, "y": 0, "width": 200, "height": 100},
  "tree": {
    "type": "container",
    "direction": "HORIZONTAL",
    "constraints": [
      {"type": "Length", "value": 60},
      {"type": "Fill", "weight": 1}
    ],
    "children": [
      {
        "type": "container",
        "direction": "VERTICAL",
        "constraints": [
          {"type": "Fill", "weight": 1},
          {"type": "Fill", "weight": 2}
        ],
        "children": [
          {"type": "leaf", "name": "header"},
          {"type": "leaf", "name": "sidebar"}
        ]
      },
      {"type": "leaf", "name": "main"}
    ]
  }
}

Tree node types:
  leaf:      {"type": "leaf", "name": "...", "intrinsic_width": N, "intrinsic_height": N, "sizing": "fixed|auto"}
  container: {"type": "container", "direction": "...", "constraints": [...], "children": [...],
              "spacing": N, "flex": "...", "sizing": "fixed|auto"}

When sizing="auto", the node's intrinsic size influences the parent's constraint resolution.
Intrinsic size for leaves uses declared intrinsic_width/intrinsic_height.
Intrinsic size for containers is computed recursively from children.

Output: JSON object mapping leaf names to rectangles.
`

func main() {
	for _, arg := range os.Args[1:] {
		if arg == "--help" || arg == "-h" {
			fmt.Print(helpText)
			os.Exit(0)
		}
	}
	batch := false
	for _, arg := range os.Args[1:] {
		if arg == "--batch" {
			batch = true
		}
	}
	if batch {
		scanner := bufio.NewScanner(os.Stdin)
		scanner.Buffer(make([]byte, 1<<20), 1<<20)
		for scanner.Scan() {
			line := scanner.Bytes()
			if len(line) == 0 {
				continue
			}
			result, err := solve(line)
			if err != nil {
				fmt.Fprintf(os.Stderr, "Error: %v\n", err)
				fmt.Println("null")
				continue
			}
			fmt.Println(string(result))
		}
	} else {
		data, err := io.ReadAll(os.Stdin)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error reading stdin: %v\n", err)
			os.Exit(1)
		}
		result, err := solve(data)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: invalid JSON input: %v\n", err)
			os.Exit(1)
		}
		fmt.Println(string(result))
	}
}
