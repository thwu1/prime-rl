/* Probe: binary integer literal prefix 0b (C23 standard, GNU extension in C11/C17) */
int main(void) {
    int x = 0b10101010;
    return (x == 170) ? 0 : 1;
}
