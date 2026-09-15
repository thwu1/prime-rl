// Functions sharing global state — optimizer must not propagate across calls
func accumulate(val) {
    sum = sum + val;
    return sum;
}

sum = 0;
x = 10 + 5;
a = accumulate(x);
b = accumulate(x * 2);
c = accumulate(1 + 0);
print a;
print b;
print c;
