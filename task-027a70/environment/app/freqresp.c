/*
 * freqresp.c — Frequency response analyzer for analog filter prototypes
 *
 * Reads zero-pole-gain (ZPK) data from a text file and computes
 * the frequency response magnitude |H(jw)| at logarithmically
 * spaced frequencies.
 *
 * Usage: ./freqresp <zpk_file> [freq_start] [freq_end] [num_points]
 *
 * ZPK file format (plain text):
 *   Line 1: N_zeros N_poles gain
 *   Next N_zeros lines: real_part imag_part
 *   Next N_poles lines: real_part imag_part
 *
 * Output (stdout): freq |H(jw)| |H(jw)|_dB
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>

typedef struct { double re, im; } cmplx;

static cmplx cmul(cmplx a, cmplx b) {
    cmplx r;
    r.re = a.re * b.re - a.im * b.im;
    r.im = a.re * b.im + a.im * b.re;
    return r;
}

static cmplx csub(cmplx a, cmplx b) {
    cmplx r;
    r.re = a.re - b.re;
    r.im = a.im - b.im;
    return r;
}

static double cmag(cmplx a) {
    return sqrt(a.re * a.re + a.im * a.im);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr,
            "Usage: %s <zpk_file> [freq_start=0.01] [freq_end=10.0] [num_points=500]\n\n"
            "ZPK file format:\n"
            "  Line 1: N_zeros N_poles gain\n"
            "  Next N_zeros lines: real_part imag_part\n"
            "  Next N_poles lines: real_part imag_part\n\n"
            "Output: freq |H(jw)| |H(jw)|_dB\n",
            argv[0]);
        return 1;
    }

    double freq_start = argc > 2 ? atof(argv[2]) : 0.01;
    double freq_end   = argc > 3 ? atof(argv[3]) : 10.0;
    int num_points    = argc > 4 ? atoi(argv[4]) : 500;

    FILE *f = fopen(argv[1], "r");
    if (!f) {
        perror("Cannot open ZPK file");
        return 1;
    }

    int nz, np;
    double gain;
    if (fscanf(f, "%d %d %lf", &nz, &np, &gain) != 3) {
        fprintf(stderr, "Error reading header\n");
        fclose(f);
        return 1;
    }

    cmplx *zeros = (cmplx *)calloc(nz, sizeof(cmplx));
    cmplx *poles = (cmplx *)calloc(np, sizeof(cmplx));
    if ((nz > 0 && !zeros) || (np > 0 && !poles)) {
        fprintf(stderr, "Memory allocation failed\n");
        fclose(f);
        return 1;
    }

    for (int i = 0; i < nz; i++) {
        if (fscanf(f, "%lf %lf", &zeros[i].re, &zeros[i].im) != 2) {
            fprintf(stderr, "Error reading zero %d\n", i);
            fclose(f);
            return 1;
        }
    }
    for (int i = 0; i < np; i++) {
        if (fscanf(f, "%lf %lf", &poles[i].re, &poles[i].im) != 2) {
            fprintf(stderr, "Error reading pole %d\n", i);
            fclose(f);
            return 1;
        }
    }
    fclose(f);

    printf("# freq |H(jw)| |H(jw)|_dB\n");

    for (int i = 0; i < num_points; i++) {
        double t = (num_points > 1) ? (double)i / (num_points - 1) : 0.0;
        double w = freq_start * pow(freq_end / freq_start, t);

        cmplx s;
        s.re = 0.0;
        s.im = w;

        cmplx num_val;
        num_val.re = gain;
        num_val.im = 0.0;

        cmplx den_val;
        den_val.re = 1.0;
        den_val.im = 0.0;

        for (int j = 0; j < nz; j++)
            num_val = cmul(num_val, csub(s, zeros[j]));
        for (int j = 0; j < np; j++)
            den_val = cmul(den_val, csub(s, poles[j]));

        double H_mag = cmag(num_val) / (cmag(den_val) + 1e-300);
        double H_dB = 20.0 * log10(H_mag + 1e-300);

        printf("%.8f %.12f %.6f\n", w, H_mag, H_dB);
    }

    free(zeros);
    free(poles);
    return 0;
}
