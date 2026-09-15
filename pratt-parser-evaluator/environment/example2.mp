// Recursive function with custom operators
// Expected output: 110
fn fib(n) = if n <= 1 then n else fib(n - 1) + fib(n - 2);
operator infixl 11 plus (a, b) = a + b;
fib(10) plus fib(10)
