/* Example: function calls */
int double_val(int x) {
    return x * 2;
}

int add(int a, int b) {
    return a + b;
}

int main() {
    int x = double_val(5);
    int y = add(x, 3);
    return y;
}
