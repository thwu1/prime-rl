/*
 * NEC2 Simulation Output Analyzer
 * Parses NEC2 output files and computes antenna performance metrics.
 *
 * Usage: nec2_analyzer <output_file> [run_number]
 */


#include "nec2_analyzer.h"

/* Extract a fixed-width field from a line as a double.
 * NEC2 uses 12-character wide floating-point fields in scientific notation.
 * Fields may have no space separator when a negative value follows. */
static double extract_field(const char *line, int start, int width) {
    char buf[64];
    int len = (int)strlen(line);
    if (start >= len) return 0.0;
    int end = start + width;
    if (end > len) end = len;
    int n = end - start;
    strncpy(buf, line + start, n);
    buf[n] = '\0';
    return atof(buf);
}

/* Check if a line contains a specific header string */
static int line_contains(const char *line, const char *pattern) {
    return strstr(line, pattern) != NULL;
}

/* Skip leading whitespace and return pointer to first non-space */
static const char *skip_ws(const char *s) {
    while (*s && isspace((unsigned char)*s)) s++;
    return s;
}

/* Parse the ANTENNA INPUT PARAMETERS data line.
 * Format (fixed-width, columns starting at 0):
 *   TAG(6) SEG(6) V_RE(12) V_IM(12) I_RE(12) I_IM(12) Z_RE(12) Z_IM(12) Y_RE(12) Y_IM(12) POWER(12)
 *   Columns: 0-5  6-11  12-23  24-35  36-47  48-59  60-71  72-83  84-95  96-107  108-119
 */
static int parse_input_params(const char *line, InputParams *p) {
    if (strlen(line) < 80) return 0;
    /* Check this looks like a data line (starts with spaces then digits) */
    const char *s = skip_ws(line);
    if (!*s || (!isdigit((unsigned char)*s) && *s != '-')) return 0;

    p->tag    = (int)extract_field(line, 0, 6);
    p->seg    = (int)extract_field(line, 6, 6);
    p->v_real = extract_field(line, 12, 12);
    p->v_imag = extract_field(line, 24, 12);
    p->i_real = extract_field(line, 36, 12);
    p->i_imag = extract_field(line, 48, 12);

    /* BUG: Reading current fields (36-59) instead of impedance fields (60-83).
     * The impedance columns start at offset 60, not 36. */
    p->z_real = extract_field(line, 36, 12);
    p->z_imag = extract_field(line, 48, 12);

    p->y_real = extract_field(line, 84, 12);
    p->y_imag = extract_field(line, 96, 12);
    p->power  = extract_field(line, 108, 12);
    return 1;
}

/* Parse a current distribution data line.
 * Format:
 *   SEG(6) TAG(6)  X(9) Y(9) Z(9)  LENGTH(10) REAL(12) IMAG(12) MAG(12) PHASE(10)
 */
static int parse_current_line(const char *line, CurrentEntry *c) {
    if (strlen(line) < 80) return 0;
    const char *s = skip_ws(line);
    if (!*s || (!isdigit((unsigned char)*s) && *s != '-')) return 0;

    int seg;
    double x, y, z, len, re, im, mag, phase;
    int tag;
    if (sscanf(line, "%d %d %lf %lf %lf %lf %lf %lf %lf %lf",
               &seg, &tag, &x, &y, &z, &len, &re, &im, &mag, &phase) < 10)
        return 0;

    c->tag = tag;
    c->x = x; c->y = y; c->z = z;
    c->seg_length = len;
    c->i_real = re;
    c->i_imag = im;

    /* BUG: Current magnitude computed as sum of absolute values
     * instead of Euclidean norm sqrt(re^2 + im^2). */
    c->i_mag = fabs(re) + fabs(im);

    c->i_phase = phase;
    return 1;
}

/* Parse a radiation pattern data line.
 * Format:
 *   THETA(10) PHI(8)  VERT_DB(10) HOR_DB(8) TOTAL_DB(8) ...
 */
static int parse_pattern_line(const char *line, PatternEntry *pe) {
    if (strlen(line) < 40) return 0;
    const char *s = skip_ws(line);
    if (!*s || (!isdigit((unsigned char)*s) && *s != '-')) return 0;
    /* Check it's not a header line */
    if (strstr(line, "THETA") || strstr(line, "DEGREES") || strstr(line, "VOLTS"))
        return 0;

    double theta, phi, gv, gh, gt;
    double axr, tilt;
    char sense[16] = "";
    double etm, etp, epm, epp;

    int n = sscanf(line, "%lf %lf %lf %lf %lf %lf %lf %15s %lf %lf %lf %lf",
                   &theta, &phi, &gv, &gh, &gt,
                   &axr, &tilt, sense, &etm, &etp, &epm, &epp);
    if (n < 5) return 0;

    pe->theta = theta;
    pe->phi = phi;
    pe->gain_vert_db = gv;
    pe->gain_hor_db = gh;
    pe->gain_total_db = gt;
    pe->e_theta_mag = (n >= 9) ? etm : 0.0;
    pe->e_theta_phase = (n >= 10) ? etp : 0.0;
    pe->e_phi_mag = (n >= 11) ? epm : 0.0;
    pe->e_phi_phase = (n >= 12) ? epp : 0.0;
    return 1;
}

