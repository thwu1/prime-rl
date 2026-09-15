package main

import (
	"bufio"
	"bytes"
	"container/heap"
	"encoding/binary"
	"fmt"
	"hash/crc32"
	"io"
	"math"
	"os"
	"sort"
	"strconv"
	"strings"
)


type Edge struct {
	To     string
	Weight float64
}

type Graph struct {
	Weighted bool
	Nodes    map[string]bool
	Adj      map[string][]Edge
	Seen     map[string]map[string]bool
}

func NewGraph() *Graph {
	return &Graph{
		Nodes: make(map[string]bool),
		Adj:   make(map[string][]Edge),
		Seen:  make(map[string]map[string]bool),
	}
}

func (g *Graph) AddNode(name string) {
	g.Nodes[name] = true
	if _, ok := g.Adj[name]; !ok {
		g.Adj[name] = nil
	}
}

func (g *Graph) AddEdge(from, to string, w float64) {
	g.AddNode(from)
	g.AddNode(to)
	if g.Seen[from] == nil {
		g.Seen[from] = make(map[string]bool)
	}
	if g.Seen[from][to] {
		return
	}
	g.Seen[from][to] = true
	g.Adj[from] = append(g.Adj[from], Edge{To: to, Weight: w})
}

func (g *Graph) SortedNodes() []string {
	ns := make([]string, 0, len(g.Nodes))
	for n := range g.Nodes {
		ns = append(ns, n)
	}
	sort.Strings(ns)
	return ns
}

func (g *Graph) NumEdges() int {
	c := 0
	for _, es := range g.Adj {
		c += len(es)
	}
	return c
}

func (g *Graph) SelfLoops() int {
	c := 0
	for from, es := range g.Adj {
		for _, e := range es {
			if e.To == from {
				c++
			}
		}
	}
	return c
}

func isValidIdent(s string) bool {
	if len(s) == 0 {
		return false
	}
	c := s[0]
	if !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_') {
		return false
	}
	for i := 1; i < len(s); i++ {
		c = s[i]
		if !((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_') {
			return false
		}
	}
	return true
}

func ParseFile(path string) (*Graph, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("cannot open file: %s", path)
	}
	defer f.Close()

	g := NewGraph()
	sc := bufio.NewScanner(f)
	ln := 0
	for sc.Scan() {
		ln++
		line := strings.TrimSpace(sc.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if line == "@weighted" {
			g.Weighted = true
			continue
		}
		if strings.HasPrefix(line, "node ") {
			name := strings.TrimSpace(line[5:])
			if !isValidIdent(name) {
				return nil, fmt.Errorf("line %d: invalid node name '%s'", ln, name)
			}
			g.AddNode(name)
			continue
		}
		if strings.HasPrefix(line, "edge ") {
			rest := line[5:]
			arr := strings.Index(rest, "->")
			if arr == -1 {
				return nil, fmt.Errorf("line %d: missing '->' in edge", ln)
			}
			src := strings.TrimSpace(rest[:arr])
			after := strings.TrimSpace(rest[arr+2:])
			tokens := strings.Fields(after)
			if len(tokens) == 0 {
				return nil, fmt.Errorf("line %d: missing destination", ln)
			}
			dst := tokens[0]
			if !isValidIdent(src) || !isValidIdent(dst) {
				return nil, fmt.Errorf("line %d: invalid node name", ln)
			}
			w := 1.0
			if g.Weighted && len(tokens) > 1 {
				w, err = strconv.ParseFloat(tokens[1], 64)
				if err != nil {
					return nil, fmt.Errorf("line %d: invalid weight '%s'", ln, tokens[1])
				}
				if w < 0 {
					return nil, fmt.Errorf("line %d: weight must be non-negative", ln)
				}
			}
			g.AddEdge(src, dst, w)
			continue
		}
		return nil, fmt.Errorf("line %d: unrecognized: %s", ln, line)
	}
	return g, nil
}

// ---- info ----

func doInfo(g *Graph) {
	n := len(g.Nodes)
	e := g.NumEdges()
	d := 0.0
	if n > 1 {
		d = float64(e) / float64(n*(n-1))
	}
	fmt.Printf("nodes: %d\n", n)
	fmt.Printf("edges: %d\n", e)
	fmt.Printf("weighted: %v\n", g.Weighted)
	fmt.Printf("density: %.4f\n", d)
	fmt.Printf("self_loops: %d\n", g.SelfLoops())
}

// ---- adj ----

