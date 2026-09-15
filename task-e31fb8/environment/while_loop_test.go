package vm


import "testing"

func TestWhileExpression(t *testing.T) {
	tests := []vmTestCase{
		// Basic counting loop
		{"let x = 0; while (x < 10) { x++; }; x;", 10},
		// Condition starts false - never enters body
		{"let x = 42; while (false) { x++; }; x;", 42},
		// While expression evaluates to null
		{"while (false) { 1; };", Null},
	}
	runVMTests(t, tests)
}

func TestWhileBreak(t *testing.T) {
	tests := []vmTestCase{
		// Break exits infinite loop
		{"let x = 0; while (true) { if (x == 5) { break; }; x++; }; x;", 5},
		// Break from deeply nested conditional
		{"let x = 0; while (x < 100) { x++; if (x > 3) { if (x > 5) { break; }; }; }; x;", 6},
	}
	runVMTests(t, tests)
}

func TestWhileContinue(t *testing.T) {
	tests := []vmTestCase{
		// Continue skips one iteration
		{"let x = 0; let y = 0; while (x < 10) { x++; if (x == 5) { continue; }; y++; }; y;", 9},
		// Continue skips multiple early iterations
		{"let x = 0; let y = 0; while (x < 10) { x++; if (x < 4) { continue; }; y++; }; y;", 7},
	}
	runVMTests(t, tests)
}

func TestNestedWhile(t *testing.T) {
	tests := []vmTestCase{
		// Nested counting loops
		{"let x = 0; let i = 0; while (i < 3) { let j = 0; while (j < 4) { j++; x++; }; i++; }; x;", 12},
		// Break only affects inner loop
		{"let x = 0; let i = 0; while (i < 3) { let j = 0; while (true) { j++; x++; if (j == 2) { break; }; }; i++; }; x;", 6},
	}
	runVMTests(t, tests)
}

func TestWhileInFunction(t *testing.T) {
	tests := []vmTestCase{
		// While inside a function with local variables
		{"let f = func() { let x = 0; while (x < 5) { x++; }; return x; }; f();", 5},
		// Function with while + break
		{"let f = func(n) { let x = 0; while (true) { if (x == n) { break; }; x++; }; return x; }; f(7);", 7},
		// Function using while + continue + modulo
		{"let countOdd = func(n) { let x = 0; let count = 0; while (x < n) { x++; if (x % 2 == 0) { continue; }; count++; }; return count; }; countOdd(10);", 5},
	}
	runVMTests(t, tests)
}
