// Nested loops with redundant computation patterns
total = 0;
scale = 2 + 3;
i = 0;
while (i < 4) {
    partial = 0;
    j = 0;
    while (j < 3) {
        partial = partial + scale * 1;
        j = j + 1;
    }
    total = total + partial + 0;
    i = i + 1;
}
print total;
