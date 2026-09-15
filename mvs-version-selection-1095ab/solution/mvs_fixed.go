package main

import (
	"sort"
)

// Grapher is the interface for module requirement graphs used by MVS algorithms.
type Grapher interface {
	Required(m Version) ([]Version, error)
	Max(p, v1, v2 string) string
}

// overrideGraph wraps a Grapher, replacing the target's requirements.
type overrideGraph struct {
	target Version
	list   []Version
	base   Grapher
}

func (o *overrideGraph) Required(m Version) ([]Version, error) {
	if m == o.target {
		return o.list, nil
	}
	return o.base.Required(m)
}

func (o *overrideGraph) Max(p, v1, v2 string) string {
	return o.base.Max(p, v1, v2)
}

// buildListCore is the internal implementation shared by BuildList and related operations.
// It traverses the requirement graph, applying an optional upgrade function, and
// selects the maximum version for each module path.
func buildListCore(gi Grapher, target Version, upgrade func(Version) (Version, error)) ([]Version, error) {
	selected := make(map[string]string)
	selected[target.Path] = target.Version

	visited := make(map[Version]bool)
	var visit func(Version) error
	visit = func(m Version) error {
		if visited[m] {
			return nil
		}
		visited[m] = true

		if m.Version == "none" {
			return nil
		}

		deps, err := gi.Required(m)
		if err != nil {
			return err
		}

		required := deps

		// Apply upgrade function if present
		if upgrade != nil {
			u, upErr := upgrade(m)
			if upErr == nil && u != m {
				// Prepend upgrade target as an additional requirement
				newReqs := make([]Version, 0, len(deps)+1)
				newReqs = append(newReqs, u)
				newReqs = append(newReqs, deps...)
				required = newReqs
			}
		}

		for _, d := range required {
			if cur, ok := selected[d.Path]; !ok || gi.Max(d.Path, cur, d.Version) == d.Version {
				selected[d.Path] = d.Version
			}
			if err := visit(d); err != nil {
				return err
			}
		}
		return nil
	}

	if err := visit(target); err != nil {
		return nil, err
	}

	// Build result: target first, then others sorted by path
	var result []Version
	result = append(result, Version{Path: target.Path, Version: selected[target.Path]})

	var others []Version
	for p, v := range selected {
		if p != target.Path && v != "none" {
			others = append(others, Version{Path: p, Version: v})
		}
	}
	sort.Slice(others, func(i, j int) bool {
		return others[i].Path < others[j].Path
	})
	result = append(result, others...)

	return result, nil
}

// BuildList returns the build list for the target module.
func BuildList(g *Graph, target Version) ([]Version, error) {
	return buildListCore(g, target, nil)
}

// UpgradeAll returns a build list in which every module is upgraded to its
// latest non-hidden version.
func UpgradeAll(g *Graph, target Version) ([]Version, error) {
	return buildListCore(g, target, func(m Version) (Version, error) {
		if m.Path == target.Path {
			return target, nil
		}
		return g.Upgrade(m)
	})
}

// Upgrade returns a build list with specific modules upgraded.
func Upgrade(g *Graph, target Version, upgrade ...Version) ([]Version, error) {
	list, err := g.Required(target)
	if err != nil {
		return nil, err
	}

	pathInList := make(map[string]bool, len(list))
	for _, m := range list {
		pathInList[m.Path] = true
	}

	newList := make([]Version, len(list))
	copy(newList, list)

	upgradeTo := make(map[string]string, len(upgrade))
	for _, u := range upgrade {
		if !pathInList[u.Path] {
			newList = append(newList, Version{Path: u.Path, Version: "none"})
		}
		if prev, ok := upgradeTo[u.Path]; ok {
			upgradeTo[u.Path] = g.Max(u.Path, prev, u.Version)
		} else {
			upgradeTo[u.Path] = u.Version
		}
	}

	og := &overrideGraph{target: target, list: newList, base: g}
	return buildListCore(og, target, func(m Version) (Version, error) {
		if v, ok := upgradeTo[m.Path]; ok {
			return Version{Path: m.Path, Version: v}, nil
		}
		return m, nil
	})
}

