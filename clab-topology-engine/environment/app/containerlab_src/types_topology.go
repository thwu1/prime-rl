// Extracted from github.com/srl-labs/containerlab/types/topology.go
// This is the canonical implementation of containerlab's property resolution.
// Your federation engine must implement equivalent behavior.

package types

// Topology represents a lab topology.
type Topology struct {
	Defaults *NodeDefinition             `yaml:"defaults,omitempty"`
	Kinds    map[string]*NodeDefinition  `yaml:"kinds,omitempty"`
	Nodes    map[string]*NodeDefinition  `yaml:"nodes,omitempty"`
	Groups   map[string]*NodeDefinition  `yaml:"groups,omitempty"`
	Links    []*LinkDefinition           `yaml:"links,omitempty"`
}

// NodeDefinition contains all properties a node (or kind/group/defaults) can have.
type NodeDefinition struct {
	Kind           string            `yaml:"kind,omitempty"`
	Image          string            `yaml:"image,omitempty"`
	Type           string            `yaml:"type,omitempty"`
	Group          string            `yaml:"group,omitempty"`
	User           string            `yaml:"user,omitempty"`
	Memory         string            `yaml:"memory,omitempty"`
	Cmd            string            `yaml:"cmd,omitempty"`
	Entrypoint     string            `yaml:"entrypoint,omitempty"`
	StartupConfig  string            `yaml:"startup-config,omitempty"`
	NetworkMode    string            `yaml:"network-mode,omitempty"`
	MgmtIPv4       string            `yaml:"mgmt-ipv4,omitempty"`
	MgmtIPv6       string            `yaml:"mgmt-ipv6,omitempty"`
	CPU            float64           `yaml:"cpu,omitempty"`
	CPUSet         string            `yaml:"cpuset,omitempty"`
	ShmSize        string            `yaml:"shm-size,omitempty"`
	RestartPolicy  string            `yaml:"restart-policy,omitempty"`
	Env            map[string]string `yaml:"env,omitempty"`
	Labels         map[string]string `yaml:"labels,omitempty"`
}

// GetDefaults returns the default node definition.
func (t *Topology) GetDefaults() *NodeDefinition {
	if t.Defaults != nil {
		return t.Defaults
	}
	return new(NodeDefinition)
}

// GetKind returns the node definition for the given kind.
func (t *Topology) GetKind(kind string) *NodeDefinition {
	if t.Kinds == nil {
		return new(NodeDefinition)
	}
	if kdef, ok := t.Kinds[kind]; ok {
		return kdef
	}
	return new(NodeDefinition)
}

func (t *Topology) GetGroup(group string) *NodeDefinition {
	if t.Groups == nil {
		return nil
	}
	if gdef, ok := t.Groups[group]; ok {
		return gdef
	}
	return nil
}

// GetNodeKind resolves the effective kind for a node.
// Resolution order: node.Kind > group(node.Group).Kind > group(defaults.Group).Kind > defaults.Kind
func (t *Topology) GetNodeKind(nodeName string) string {
	defaultKind := t.GetDefaults().Kind

	nodeDefinition, ok := t.Nodes[nodeName]
	if !ok {
		return defaultKind
	}

	if nodeDefinition != nil && nodeDefinition.Kind != "" {
		return nodeDefinition.Kind
	}

	if nodeDefinition != nil {
		group := t.GetGroup(nodeDefinition.Group)
		if group != nil && group.Kind != "" {
			return group.Kind
		}
	}

	defaults := t.GetGroup(t.Defaults.Group)
	if defaults != nil && defaults.Kind != "" {
		return defaults.Kind
	}

	return defaultKind
}

// GetNodeGroup resolves the effective group for a node.
// Resolution order: node.Group > kind(resolved).Group > defaults.Group
func (t *Topology) GetNodeGroup(nodeName string) string {
	defaultGroup := t.GetDefaults().Group

	nodeDefinition, ok := t.Nodes[nodeName]
	if nodeDefinition == nil || !ok {
		return defaultGroup
	}

	if nodeDefinition.Group != "" {
		return nodeDefinition.Group
	}

	kind := t.GetNodeKind(nodeName)

	if kind != "" {
		kindGroup := t.GetKind(kind).Group

		if kindGroup != "" {
			return kindGroup
		}
	}

	return defaultGroup
}

