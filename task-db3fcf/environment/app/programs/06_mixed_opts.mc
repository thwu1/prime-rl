// Combined optimizations: folding + propagation + dead store + dead branch
a = 2 + 3;
b = a * 2;
c = b + 0;
d = 10;
d = c;
if (c > 5) {
    print c;
} else {
    print 0;
}
e = 2 + 3;
print e;
