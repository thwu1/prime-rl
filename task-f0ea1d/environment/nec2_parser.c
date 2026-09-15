/*
 * NEC2 Simulation Output File Parser
 * Parses Fortran-formatted NEC2 output to extract antenna parameters.
 */


#include "nec2_parser.h"

/* Extract a fixed-width numeric field from a Fortran-formatted line.
 * NEC2 uses 12-character fields for floating-point values in scientific
 * notation. Adjacent negative values may consume separator whitespace. */
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

static int has_substr(const char *line, const char *pat) {
    return strstr(line, pat) != NULL;
}

static const char *skip_ws(const char *s) {
    while (*s && isspace((unsigned char)*s)) s++;
    return s;
}

/* Parse a data line from the ANTENNA INPUT PARAMETERS section.
 * Fixed-width layout: TAG(6) SEG(6) then ten 12-char float columns
 * for voltage, current, impedance, admittance, and power. */
static int parse_input_line(const char *line, InputParams *p) {
    if (strlen(line) < 80) return 0;
    const char *s = skip_ws(line);
    if (!*s || (!isdigit((unsigned char)*s) && *s != '-')) return 0;

    p->tag    = (int)extract_field(line, 0, 6);
    p->seg    = (int)extract_field(line, 6, 6);
    p->v_real = extract_field(line, 12, 12);
    p->v_imag = extract_field(line, 24, 12);
    p->i_real = extract_field(line, 36, 12);
    p->i_imag = extract_field(line, 48, 12);
    p->z_real = extract_field(line, 36, 12);
    p->z_imag = extract_field(line, 48, 12);
    p->y_real = extract_field(line, 84, 12);
    p->y_imag = extract_field(line, 96, 12);
    p->power  = extract_field(line, 108, 12);
    return 1;
}

/* Parse a data line from the CURRENTS AND LOCATION section. */
static int parse_current_line(const char *line, CurrentEntry *c) {
    if (strlen(line) < 80) return 0;
    const char *s = skip_ws(line);
    if (!*s || (!isdigit((unsigned char)*s) && *s != '-')) return 0;

    int seg, tag;
    double x, y, z, len_seg, re, im;

    if (sscanf(line, "%d %d %lf %lf %lf %lf %lf %lf",
               &seg, &tag, &x, &y, &z, &len_seg, &re, &im) < 8)
        return 0;

    c->seg_no = seg;
    c->tag = tag;
    c->x = x; c->y = y; c->z = z;
    c->seg_length = len_seg;
    c->i_real = re;
    c->i_imag = im;
    c->i_mag = fabs(re) + fabs(im);
    c->i_phase = 0.0;
    return 1;
}

/* Parse a data line from the RADIATION PATTERNS section.
 * Fields: THETA PHI VERT_DB HOR_DB TOTAL_DB AXIAL_RATIO TILT SENSE
 *         E_THETA_MAG E_THETA_PHASE E_PHI_MAG E_PHI_PHASE */
