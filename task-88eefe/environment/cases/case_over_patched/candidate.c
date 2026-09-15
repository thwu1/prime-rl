int validate(int input) {
    if (input < 0)
        return 0;
    if (input > 1000)
        return 0;
    return 1;
}

int process_v2(int input, int mode) {
    if (mode == 0)
        return input * 2;
    return input * 3;
}

int log_result(int val) {
    return val;
}

int run(int value) {
    int result;
    if (!validate(value))
        return -1;
    result = process_v2(value, 0);
    result = log_result(result);
    return result;
}