func doAdj(g *Graph) {
	for _, node := range g.SortedNodes() {
		edges := g.Adj[node]
		sorted := make([]Edge, len(edges))
		copy(sorted, edges)
		sort.Slice(sorted, func(i, j int) bool {
			return sorted[i].To < sorted[j].To
		})
		if len(sorted) == 0 {
			fmt.Printf("%s -> (none)\n", node)
		} else {
			parts := make([]string, len(sorted))
			for i, e := range sorted {
				if g.Weighted {
					parts[i] = fmt.Sprintf("%s(%.1f)", e.To, e.Weight)
				} else {
					parts[i] = e.To
				}
			}
			fmt.Printf("%s -> %s\n", node, strings.Join(parts, ", "))
		}
	}
}

// ---- shortest path (Dijkstra / BFS) ----

type pqItem struct {
	node string
	cost float64
	dist int
	path []string
	idx  int
}
type pq []*pqItem

func (q pq) Len() int { return len(q) }
func (q pq) Less(i, j int) bool {
	if q[i].cost != q[j].cost {
		return q[i].cost < q[j].cost
	}
	if q[i].dist != q[j].dist {
		return q[i].dist < q[j].dist
	}
	return q[i].node < q[j].node
}
func (q pq) Swap(i, j int) {
	q[i], q[j] = q[j], q[i]
	q[i].idx = i
	q[j].idx = j
}
func (q *pq) Push(x interface{}) {
	it := x.(*pqItem)
	it.idx = len(*q)
	*q = append(*q, it)
}
func (q *pq) Pop() interface{} {
	old := *q
	n := len(old)
	it := old[n-1]
	old[n-1] = nil
	it.idx = -1
	*q = old[:n-1]
	return it
}

func doShortest(g *Graph, src, dst string) {
	if !g.Nodes[src] {
		fmt.Fprintf(os.Stderr, "error: node '%s' not found\n", src)
		os.Exit(1)
	}
	if !g.Nodes[dst] {
		fmt.Fprintf(os.Stderr, "error: node '%s' not found\n", dst)
		os.Exit(1)
	}
	if src == dst {
		fmt.Println(src)
		fmt.Println("distance: 0")
		if g.Weighted {
			fmt.Println("cost: 0.0")
		}
		return
	}
	if g.Weighted {
		dijkstra(g, src, dst)
	} else {
		bfs(g, src, dst)
	}
}

func dijkstra(g *Graph, src, dst string) {
	best := make(map[string]float64)
	q := &pq{}
	heap.Init(q)
	heap.Push(q, &pqItem{node: src, cost: 0, dist: 0, path: []string{src}})
	for q.Len() > 0 {
		it := heap.Pop(q).(*pqItem)
		if it.node == dst {
			fmt.Println(strings.Join(it.path, " -> "))
			fmt.Printf("distance: %d\n", it.dist)
			fmt.Printf("cost: %.1f\n", it.cost)
			return
		}
		if prev, ok := best[it.node]; ok && prev <= it.cost {
			continue
		}
		best[it.node] = it.cost
		for _, e := range g.Adj[it.node] {
			nc := it.cost + e.Weight
			if prev, ok := best[e.To]; ok && prev <= nc {
				continue
			}
			np := make([]string, len(it.path)+1)
			copy(np, it.path)
			np[len(it.path)] = e.To
			heap.Push(q, &pqItem{node: e.To, cost: nc, dist: it.dist + 1, path: np})
		}
	}
	fmt.Printf("no path from %s to %s\n", src, dst)
}

func bfs(g *Graph, src, dst string) {
	type state struct {
		node string
		path []string
	}
	vis := map[string]bool{src: true}
	queue := []state{{src, []string{src}}}
	for len(queue) > 0 {
		cur := queue[0]
		queue = queue[1:]
		if cur.node == dst {
			fmt.Println(strings.Join(cur.path, " -> "))
			fmt.Printf("distance: %d\n", len(cur.path)-1)
			return
		}
		nbrs := make([]Edge, len(g.Adj[cur.node]))
		copy(nbrs, g.Adj[cur.node])
		sort.Slice(nbrs, func(i, j int) bool {
			return nbrs[i].To < nbrs[j].To
		})
		for _, e := range nbrs {
			if !vis[e.To] {
				vis[e.To] = true
				np := make([]string, len(cur.path)+1)
				copy(np, cur.path)
				np[len(cur.path)] = e.To
				queue = append(queue, state{e.To, np})
			}
		}
	}
	fmt.Printf("no path from %s to %s\n", src, dst)
}

// ---- topo ----

