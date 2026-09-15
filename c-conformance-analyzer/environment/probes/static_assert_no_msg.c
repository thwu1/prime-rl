/* Probe: _Static_assert without message string (C23 allows omission) */
_Static_assert(sizeof(int) >= 4);
int main(void) { return 0; }