/* Compute VSWR from complex impedance relative to Z0_REF */
static double compute_vswr(double z_real, double z_imag) {
    double denom_r = z_real + Z0_REF;
    double denom_i = z_imag;
    double num_r = z_real - Z0_REF;
    double num_i = z_imag;

    double num_mag_sq = num_r * num_r + num_i * num_i;
    double den_mag_sq = denom_r * denom_r + denom_i * denom_i;

    if (den_mag_sq < 1e-30) return 999.0;

    double gamma_mag_sq = num_mag_sq / den_mag_sq;

    /* BUG: Uses |Gamma|^2 in the VSWR formula instead of |Gamma|.
     * Correct: gamma_mag = sqrt(gamma_mag_sq); vswr = (1+gamma_mag)/(1-gamma_mag)
     * Wrong:   vswr = (1 + gamma_mag_sq) / (1 - gamma_mag_sq) */
    if (gamma_mag_sq >= 1.0) return 999.0;
    double vswr = (1.0 + gamma_mag_sq) / (1.0 - gamma_mag_sq);
    return vswr;
}

/* Find maximum gain from radiation pattern data */
static void find_max_gain(const PatternEntry *pat, int n,
                          double *max_db, double *max_theta) {
    *max_db = -9999.0;
    *max_theta = 0.0;

    for (int i = 0; i < n; i++) {
        /* BUG: Reads horizontal-polarization gain instead of total gain.
         * The HOR column is -999.99 for vertically polarized antennas.
         * Should use gain_total_db, not gain_hor_db. */
        double g = pat[i].gain_hor_db;
        if (g > *max_db) {
            *max_db = g;
            *max_theta = pat[i].theta;
        }
    }
}

/* Compute average power gain from pattern data.
 * The average gain over the sphere should equal the radiation efficiency
 * for a correctly modeled antenna. */
static double compute_avg_gain(const PatternEntry *pat, int n) {
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
}

/* Main parsing loop: reads a NEC2 output file and extracts data for
 * the specified run number (1-based). */
static int parse_nec2_output(const char *filename, int run_number, RunData *rd) {
    FILE *fp = fopen(filename, "r");
    if (!fp) {
        fprintf(stderr, "Error: cannot open %s\n", filename);
        return -1;
    }

    memset(rd, 0, sizeof(RunData));
    rd->avg_power_gain = -1.0;

    char line[MAX_LINE];
    int current_run = 0;
    int in_input_params = 0;
    int in_currents = 0;
    int in_power = 0;
    int in_pattern = 0;
    int skip_header_lines = 0;

    while (fgets(line, MAX_LINE, fp)) {
        /* Remove trailing newline */
        int len = strlen(line);
        while (len > 0 && (line[len-1] == '\n' || line[len-1] == '\r'))
            line[--len] = '\0';

        /* Detect new simulation run by ANTENNA INPUT PARAMETERS section.
         * NEC2 files may contain multiple executions at the same frequency
         * (e.g., different ground models), each producing a new set of results
         * delimited by the ANTENNA INPUT PARAMETERS header. */
        if (line_contains(line, "ANTENNA INPUT PARAMETERS")) {
            current_run++;
            if (current_run == run_number) {
                /* Reset data for this run */
                memset(rd, 0, sizeof(RunData));
                rd->avg_power_gain = -1.0;
            }
            in_input_params = (current_run == run_number) ? 1 : 0;
            in_currents = 0;
            in_power = 0;
            in_pattern = 0;
            skip_header_lines = 3;
            continue;
        }

        /* Only process data for the target run */
        if (current_run != run_number) continue;

        /* Detect section headers */
        if (0 && line_contains(line, "ANTENNA INPUT PARAMETERS")) {
            in_input_params = 1;
            in_currents = 0;
            in_power = 0;
            in_pattern = 0;
            skip_header_lines = 3; /* skip column header lines */
            continue;
        }
        if (line_contains(line, "CURRENTS AND LOCATION")) {
            in_input_params = 0;
            in_currents = 1;
            in_power = 0;
            in_pattern = 0;
            skip_header_lines = 5;
            continue;
        }
        if (line_contains(line, "POWER BUDGET")) {
            in_input_params = 0;
            in_currents = 0;
            in_power = 1;
            in_pattern = 0;
            continue;
        }
        if (line_contains(line, "RADIATION PATTERNS") &&
            !line_contains(line, "NORMALIZED")) {
            in_input_params = 0;
            in_currents = 0;
            in_power = 0;
            in_pattern = 1;
            skip_header_lines = 4;
            continue;
        }
        if (line_contains(line, "NORMALIZED GAIN") ||
            line_contains(line, "CHARGE DENSITIES") ||
            line_contains(line, "NEAR ELECTRIC") ||
            line_contains(line, "NEAR MAGNETIC") ||
            line_contains(line, "DATA CARD NO.")) {
            in_input_params = 0;
            in_currents = 0;
            in_power = 0;
            in_pattern = 0;
            continue;
        }

        /* Skip header lines after section start */
        if (skip_header_lines > 0) {
            skip_header_lines--;
            continue;
        }

        /* Parse average gain line (can appear after pattern section) */
        if (line_contains(line, "AVERAGE POWER GAIN=") && current_run == run_number) {
            const char *p = strstr(line, "AVERAGE POWER GAIN=");
            if (p) {
                p += strlen("AVERAGE POWER GAIN=");
                while (*p == ' ') p++;
                rd->avg_power_gain = atof(p);
                rd->has_avg_gain = 1;
            }
            continue;
        }

        /* Parse data lines based on current section */
        if (in_input_params) {
            if (parse_input_params(line, &rd->input)) {
                rd->has_input = 1;
                in_input_params = 0; /* Usually only one data line */
            }
        } else if (in_currents) {
            if (rd->n_currents < MAX_SEGMENTS) {
                if (parse_current_line(line, &rd->currents[rd->n_currents])) {
                    rd->n_currents++;
                    rd->has_currents = 1;
                }
            }
        } else if (in_power) {
            if (line_contains(line, "INPUT POWER")) {
                const char *eq = strchr(line, '=');
                if (eq) rd->power.input_power = atof(eq + 1);
            } else if (line_contains(line, "RADIATED POWER")) {
                const char *eq = strchr(line, '=');
                if (eq) rd->power.radiated_power = atof(eq + 1);
            } else if (line_contains(line, "STRUCTURE LOSS")) {
                const char *eq = strchr(line, '=');
                if (eq) rd->power.structure_loss = atof(eq + 1);
            } else if (line_contains(line, "NETWORK LOSS")) {
                const char *eq = strchr(line, '=');
                if (eq) rd->power.network_loss = atof(eq + 1);
            } else if (line_contains(line, "EFFICIENCY")) {
                const char *eq = strchr(line, '=');
                if (eq) rd->power.efficiency = atof(eq + 1);
                rd->has_power = 1;
                in_power = 0;
            }
        } else if (in_pattern) {
            if (rd->n_pattern < MAX_PATTERN) {
                if (parse_pattern_line(line, &rd->pattern[rd->n_pattern])) {
                    rd->n_pattern++;
                    rd->has_pattern = 1;
                }
            }
        }
    }

    fclose(fp);
    return (current_run >= run_number) ? 0 : -1;
}