func doTopo(g *Graph) {
	indeg := make(map[string]int)
	for n := range g.Nodes {
		indeg[n] = 0
	}
	for _, es := range g.Adj {
		for _, e := range es {
			indeg[e.To]++
		}
	}
	var avail []string
	for n, d := range indeg {
		if d == 0 {
			avail = append(avail, n)
		}
	}
	sort.Strings(avail)
	var result []string
	for len(avail) > 0 {
		node := avail[0]
		avail = avail[1:]
		result = append(result, node)
		for _, e := range g.Adj[node] {
			indeg[e.To]--
			if indeg[e.To] == 0 {
				i := sort.SearchStrings(avail, e.To)
				avail = append(avail, "")
				copy(avail[i+1:], avail[i:])
				avail[i] = e.To
			}
		}
	}
	if len(result) != len(g.Nodes) {
		fmt.Fprintln(os.Stderr, "error: graph contains a cycle")
		os.Exit(1)
	}
	for _, n := range result {
		fmt.Println(n)
	}
}

// ---- allpaths ----

type pathResult struct {
	path   []string
	cost   float64
	length int
}

func doAllPaths(g *Graph, src, dst string) {
	if !g.Nodes[src] {
		fmt.Fprintf(os.Stderr, "error: node '%s' not found\n", src)
		os.Exit(1)
	}
	if !g.Nodes[dst] {
		fmt.Fprintf(os.Stderr, "error: node '%s' not found\n", dst)
		os.Exit(1)
	}

	var results []pathResult
	vis := map[string]bool{src: true}

	var dfs func(string, []string, float64)
	dfs = func(node string, path []string, cost float64) {
		if node == dst {
			p := make([]string, len(path))
			copy(p, path)
			results = append(results, pathResult{p, cost, len(path) - 1})
			return
		}
		for _, e := range g.Adj[node] {
			if !vis[e.To] {
				vis[e.To] = true
				np := make([]string, len(path)+1)
				copy(np, path)
				np[len(path)] = e.To
				dfs(e.To, np, cost+e.Weight)
				vis[e.To] = false
			}
		}
	}
	dfs(src, []string{src}, 0)

	if len(results) == 0 {
		fmt.Printf("no paths from %s to %s\n", src, dst)
		return
	}

	sort.Slice(results, func(i, j int) bool {
		if g.Weighted {
			if results[i].cost != results[j].cost {
				return results[i].cost < results[j].cost
			}
		}
		if results[i].length != results[j].length {
			return results[i].length < results[j].length
		}
		pi := strings.Join(results[i].path, " -> ")
		pj := strings.Join(results[j].path, " -> ")
		return pi < pj
	})

	for _, r := range results {
		ps := strings.Join(r.path, " -> ")
		if g.Weighted {
			fmt.Printf("%s (cost: %.1f, length: %d)\n", ps, r.cost, r.length)
		} else {
			fmt.Printf("%s (length: %d)\n", ps, r.length)
		}
	}
}

// ---- serialize (graph -> custom binary format on stdout) ----
//
// Binary format:
//   Magic:    4 bytes  "GRB\x01"
//   Flags:    1 byte   (bit 0 = weighted)
//   NumNodes: 4 bytes  uint32 LE
//   Per node: 1 byte nameLen (uint8) + nameLen bytes name (sorted order)
//   NumEdges: 4 bytes  uint32 LE
//   Per edge: 4 bytes srcIdx (uint32 LE) + 4 bytes dstIdx (uint32 LE)
//             + [if weighted] 8 bytes weight (float64 LE)
//   Edges sorted by source node index, then dest node index
//   CRC32:    4 bytes  uint32 LE  (IEEE CRC32 of all preceding bytes)

func doSerialize(g *Graph) {
	var buf bytes.Buffer

	buf.Write([]byte{0x47, 0x52, 0x42, 0x01})

	var flags byte
	if g.Weighted {
		flags |= 0x01
	}
	buf.WriteByte(flags)

	nodes := g.SortedNodes()
	binary.Write(&buf, binary.LittleEndian, uint32(len(nodes)))
	nodeIdx := make(map[string]uint32)
	for i, n := range nodes {
		nodeIdx[n] = uint32(i)
		buf.WriteByte(byte(len(n)))
		buf.WriteString(n)
	}

	type edgeRec struct {
		src, dst uint32
		weight   float64
	}
	var edges []edgeRec
	for _, srcName := range nodes {
		sortedEdges := make([]Edge, len(g.Adj[srcName]))
		copy(sortedEdges, g.Adj[srcName])
		sort.Slice(sortedEdges, func(i, j int) bool {
			return sortedEdges[i].To < sortedEdges[j].To
		})
		for _, e := range sortedEdges {
			edges = append(edges, edgeRec{nodeIdx[srcName], nodeIdx[e.To], e.Weight})
		}
	}

	binary.Write(&buf, binary.LittleEndian, uint32(len(edges)))
	for _, e := range edges {
		binary.Write(&buf, binary.LittleEndian, e.src)
		binary.Write(&buf, binary.LittleEndian, e.dst)
		if g.Weighted {
			binary.Write(&buf, binary.LittleEndian, e.weight)
		}
	}

	chk := crc32.ChecksumIEEE(buf.Bytes())
	binary.Write(&buf, binary.LittleEndian, chk)

	os.Stdout.Write(buf.Bytes())
}