static int parse_pattern_line(const char *line, PatternEntry *pe) {
    if (strlen(line) < 40) return 0;
    const char *s = skip_ws(line);
    if (!*s || (!isdigit((unsigned char)*s) && *s != '-')) return 0;
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

int parse_nec2_output(const char *filename, int run_number, SimRun *run) {
    FILE *fp = fopen(filename, "r");
    if (!fp) {
        fprintf(stderr, "Error: cannot open %s\n", filename);
        return -1;
    }

    memset(run, 0, sizeof(SimRun));
    run->avg_power_gain = -1.0;

    char line[MAX_LINE];
    int current_run = 0;
    int section = 0; /* 0=none, 1=input_params, 2=currents, 3=power, 4=pattern */
    int skip_lines = 0;

    while (fgets(line, MAX_LINE, fp)) {
        int len = strlen(line);
        while (len > 0 && (line[len-1] == '\n' || line[len-1] == '\r'))
            line[--len] = '\0';

        /* Extract global parameters from any position in the file */
        if (has_substr(line, "TOTAL SEGMENTS USED=")) {
            const char *p = strstr(line, "TOTAL SEGMENTS USED=");
            p += strlen("TOTAL SEGMENTS USED=");
            while (*p == ' ') p++;
            run->total_segments = atoi(p);
        }
        if (has_substr(line, "FREQUENCY=") && has_substr(line, "MHZ")) {
            const char *p = strstr(line, "FREQUENCY=");
            p += strlen("FREQUENCY=");
            while (*p == ' ') p++;
            run->frequency_mhz = atof(p);
        }
        if (has_substr(line, "WAVELENGTH=") && has_substr(line, "METERS")) {
            const char *p = strstr(line, "WAVELENGTH=");
            p += strlen("WAVELENGTH=");
            while (*p == ' ') p++;
            run->wavelength_m = atof(p);
        }

        /* Detect run boundaries via the input parameters header */
        if (has_substr(line, "ANTENNA INPUT PARAMETERS")) {
            current_run++;
            if (current_run == run_number) {
                /* Reset run-specific data while preserving global values */
                double freq = run->frequency_mhz;
                double wl = run->wavelength_m;
                int nseg = run->total_segments;
                run->n_currents = 0;
                run->n_pattern = 0;
                run->avg_power_gain = -1.0;
                memset(&run->input, 0, sizeof(InputParams));
                memset(&run->power, 0, sizeof(PowerBudget));
                run->has_input = 0;
                run->has_currents = 0;
                run->has_power = 0;
                run->has_pattern = 0;
                run->has_avg_gain = 0;
                run->frequency_mhz = freq;
                run->wavelength_m = wl;
                run->total_segments = nseg;
            }
            section = (current_run == run_number) ? 1 : 0;
            skip_lines = 3;
            continue;
        }

        /* Only process detail sections for the target run */
        if (current_run != run_number) continue;

        /* Detect section transitions */
        if (has_substr(line, "CURRENTS AND LOCATION")) {
            section = 2; skip_lines = 5; continue;
        }
        if (has_substr(line, "POWER BUDGET")) {
            section = 3; continue;
        }
        if (has_substr(line, "RADIATION PATTERNS") &&
            !has_substr(line, "NORMALIZED") &&
            !has_substr(line, "RECEIVING")) {
            section = 4; skip_lines = 4; continue;
        }
        if (has_substr(line, "NORMALIZED GAIN") ||
            has_substr(line, "CHARGE DENSIT") ||
            has_substr(line, "NEAR ELECTRIC") ||
            has_substr(line, "NEAR MAGNETIC") ||
            has_substr(line, "DATA CARD NO.") ||
            has_substr(line, "RECEIVING PATTERN") ||
            has_substr(line, "RADIATED FIELDS NEAR")) {
            section = 0; continue;
        }

        if (skip_lines > 0) { skip_lines--; continue; }

        /* Average power gain line (can appear after radiation pattern) */
        if (has_substr(line, "AVERAGE POWER GAIN=")) {
            const char *p = strstr(line, "AVERAGE POWER GAIN=");
            p += strlen("AVERAGE POWER GAIN=");
            while (*p == ' ') p++;
            run->avg_power_gain = atof(p);
            run->has_avg_gain = 1;
            continue;
        }

        /* Parse data based on active section */
        switch (section) {
        case 1: /* Input parameters */
            if (parse_input_line(line, &run->input)) {
                run->has_input = 1;
                section = 0;
            }
            break;
        case 2: /* Current distribution */
            if (run->n_currents < MAX_SEGMENTS) {
                if (parse_current_line(line, &run->currents[run->n_currents])) {
                    run->n_currents++;
                    run->has_currents = 1;
                }
            }
            break;
        case 3: /* Power budget */
            if (has_substr(line, "INPUT POWER")) {
                const char *eq = strchr(line, '=');
                if (eq) run->power.input_power = atof(eq + 1);
            } else if (has_substr(line, "RADIATED POWER")) {
                const char *eq = strchr(line, '=');
                if (eq) run->power.radiated_power = atof(eq + 1);
            } else if (has_substr(line, "STRUCTURE LOSS")) {
                const char *eq = strchr(line, '=');
                if (eq) run->power.structure_loss = atof(eq + 1);
            } else if (has_substr(line, "NETWORK LOSS")) {
                const char *eq = strchr(line, '=');
                if (eq) run->power.network_loss = atof(eq + 1);
            } else if (has_substr(line, "EFFICIENCY")) {
                const char *eq = strchr(line, '=');
                if (eq) run->power.efficiency = atof(eq + 1);
                run->has_power = 1;
                section = 0;
            }
            break;
        case 4: /* Radiation pattern */
            if (run->n_pattern < MAX_PATTERN) {
                if (parse_pattern_line(line, &run->pattern[run->n_pattern])) {
                    run->n_pattern++;
                    run->has_pattern = 1;
                }
            }
            break;
        }
    }

    fclose(fp);
    return (current_run >= run_number) ? 0 : -1;
}