// Downgrade returns a build list with specific modules downgraded,
// potentially overriding the requirements of the target.
func Downgrade(g *Graph, target Version, downgrade ...Version) ([]Version, error) {
	// Build the current full list
	fullList, err := BuildList(g, target)
	if err != nil {
		return nil, err
	}
	list := fullList[1:] // remove target

	// Set up max constraints from current build list
	max := make(map[string]string)
	for _, r := range list {
		max[r.Path] = r.Version
	}
	// Apply downgrade constraints
	for _, d := range downgrade {
		if v, ok := max[d.Path]; !ok || g.Max(d.Path, v, d.Version) != d.Version {
			max[d.Path] = d.Version
		}
	}

	// Track added modules, reverse dependencies, and exclusions
	added := make(map[Version]bool)
	rdeps := make(map[Version][]Version)
	excluded := make(map[Version]bool)

	var exclude func(Version)
	exclude = func(m Version) {
		if excluded[m] {
			return
		}
		excluded[m] = true
		for _, p := range rdeps[m] {
			exclude(p)
		}
	}

	var add func(Version)
	add = func(m Version) {
		if added[m] {
			return
		}
		added[m] = true

		// If m would upgrade an existing dependency beyond its max, exclude it
		if v, ok := max[m.Path]; ok && g.Max(m.Path, m.Version, v) != v {
			exclude(m)
			return
		}

		deps, err := g.Required(m)
		if err != nil {
			// Can't load requirements — exclude this version
			exclude(m)
			return
		}

		for _, r := range deps {
			add(r)
			if excluded[r] {
				exclude(m)
				return
			}
			rdeps[r] = append(rdeps[r], m)
		}
	}

	// Build the downgraded requirement list
	downgraded := make([]Version, 0, len(list)+1)
	downgraded = append(downgraded, target)

Loop:
	for _, r := range list {
		add(r)
		for excluded[r] {
			p, err := g.Previous(r)
			if err != nil {
				return nil, err
			}
			// If the target version for this path is between p and r,
			// try the target version (handles pseudo-versions and hidden versions
			// that Previous doesn't enumerate)
			if v := max[r.Path]; g.Max(r.Path, v, r.Version) != v && g.Max(r.Path, p.Version, v) != p.Version {
				p.Version = v
			}
			if p.Version == "none" {
				continue Loop
			}
			add(p)
			r = p
		}
		downgraded = append(downgraded, r)
	}

	// Two-pass: recompute with actual selected versions to eliminate
	// spurious transitive dependencies from initially-downgraded versions
	// that were pulled back up by other transitive requirements.
	og := &overrideGraph{target: target, list: downgraded, base: g}
	actual, err := buildListCore(og, target, nil)
	if err != nil {
		return nil, err
	}

	actualVersion := make(map[string]string, len(actual))
	for _, m := range actual {
		actualVersion[m.Path] = m.Version
	}

	// Rebuild downgraded list using actual versions
	downgraded = downgraded[:0]
	for _, m := range list {
		if v, ok := actualVersion[m.Path]; ok {
			downgraded = append(downgraded, Version{Path: m.Path, Version: v})
		}
	}

	og2 := &overrideGraph{target: target, list: downgraded, base: g}
	return buildListCore(og2, target, nil)
}

// Req returns the minimal requirement list for the target module,
// with the constraint that all module paths listed in base must
// appear in the returned list.
func Req(g *Graph, target Version, base []string) ([]Version, error) {
	list, err := BuildList(g, target)
	if err != nil {
		return nil, err
	}

	// Map from path to its selected version
	maxVer := make(map[string]string)
	for _, m := range list {
		maxVer[m.Path] = m.Version
	}

	// Compute postorder traversal and cache requirements
	var postorder []Version
	reqCache := make(map[Version][]Version)
	reqCache[target] = nil // target's requirements are already in the build list

	var walk func(Version) error
	walk = func(m Version) error {
		if _, ok := reqCache[m]; ok {
			return nil
		}
		required, err := g.Required(m)
		if err != nil {
			return err
		}
		reqCache[m] = required
		for _, m1 := range required {
			if err := walk(m1); err != nil {
				return err
			}
		}
		postorder = append(postorder, m)
		return nil
	}
	for _, m := range list {
		if err := walk(m); err != nil {
			return nil, err
		}
	}

	// Walk in reverse post-order, only adding modules not already implied
	have := make(map[Version]bool)
	walk = func(m Version) error {
		if have[m] {
			return nil
		}
		have[m] = true
		for _, m1 := range reqCache[m] {
			walk(m1)
		}
		return nil
	}

	// First walk the base modules that must be listed
	var min []Version
	haveBase := make(map[string]bool)
	for _, path := range base {
		if haveBase[path] {
			continue
		}
		m := Version{Path: path, Version: maxVer[path]}
		min = append(min, m)
		walk(m)
		haveBase[path] = true
	}

	// Now reverse postorder to bring in anything else
	for i := len(postorder) - 1; i >= 0; i-- {
		m := postorder[i]
		if maxVer[m.Path] != m.Version {
			// Older version, skip
			continue
		}
		if !have[m] {
			min = append(min, m)
			walk(m)
		}
	}

	sort.Slice(min, func(i, j int) bool {
		return min[i].Path < min[j].Path
	})
	return min, nil
}