// ---- deserialize (binary format -> text on stdout) ----

func doDeserialize(path string) {
	data, err := os.ReadFile(path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: cannot read file: %s\n", path)
		os.Exit(1)
	}

	if len(data) < 13 {
		fmt.Fprintln(os.Stderr, "error: invalid binary format")
		os.Exit(1)
	}

	payload := data[:len(data)-4]
	storedCRC := binary.LittleEndian.Uint32(data[len(data)-4:])
	if crc32.ChecksumIEEE(payload) != storedCRC {
		fmt.Fprintln(os.Stderr, "error: checksum mismatch")
		os.Exit(1)
	}

	r := bytes.NewReader(payload)

	magic := make([]byte, 4)
	if _, err := io.ReadFull(r, magic); err != nil || string(magic) != "GRB\x01" {
		fmt.Fprintln(os.Stderr, "error: invalid magic")
		os.Exit(1)
	}

	flags, _ := r.ReadByte()
	weighted := flags&0x01 != 0

	var numNodes uint32
	binary.Read(r, binary.LittleEndian, &numNodes)
	nodes := make([]string, numNodes)
	for i := uint32(0); i < numNodes; i++ {
		nameLen, _ := r.ReadByte()
		name := make([]byte, nameLen)
		io.ReadFull(r, name)
		nodes[i] = string(name)
	}

	var numEdges uint32
	binary.Read(r, binary.LittleEndian, &numEdges)

	type edgeRec struct {
		src, dst string
		weight   float64
	}
	var edges []edgeRec
	for i := uint32(0); i < numEdges; i++ {
		var srcIdx, dstIdx uint32
		binary.Read(r, binary.LittleEndian, &srcIdx)
		binary.Read(r, binary.LittleEndian, &dstIdx)
		w := 1.0
		if weighted {
			binary.Read(r, binary.LittleEndian, &w)
		}
		edges = append(edges, edgeRec{nodes[srcIdx], nodes[dstIdx], w})
	}

	if weighted {
		fmt.Println("@weighted")
	}
	for _, n := range nodes {
		fmt.Printf("node %s\n", n)
	}
	for _, e := range edges {
		if weighted {
			fmt.Printf("edge %s -> %s %.1f\n", e.src, e.dst, e.weight)
		} else {
			fmt.Printf("edge %s -> %s\n", e.src, e.dst)
		}
	}
}

// ---- pagerank ----

func doPageRank(g *Graph, dampStr, iterStr string) {
	damping := 0.85
	maxIter := 100

	if dampStr != "" {
		d, err := strconv.ParseFloat(dampStr, 64)
		if err != nil || d < 0 || d > 1 {
			fmt.Fprintln(os.Stderr, "error: damping factor must be between 0.0 and 1.0")
			os.Exit(1)
		}
		damping = d
	}
	if iterStr != "" {
		it, err := strconv.Atoi(iterStr)
		if err != nil || it < 1 {
			fmt.Fprintln(os.Stderr, "error: iterations must be a positive integer")
			os.Exit(1)
		}
		maxIter = it
	}

	nodes := g.SortedNodes()
	n := len(nodes)
	if n == 0 {
		return
	}

	nodeIdx := make(map[string]int)
	for i, nd := range nodes {
		nodeIdx[nd] = i
	}

	rank := make([]float64, n)
	for i := range rank {
		rank[i] = 1.0 / float64(n)
	}

	outDeg := make([]int, n)
	for i, nd := range nodes {
		outDeg[i] = len(g.Adj[nd])
	}

	for iter := 0; iter < maxIter; iter++ {
		newRank := make([]float64, n)

		danglingSum := 0.0
		for i := 0; i < n; i++ {
			if outDeg[i] == 0 {
				danglingSum += rank[i]
			}
		}

		base := (1.0 - damping + damping*danglingSum) / float64(n)
		for i := 0; i < n; i++ {
			newRank[i] = base
		}

		for i, nd := range nodes {
			if outDeg[i] > 0 {
				share := damping * rank[i] / float64(outDeg[i])
				for _, e := range g.Adj[nd] {
					j := nodeIdx[e.To]
					newRank[j] += share
				}
			}
		}

		diff := 0.0
		for i := 0; i < n; i++ {
			diff += math.Abs(newRank[i] - rank[i])
		}
		rank = newRank
		if diff < 1e-10 {
			break
		}
	}

	type nodeRank struct {
		name string
		rank float64
	}
	nrs := make([]nodeRank, n)
	for i, nd := range nodes {
		nrs[i] = nodeRank{nd, rank[i]}
	}
	sort.Slice(nrs, func(i, j int) bool {
		if nrs[i].rank != nrs[j].rank {
			return nrs[i].rank > nrs[j].rank
		}
		return nrs[i].name < nrs[j].name
	})

	for _, nr := range nrs {
		fmt.Printf("%s: %.6f\n", nr.name, nr.rank)
	}
}

