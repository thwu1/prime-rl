// Dead branch elimination via constant conditions
if (1) {
    print 1;
}
if (0) {
    print 999;
}
x = 5;
y = 3;
if (10 < 5) {
    print 998;
} else {
    print 3;
}
print x;
