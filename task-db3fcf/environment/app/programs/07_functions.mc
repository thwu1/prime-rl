// Functions with constant arguments
func square(n) {
    return n * n;
}

func add(a, b) {
    return a + b;
}

x = square(3 + 1);
print x;
y = add(2 * 3, 4 + 1);
print y;
z = square(0);
print z;
