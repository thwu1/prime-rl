/* Digital signal processing filters with helper functions */

static int clamp_int(int val, int lo, int hi) {
    if (val < lo) return lo;
    if (val > hi) return hi;
    return val;
}

static int abs_diff(int a, int b) {
    int d = a - b;
    return d < 0 ? -d : d;
}

static int weighted_avg(int a, int b, int wa, int wb) {
    long long num = (long long)a * wa + (long long)b * wb;
    return (int)(num / (wa + wb));
}

void fir_filter(const int *input, int *output, const int *coeffs,
                int n, int taps) {
    for (int i = 0; i < n; i++) {
        long long acc = 0;
        for (int j = 0; j < taps; j++) {
            int idx = i - j;
            int sample = (idx >= 0) ? input[idx] : 0;
            acc += (long long)sample * coeffs[j];
        }
        output[i] = clamp_int((int)(acc >> 15), -32768, 32767);
    }
}

void iir_filter(const int *input, int *output, const int *a_coeffs,
                const int *b_coeffs, int n, int order) {
    for (int i = 0; i < n; i++) {
        long long acc = 0;
        for (int j = 0; j <= order; j++) {
            int idx = i - j;
            if (idx >= 0)
                acc += (long long)b_coeffs[j] * input[idx];
        }
        for (int j = 1; j <= order; j++) {
            int idx = i - j;
            if (idx >= 0)
                acc -= (long long)a_coeffs[j] * output[idx];
        }
        output[i] = clamp_int((int)(acc >> 15), -32768, 32767);
    }
}

void adaptive_filter(int *input, int *desired, int *output, int *err,
                     int *weights, int n, int taps, int mu) {
    for (int i = 0; i < n; i++) {
        long long y = 0;
        for (int j = 0; j < taps; j++) {
            int idx = i - j;
            int sample = (idx >= 0) ? input[idx] : 0;
            y += (long long)weights[j] * sample;
        }
        output[i] = (int)(y >> 15);
        err[i] = desired[i] - output[i];
        for (int j = 0; j < taps; j++) {
            int idx = i - j;
            int sample = (idx >= 0) ? input[idx] : 0;
            weights[j] += (int)(((long long)mu * err[i] * sample) >> 15);
        }
    }
}

int cross_correlate(const int *a, const int *b, int n) {
    int max_corr = 0;
    for (int lag = 0; lag < n; lag++) {
        int corr = 0;
        for (int i = 0; i < n - lag; i++)
            corr += abs_diff(a[i], b[i + lag]);
        if (corr > max_corr)
            max_corr = corr;
    }
    return max_corr;
}

void envelope_detect(const int *input, int *output, int n, int attack, int release) {
    int env = 0;
    for (int i = 0; i < n; i++) {
        int abs_in = input[i] < 0 ? -input[i] : input[i];
        if (abs_in > env)
            env = weighted_avg(abs_in, env, attack, 256 - attack);
        else
            env = weighted_avg(abs_in, env, release, 256 - release);
        output[i] = env;
    }
}
