// Prime counter with constant folding opportunities
func is_prime(n) {
    if (n < 2) {
        return 0;
    }
    d = 2;
    while (d * d <= n) {
        if (n - (n / d) * d == 0) {
            return 0;
        }
        d = d + 1;
    }
    return 1;
}

count = 0;
num = 2;
limit = 10 + 10 + 10;
while (num < limit) {
    if (is_prime(num)) {
        count = count + 1;
    }
    num = num + 1;
}
print count;
