/*
 * Test: integer modulo operator (%).
 * On x86-64, idiv puts quotient in %rax and remainder in %rdx.
 * The C modulo operator must return the remainder, not the quotient.
 *
 * Returns 0 on success, non-zero on failure.
 */
int main() {
    int a = 17 % 5;
    if (a != 2) return 1;   /* quotient=3, remainder=2 */

    int b = 100 % 7;
    if (b != 2) return 2;   /* quotient=14, remainder=2 */

    int c = 29 % 10;
    if (c != 9) return 3;   /* quotient=2, remainder=9 */

    /* Negative dividend: C99+ says result has sign of dividend */
    int d = (-7) % 3;
    if (d != -1) return 4;  /* quotient=-2, remainder=-1 */

    int e = (-19) % 5;
    if (e != -4) return 5;  /* quotient=-3, remainder=-4 */

    /* Modulo with long type */
    long f = 1000000007L % 1000000000L;
    if (f != 7) return 6;

    return 0;
}
