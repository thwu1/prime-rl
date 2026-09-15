package main

import (
	"fmt"
	"sort"
)

// BuildList returns the build list for the target module.
// It traverses the requirement graph, collecting all reachable modules,
// and selects the maximum version for each module path.
func BuildList(g *Graph, target Version) ([]Version, error) {
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

		deps, err := g.Required(m)
		if err != nil {
			return err
		}

		for _, d := range deps {
			if cur, ok := selected[d.Path]; !ok || g.Max(d.Path, cur, d.Version) == d.Version {
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

// UpgradeAll returns a build list in which every module is upgraded to its
// latest non-hidden version.
func UpgradeAll(g *Graph, target Version) ([]Version, error) {
	// TODO: implement
	return nil, fmt.Errorf("not implemented: upgrade-all")
}

// Upgrade returns a build list with specific modules upgraded.
func Upgrade(g *Graph, target Version, upgrade ...Version) ([]Version, error) {
	// TODO: implement
	return nil, fmt.Errorf("not implemented: upgrade")
}

// Downgrade returns a build list with specific modules downgraded,
// potentially overriding the requirements of the target.
func Downgrade(g *Graph, target Version, downgrade ...Version) ([]Version, error) {
	// TODO: implement
	return nil, fmt.Errorf("not implemented: downgrade")
}

// Req returns the minimal requirement list for the target module,
// with the constraint that all module paths listed in base must
// appear in the returned list.
func Req(g *Graph, target Version, base []string) ([]Version, error) {
	// TODO: implement
	return nil, fmt.Errorf("not implemented: req")
}