// getField resolves a scalar field through the 4-level hierarchy.
// Priority: node > group > kind > defaults
// The group and kind used are the RESOLVED group and kind for the node
// (via GetNodeGroup and GetNodeKind).
func getField[T any](
	topo *Topology,
	nodeName string,
	getFieldNode func(*NodeDefinition) T,
	getFieldGroup func(*NodeDefinition) T,
	getFieldKind func(*NodeDefinition) T,
	getFieldDefaults func(*NodeDefinition) T,
	isSet func(T) bool,
) T {
	fieldDefault := getFieldDefaults(topo.GetDefaults())

	nodeDefinition, ok := topo.Nodes[nodeName]
	if !ok {
		return fieldDefault
	}

	if nodeDefinition != nil {
		fieldNode := getFieldNode(nodeDefinition)
		if isSet(fieldNode) {
			return fieldNode
		}
	}

	group := topo.GetGroup(topo.GetNodeGroup(nodeName))
	if group != nil {
		fieldGroup := getFieldGroup(group)
		if isSet(fieldGroup) {
			return fieldGroup
		}
	}

	kind := topo.GetKind(topo.GetNodeKind(nodeName))
	if kind != nil {
		fieldKind := getFieldKind(kind)
		if isSet(fieldKind) {
			return fieldKind
		}
	}

	return fieldDefault
}

// mergeStringMapFields merges a map[string]string field across all 4 levels.
// Merge order: defaults first, then kind, then group, then node.
// Later values override earlier ones for the same key.
// The group and kind used are the RESOLVED group and kind for the node.
func mergeStringMapFields(
	topo *Topology,
	nodeName string,
	getFieldNode func(*NodeDefinition) map[string]string,
	getFieldGroup func(*NodeDefinition) map[string]string,
	getFieldKind func(*NodeDefinition) map[string]string,
	getFieldDefaults func(*NodeDefinition) map[string]string,
) map[string]string {
	out := map[string]string{}

	nodeDefintion, ok := topo.Nodes[nodeName]
	if !ok {
		return out
	}

	var fieldNode map[string]string
	if nodeDefintion != nil {
		fieldNode = getFieldNode(nodeDefintion)
	}

	var fieldGroup map[string]string
	group := topo.GetGroup(topo.GetNodeGroup(nodeName))
	if group != nil {
		fieldGroup = getFieldGroup(group)
	}

	var fieldKind map[string]string
	kind := topo.GetKind(topo.GetNodeKind(nodeName))
	if kind != nil {
		fieldKind = getFieldKind(kind)
	}

	defaultsField := getFieldDefaults(topo.GetDefaults())

	// MergeStringMaps merges maps left-to-right; later values override.
	// Order: defaults -> kind -> group -> node
	mergedOut := MergeStringMaps(defaultsField, fieldKind, fieldGroup, fieldNode)
	if mergedOut == nil {
		return out
	}

	return mergedOut
}

// MergeStringMaps merges multiple string maps left-to-right.
// Later maps override earlier maps for the same key.
func MergeStringMaps(maps ...map[string]string) map[string]string {
	result := map[string]string{}
	for _, m := range maps {
		for k, v := range m {
			result[k] = v
		}
	}
	if len(result) == 0 {
		return nil
	}
	return result
}

// --- Usage examples from containerlab source ---

func (t *Topology) GetNodeImage(nodeName string) string {
	return getField(
		t,
		nodeName,
		func(node *NodeDefinition) string { return node.Image },
		func(group *NodeDefinition) string { return group.Image },
		func(kind *NodeDefinition) string { return kind.Image },
		func(defaults *NodeDefinition) string { return defaults.Image },
		func(v string) bool { return v != "" },
	)
}

func (t *Topology) GetNodeEnv(nodeName string) map[string]string {
	return mergeStringMapFields(
		t,
		nodeName,
		func(node *NodeDefinition) map[string]string { return node.Env },
		func(group *NodeDefinition) map[string]string { return group.Env },
		func(kind *NodeDefinition) map[string]string { return kind.Env },
		func(defaults *NodeDefinition) map[string]string { return defaults.Env },
	)
}

func (t *Topology) GetNodeLabels(nodeName string) map[string]string {
	return mergeStringMapFields(
		t,
		nodeName,
		func(node *NodeDefinition) map[string]string { return node.Labels },
		func(group *NodeDefinition) map[string]string { return group.Labels },
		func(kind *NodeDefinition) map[string]string { return kind.Labels },
		func(defaults *NodeDefinition) map[string]string { return defaults.Labels },
	)
}

func (t *Topology) GetNodeUser(nodeName string) string {
	return getField(
		t,
		nodeName,
		func(node *NodeDefinition) string { return node.User },
		func(group *NodeDefinition) string { return group.User },
		func(kind *NodeDefinition) string { return kind.User },
		func(defaults *NodeDefinition) string { return defaults.User },
		func(v string) bool { return v != "" },
	)
}

func (t *Topology) GetNodeMemory(nodeName string) string {
	return getField(
		t,
		nodeName,
		func(node *NodeDefinition) string { return node.Memory },
		func(group *NodeDefinition) string { return group.Memory },
		func(kind *NodeDefinition) string { return kind.Memory },
		func(defaults *NodeDefinition) string { return defaults.Memory },
		func(v string) bool { return v != "" },
	)
}
