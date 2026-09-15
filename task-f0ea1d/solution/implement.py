#!/usr/bin/env python3
"""
Apply bug fixes and implement missing features in the NEC2
antenna characterization tool.

"""

import re

# ---------------------------------------------------------------------------
# Fix nec2_parser.c
# ---------------------------------------------------------------------------
with open('/app/nec2_parser.c', 'r') as f:
    src = f.read()

# Bug 1: Impedance reads current columns (36,48) instead of (60,72)
src = src.replace(
    "p->z_real = extract_field(line, 36, 12);\n"
    "    p->z_imag = extract_field(line, 48, 12);",
    "p->z_real = extract_field(line, 60, 12);\n"
    "    p->z_imag = extract_field(line, 72, 12);"
)

# Bug 2: Current magnitude uses L1 norm instead of L2 norm
src = src.replace(
    "c->i_mag = fabs(re) + fabs(im);",
    "c->i_mag = sqrt(re * re + im * im);"
)

with open('/app/nec2_parser.c', 'w') as f:
    f.write(src)

# ---------------------------------------------------------------------------
# Fix antenna_metrics.c: fix bugs + implement HPBW and cross-validation
# ---------------------------------------------------------------------------
with open('/app/antenna_metrics.c', 'r') as f:
    src = f.read()

# Bug 3: VSWR uses |Gamma|^2 instead of |Gamma|
src = src.replace(
    "double gamma_sq = num_sq / den_sq;\n"
    "    if (gamma_sq >= 1.0) return 999.0;\n"
    "    double vswr = (1.0 + gamma_sq) / (1.0 - gamma_sq);",
    "double gamma_sq = num_sq / den_sq;\n"
    "    double gamma = sqrt(gamma_sq);\n"
    "    if (gamma >= 1.0) return 999.0;\n"
    "    double vswr = (1.0 + gamma) / (1.0 - gamma);"
)

# Bug 4: Max gain reads horizontal-polarization column instead of total
src = src.replace(
    "double g = pat[i].gain_hor_db;",
    "double g = pat[i].gain_total_db;\n"
    "        if (g < GAIN_SENTINEL) continue;"
)

# Implement HPBW
hpbw_impl = r'''double compute_hpbw(const PatternEntry *pat, int n) {
    if (n == 0) return -1.0;

    /* Find peak total gain, excluding sentinel values */
    double peak_db = -9999.0;
    double peak_theta = 0.0, peak_phi = 0.0;
    for (int i = 0; i < n; i++) {
        if (pat[i].gain_total_db < GAIN_SENTINEL) continue;
        if (pat[i].gain_total_db > peak_db) {
            peak_db = pat[i].gain_total_db;
            peak_theta = pat[i].theta;
            peak_phi = pat[i].phi;
        }
    }
    if (peak_db < -998.0) return -1.0;

    double threshold = peak_db - 3.0;

    /* Extract the theta-cut at the peak phi, sorted by theta */
    double thetas[10000], gains[10000];
    int nc = 0;
    for (int i = 0; i < n && nc < 10000; i++) {
        if (fabs(pat[i].phi - peak_phi) > 0.01) continue;
        if (pat[i].gain_total_db < GAIN_SENTINEL) continue;
        thetas[nc] = pat[i].theta;
        gains[nc] = pat[i].gain_total_db;
        nc++;
    }
    if (nc < 2) return -1.0;

    /* Sort by theta (insertion sort for small arrays) */
    for (int i = 1; i < nc; i++) {
        double kt = thetas[i], kg = gains[i];
        int j = i - 1;
        while (j >= 0 && thetas[j] > kt) {
            thetas[j+1] = thetas[j];
            gains[j+1] = gains[j];
            j--;
        }
        thetas[j+1] = kt;
        gains[j+1] = kg;
    }

    /* Find peak index in sorted cut */
    int pidx = 0;
    for (int i = 0; i < nc; i++) {
        if (fabs(thetas[i] - peak_theta) < 0.01) { pidx = i; break; }
    }

    /* Scan downward from peak for lower -3dB crossing */
    double lower = -1.0;
    for (int i = pidx; i > 0; i--) {
        if (gains[i] >= threshold && gains[i-1] < threshold) {
            double f = (threshold - gains[i-1]) / (gains[i] - gains[i-1]);
            lower = thetas[i-1] + f * (thetas[i] - thetas[i-1]);
            break;
        }
    }

    /* Scan upward from peak for upper -3dB crossing */
    double upper = -1.0;
    for (int i = pidx; i < nc - 1; i++) {
        if (gains[i] >= threshold && gains[i+1] < threshold) {
            double f = (threshold - gains[i]) / (gains[i+1] - gains[i]);
            upper = thetas[i] + f * (thetas[i+1] - thetas[i]);
            break;
        }
    }

    if (lower >= 0.0 && upper >= 0.0)
        return upper - lower;
    else if (lower >= 0.0)
        return 2.0 * (peak_theta - lower);
    else if (upper >= 0.0)
        return 2.0 * (upper - peak_theta);
    return -1.0;
}'''

