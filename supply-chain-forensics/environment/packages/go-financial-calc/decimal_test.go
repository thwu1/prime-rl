package decimal

import (
	"testing"
)

func TestNewFromString(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"0", "0"},
		{"1", "1"},
		{"-1", "-1"},
		{"1.234", "1.234"},
		{"-1.234", "-1.234"},
		{"0.1", "0.1"},
	}

	for _, tc := range tests {
		d, err := NewFromString(tc.input)
		if err != nil {
			t.Errorf("NewFromString(%q) unexpected error: %v", tc.input, err)
			continue
		}
		if d.String() != tc.expected {
			t.Errorf("NewFromString(%q) = %q, want %q", tc.input, d.String(), tc.expected)
		}
	}
}

func TestAdd(t *testing.T) {
	a := RequireFromString("1.23")
	b := RequireFromString("4.56")
	result := a.Add(b)
	expected := "5.79"
	if result.String() != expected {
		t.Errorf("Add: got %s, want %s", result.String(), expected)
	}
}

func TestMul(t *testing.T) {
	a := RequireFromString("3.14")
	b := RequireFromString("2")
	result := a.Mul(b)
	expected := "6.28"
	if result.String() != expected {
		t.Errorf("Mul: got %s, want %s", result.String(), expected)
	}
}
