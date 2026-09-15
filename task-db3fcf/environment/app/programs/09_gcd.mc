// Iterative GCD algorithm
func gcd(a, b) {
    while (b != 0) {
        t = b;
        b = a - (a / b) * b;
        a = t;
    }
    return a;
}

print gcd(48, 18);
print gcd(100, 75);
print gcd(17, 13);