src = re.sub(
    r'double compute_hpbw\(const PatternEntry \*pat, int n\) \{[^}]*\}',
    hpbw_impl,
    src
)

# Implement cross-validation
validation_impl = r'''ValidationResult validate_deck_vs_output(const DeckData *deck, const SimRun *run) {
    ValidationResult v;
    memset(&v, 0, sizeof(v));

    v.segments_deck = deck->total_segments;
    v.segments_output = run->total_segments;
    v.segments_match = (deck->total_segments > 0 &&
                        deck->total_segments == run->total_segments) ? 1 : 0;

    if (deck->has_excitation && run->has_input) {
        v.ex_tag_deck = deck->ex_tag;
        v.ex_seg_deck = deck->ex_seg;
        v.ex_tag_output = run->input.tag;
        v.ex_seg_output = run->input.seg;
        v.excitation_match = (deck->ex_tag == run->input.tag &&
                              deck->ex_seg == run->input.seg) ? 1 : 0;
    }

    return v;
}'''

src = re.sub(
    r'ValidationResult validate_deck_vs_output\(const DeckData \*deck, const SimRun \*run\) \{[^}]*\}',
    validation_impl,
    src
)

with open('/app/antenna_metrics.c', 'w') as f:
    f.write(src)

# ---------------------------------------------------------------------------
# Implement deck_parser.c: parse GW, EX, and FR cards
# ---------------------------------------------------------------------------
with open('/app/deck_parser.c', 'r') as f:
    src = f.read()

# Replace GW stub with actual parsing
src = src.replace(
    'if (strcmp(card, "GW") == 0) {\n'
    '            /* Parse wire geometry card */\n'
    '            continue;\n'
    '        }',
    'if (strcmp(card, "GW") == 0) {\n'
    '            if (deck->n_wires < MAX_WIRES) {\n'
    '                WireDef *w = &deck->wires[deck->n_wires];\n'
    '                if (sscanf(line + 2, "%d %d %lf %lf %lf %lf %lf %lf %lf",\n'
    '                           &w->tag, &w->n_segments,\n'
    '                           &w->x1, &w->y1, &w->z1,\n'
    '                           &w->x2, &w->y2, &w->z2,\n'
    '                           &w->radius) >= 9) {\n'
    '                    deck->total_segments += w->n_segments;\n'
    '                    deck->n_wires++;\n'
    '                }\n'
    '            }\n'
    '            continue;\n'
    '        }'
)

# Replace EX stub with actual parsing
src = src.replace(
    'if (strcmp(card, "EX") == 0) {\n'
    '            /* Parse excitation card */\n'
    '            continue;\n'
    '        }',
    'if (strcmp(card, "EX") == 0) {\n'
    '            if (!deck->has_excitation) {\n'
    '                int etype, etag, eseg, ei4;\n'
    '                if (sscanf(line + 2, "%d %d %d %d",\n'
    '                           &etype, &etag, &eseg, &ei4) >= 3) {\n'
    '                    deck->ex_type = etype;\n'
    '                    deck->ex_tag = etag;\n'
    '                    deck->ex_seg = eseg;\n'
    '                    deck->has_excitation = 1;\n'
    '                }\n'
    '            }\n'
    '            continue;\n'
    '        }'
)

# Replace FR stub with actual parsing
src = src.replace(
    'if (strcmp(card, "FR") == 0) {\n'
    '            /* Parse frequency card */\n'
    '            continue;\n'
    '        }',
    'if (strcmp(card, "FR") == 0) {\n'
    '            int ifrq, nfrq, i3, i4;\n'
    '            double fmhz;\n'
    '            if (sscanf(line + 2, "%d %d %d %d %lf",\n'
    '                       &ifrq, &nfrq, &i3, &i4, &fmhz) >= 5) {\n'
    '                deck->frequency_mhz = fmhz;\n'
    '                deck->has_frequency = 1;\n'
    '            }\n'
    '            continue;\n'
    '        }'
)

with open('/app/deck_parser.c', 'w') as f:
    f.write(src)

print("All bug fixes and feature implementations applied successfully.")
