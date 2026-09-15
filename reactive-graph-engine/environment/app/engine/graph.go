package engine

import "fmt"

// Edge represents a directed dependency edge in the resource graph.
// Edge{From: "a", To: "b"} means resource "a" must run before resource "b"
// (equivalently, "b" depends on "a").
type Edge struct {
	From   string // source resource name
	To     string // destination resource name
	Notify bool   // if true, propagate refresh notifications along this edge
}

// Graph represents a directed acyclic graph of resources with dependency
// and notification edges.
type Graph struct {
	resources map[string]Res
	edges     []Edge
}

// NewGraph creates an empty resource graph.
func NewGraph() *Graph {
	return &Graph{
		resources: make(map[string]Res),
	}
}

// AddResource adds a resource to the graph. Returns an error if a resource
// with the same name already exists.
func (g *Graph) AddResource(r Res) error {
	name := r.Name()
	if _, exists := g.resources[name]; exists {
		return fmt.Errorf("duplicate resource: %s", name)
	}
	g.resources[name] = r
	return nil
}

// AddEdge adds a dependency edge from one resource to another.
// If notify is true, the target resource will receive a refresh notification
// when the source resource makes changes.
func (g *Graph) AddEdge(from, to string, notify bool) error {
	if _, ok := g.resources[from]; !ok {
		return fmt.Errorf("resource not found: %s", from)
	}
	if _, ok := g.resources[to]; !ok {
		return fmt.Errorf("resource not found: %s", to)
	}
	g.edges = append(g.edges, Edge{From: from, To: to, Notify: notify})
	return nil
}

// Resources returns the map of resource name to resource.
func (g *Graph) Resources() map[string]Res {
	return g.resources
}

// Edges returns all edges in the graph.
func (g *Graph) Edges() []Edge {
	return g.edges
}

// Dependencies returns the names of resources that must run before the
// given resource (i.e., resources with edges pointing TO this resource).
func (g *Graph) Dependencies(name string) []string {
	var deps []string
	for _, e := range g.edges {
		if e.To == name {
			deps = append(deps, e.From)
		}
	}
	return deps
}

// Dependents returns the names of resources that depend on the given
// resource (i.e., resources with edges pointing FROM this resource).
func (g *Graph) Dependents(name string) []string {
	var deps []string
	for _, e := range g.edges {
		if e.From == name {
			deps = append(deps, e.To)
		}
	}
	return deps
}

// NotifyTargets returns the names of resources that should receive a
// refresh notification when the given resource makes changes.
func (g *Graph) NotifyTargets(name string) []string {
	var targets []string
	for _, e := range g.edges {
		if e.From == name && e.Notify {
			targets = append(targets, e.To)
		}
	}
	return targets
}
