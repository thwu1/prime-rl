#!/usr/bin/env python3
"""Fix the compute_avg_gain function in nec2_analyzer.c"""


import re

with open('/app/nec2_analyzer.c', 'r') as f:
    code = f.read()

old_fn = '''static double compute_avg_gain(const PatternEntry *pat, int n) {
    if (n == 0) return -1.0;

    /* BUG: Averages gain values in dB without converting to linear first,
     * and does not handle -999.99 sentinel values (representing zero gain).
     * Correct approach:
     *   1. Skip or treat -999.99 as 0 in linear
     *   2. Convert dB to linear: G_linear = 10^(G_dB/10)
     *   3. Average the linear values
     * Wrong: directly averages the dB values */
    double sum = 0.0;
    int count = 0;
    for (int i = 0; i < n; i++) {
        sum += pat[i].gain_total_db;
        count++;
    }
    return (count > 0) ? sum / count : -1.0;
}'''

new_fn = '''static double compute_avg_gain(const PatternEntry *pat, int n) {
    if (n == 0) return -1.0;

    /* Fixed: convert dB to linear, skip -999.99 sentinel values */
    double sum = 0.0;
    int count = 0;
    for (int i = 0; i < n; i++) {
        double g_db = pat[i].gain_total_db;
        if (g_db < -998.0) {
            /* Sentinel: zero gain, contributes 0 to linear sum */
            count++;
            continue;
        }
        sum += pow(10.0, g_db / 10.0);
        count++;
    }
    return (count > 0) ? sum / count : -1.0;
}'''

code = code.replace(old_fn, new_fn)

with open('/app/nec2_analyzer.c', 'w') as f:
    f.write(code)
