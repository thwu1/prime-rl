/* Probe: bool, true, false as language keywords without stdbool.h (C23 feature) */
int main(void) {
    bool b = true;
    bool c = false;
    return (b && !c) ? 0 : 1;
}
