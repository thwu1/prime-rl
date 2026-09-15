/* Benchmark: complex branching, jump threading, dead branches */

int classify_value(int x) {
    int result = 0;
    if (x > 100) {
        result = 3;
    } else if (x > 50) {
        result = 2;
    } else if (x > 0) {
        result = 1;
    } else {
        result = 0;
    }
    /* Redundant re-check */
    if (result == 3) {
        if (x > 100) {  /* Always true when result==3 */
            result += x - 100;
        }
    }
    return result;
}

int cascaded_checks(int a, int b, int c) {
    int r = 0;
    if (a > 0) {
        if (b > 0) {
            if (c > 0) {
                r = a + b + c;
            } else {
                r = a + b;
            }
        } else {
            if (c > 0) {
                r = a + c;
            } else {
                r = a;
            }
        }
    } else {
        if (b > 0) {
            r = b;
        } else {
            r = 0;
        }
    }
    /* Re-derive something computable from above */
    if (a > 0 && b > 0 && c > 0) {
        r = r * 2;  /* Jump threading: we know r = a+b+c here */
    }
    return r;
}

int switch_with_fallthrough(int cmd, int *data, int n) {
    int result = 0;
    for (int i = 0; i < n; i++) {
        switch (cmd) {
            case 0: result += data[i]; break;
            case 1: result += data[i] * 2; break;
            case 2: result += data[i] * 3; break;
            case 3: result += data[i] * 4; break;
            case 4: result += data[i] * 5; break;
            default: result += data[i]; break;
        }
    }
    return result;
}

int early_exit_chain(int *arr, int n) {
    int sum = 0;
    for (int i = 0; i < n; i++) {
        if (arr[i] < 0) continue;
        if (arr[i] == 0) continue;
        if (arr[i] > 1000) break;
        sum += arr[i];
        if (sum > 10000) return sum;
    }
    return sum;
}

int boolean_chain(int a, int b, int c, int d) {
    int x = (a > 0) ? 1 : 0;
    int y = (b > 0) ? 1 : 0;
    int z = (c > 0) ? 1 : 0;
    int w = (d > 0) ? 1 : 0;
    /* These could be simplified */
    if (x && y) {
        if (z || w) {
            return a + b + c + d;
        }
        return a + b;
    }
    if (!x && !y) {
        return 0;
    }
    return x * a + y * b + z * c + w * d;
}
