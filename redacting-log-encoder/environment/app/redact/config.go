package redact

import "strings"

// Action defines what to do with a matching field.
type Action int

const (
	// Mask replaces the field value with "[REDACTED]".
	Mask Action = iota
	// Drop removes the field entirely from the output.
	Drop
)

// Rule defines a redaction rule for a field path.
type Rule struct {
	// Pattern is a dot-separated path pattern.
	// "*" matches any single path segment.
	// Examples: "password", "user.email", "*.token", "request.*.secret"
	Pattern string
	Action  Action
}

// Match returns true if the given dot-separated path matches this rule's pattern.
func (r *Rule) Match(path string) bool {
	return matchPattern(r.Pattern, path)
}

func matchPattern(pattern, path string) bool {
	patParts := strings.Split(pattern, ".")
	pathParts := strings.Split(path, ".")
	if len(patParts) != len(pathParts) {
		return false
	}
	for i := range patParts {
		if patParts[i] != "*" && patParts[i] != pathParts[i] {
			return false
		}
	}
	return true
}

// Config holds redaction configuration.
type Config struct {
	Rules []Rule
}