// ---- scc (Tarjan's strongly connected components) ----

func doSCC(g *Graph) {
	nodes := g.SortedNodes()
	n := len(nodes)
	if n == 0 {
		return
	}

	nodeIdx := make(map[string]int)
	for i, nd := range nodes {
		nodeIdx[nd] = i
	}

	idx := make([]int, n)
	low := make([]int, n)
	onStack := make([]bool, n)
	visited := make([]bool, n)
	for i := range idx {
		idx[i] = -1
	}

	var stack []int
	counter := 0
	var components [][]string

	var strongconnect func(v int)
	strongconnect = func(v int) {
		idx[v] = counter
		low[v] = counter
		counter++
		visited[v] = true
		stack = append(stack, v)
		onStack[v] = true

		for _, e := range g.Adj[nodes[v]] {
			w := nodeIdx[e.To]
			if !visited[w] {
				strongconnect(w)
				if low[w] < low[v] {
					low[v] = low[w]
				}
			} else if onStack[w] {
				if idx[w] < low[v] {
					low[v] = idx[w]
				}
			}
		}

		if low[v] == idx[v] {
			var comp []string
			for {
				w := stack[len(stack)-1]
				stack = stack[:len(stack)-1]
				onStack[w] = false
				comp = append(comp, nodes[w])
				if w == v {
					break
				}
			}
			sort.Strings(comp)
			components = append(components, comp)
		}
	}

	for i := 0; i < n; i++ {
		if !visited[i] {
			strongconnect(i)
		}
	}

	sort.Slice(components, func(i, j int) bool {
		return components[i][0] < components[j][0]
	})

	for _, comp := range components {
		fmt.Printf("{%s}\n", strings.Join(comp, ", "))
	}
}

// ---- main ----

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: graphtool <command> <file> [args...]")
		fmt.Fprintln(os.Stderr, "commands: info, adj, shortest, topo, allpaths, serialize, deserialize, pagerank, scc")
		os.Exit(1)
	}
	cmd := os.Args[1]
	if len(os.Args) < 3 {
		fmt.Fprintln(os.Stderr, "usage: graphtool <command> <file> [args...]")
		fmt.Fprintln(os.Stderr, "commands: info, adj, shortest, topo, allpaths, serialize, deserialize, pagerank, scc")
		os.Exit(1)
	}
	path := os.Args[2]

	if cmd == "deserialize" {
		doDeserialize(path)
		return
	}

	g, err := ParseFile(path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}

	switch cmd {
	case "info":
		doInfo(g)
	case "adj":
		doAdj(g)
	case "shortest":
		if len(os.Args) != 5 {
			fmt.Fprintln(os.Stderr, "usage: graphtool shortest <file> <src> <dst>")
			os.Exit(1)
		}
		doShortest(g, os.Args[3], os.Args[4])
	case "topo":
		doTopo(g)
	case "allpaths":
		if len(os.Args) != 5 {
			fmt.Fprintln(os.Stderr, "usage: graphtool allpaths <file> <src> <dst>")
			os.Exit(1)
		}
		doAllPaths(g, os.Args[3], os.Args[4])
	case "serialize":
		doSerialize(g)
	case "pagerank":
		dampStr := ""
		iterStr := ""
		if len(os.Args) > 3 {
			dampStr = os.Args[3]
		}
		if len(os.Args) > 4 {
			iterStr = os.Args[4]
		}
		doPageRank(g, dampStr, iterStr)
	case "scc":
		doSCC(g)
	default:
		fmt.Fprintf(os.Stderr, "error: unknown command '%s'\n", cmd)
		fmt.Fprintln(os.Stderr, "commands: info, adj, shortest, topo, allpaths, serialize, deserialize, pagerank, scc")
		os.Exit(1)
	}
}