/* Output analysis results as JSON */
static void output_json(const RunData *rd) {
    double z_re = rd->input.z_real;
    double z_im = rd->input.z_imag;
    double vswr = compute_vswr(z_re, z_im);

    /* Find max current magnitude */
    double max_cur = 0.0;
    for (int i = 0; i < rd->n_currents; i++) {
        if (rd->currents[i].i_mag > max_cur)
            max_cur = rd->currents[i].i_mag;
    }

    /* Pattern analysis */
    double max_gain = -9999.0, max_theta = 0.0;
    double avg_gain = -1.0;
    if (rd->has_pattern) {
        find_max_gain(rd->pattern, rd->n_pattern, &max_gain, &max_theta);
        avg_gain = compute_avg_gain(rd->pattern, rd->n_pattern);
    }
    /* Use NEC2's own average gain if available */
    if (rd->has_avg_gain) {
        avg_gain = rd->avg_power_gain;
    }

    printf("{\n");
    printf("  \"impedance_real\": %.6e,\n", z_re);
    printf("  \"impedance_imag\": %.6e,\n", z_im);
    printf("  \"vswr\": %.6f,\n", vswr);
    printf("  \"input_power\": %.6e,\n", rd->power.input_power);
    printf("  \"radiated_power\": %.6e,\n", rd->power.radiated_power);
    printf("  \"efficiency\": %.4f,\n", rd->power.efficiency);
    printf("  \"max_current_mag\": %.6e,\n", max_cur);
    if (rd->has_pattern) {
        printf("  \"max_gain_db\": %.4f,\n", max_gain);
        printf("  \"max_gain_theta\": %.2f,\n", max_theta);
    } else {
        printf("  \"max_gain_db\": null,\n");
        printf("  \"max_gain_theta\": null,\n");
    }
    if (avg_gain > -900.0) {
        printf("  \"avg_power_gain\": %.6e\n", avg_gain);
    } else {
        printf("  \"avg_power_gain\": null\n");
    }
    printf("}\n");
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <nec2_output_file> [run_number]\n", argv[0]);
        return 1;
    }

    const char *filename = argv[1];
    int run_number = 1;
    if (argc >= 3) {
        run_number = atoi(argv[2]);
        if (run_number < 1) run_number = 1;
    }

    RunData rd;
    if (parse_nec2_output(filename, run_number, &rd) != 0) {
        fprintf(stderr, "Error: failed to parse run %d from %s\n",
                run_number, filename);
        return 1;
    }

    if (!rd.has_input) {
        fprintf(stderr, "Error: no input parameters found for run %d\n", run_number);
        return 1;
    }

    output_json(&rd);
    return 0;
}
