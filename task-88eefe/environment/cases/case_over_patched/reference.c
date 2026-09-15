int process_v2(int input, int mode) {
    if (mode == 0)
        return input * 2;
    return input * 3;
}

int run(int value) {
    int result;
    result = process_v2(value, 0);
    return result;
}
