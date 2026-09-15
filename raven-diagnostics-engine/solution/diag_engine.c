/* Raven Hydrological Diagnostics - C Shared Library Implementation */


#define _GNU_SOURCE
#include <math.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>

#define ALMOST_INF 1e32

#ifdef __cplusplus
extern "C" {
#endif

/* --- Helper types and comparators --- */

typedef struct { double val; int idx; } rpair;

static int cmp_dbl(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

static int cmp_rpair(const void *a, const void *b) {
    double x = ((const rpair *)a)->val, y = ((const rpair *)b)->val;
    return (x > y) - (x < y);
}

static int get_month(int nn, int sy, int sm, int sd, double ts) {
    struct tm t;
    memset(&t, 0, sizeof(t));
    t.tm_year = sy - 1900;
    t.tm_mon = sm - 1;
    t.tm_mday = sd + (int)(nn * ts);
    t.tm_hour = 12;
    t.tm_isdst = 0;
    timegm(&t);
    return t.tm_mon + 1;
}

static void get_ranks(const double *vals, int n, int *ranks) {
    rpair *p = (rpair *)malloc(n * sizeof(rpair));
    for (int i = 0; i < n; i++) { p[i].val = vals[i]; p[i].idx = i; }
    qsort(p, n, sizeof(rpair), cmp_rpair);
    for (int r = 0; r < n; r++) ranks[p[r].idx] = r;
    free(p);
}

/* --- Public: compute_baseweights --- */

void compute_baseweights(const double *obs, const double *mod, const double *wts,
                         int has_wts, int n, double blank_val, double threshold,
                         const char *comparison, double *out_bw) {
    double *allvals = (double *)malloc(n * sizeof(double));
    int Nobs = 0;
    for (int i = 0; i < n; i++) {
        if (obs[i] != blank_val) allvals[Nobs++] = obs[i];
    }

    int is_gt = (strcmp(comparison, "GREATERTHAN") == 0);
    int is_lt = (strcmp(comparison, "LESSTHAN") == 0);
    double thresh_obsval = 0.0;

    if (Nobs > 1 && (is_gt || is_lt)) {
        int corr = is_lt ? -1 : 0;
        qsort(allvals, Nobs, sizeof(double), cmp_dbl);
        int idx = (int)floor(threshold * Nobs) + corr;
        if (idx < 0) idx = 0;
        if (idx >= Nobs) idx = Nobs - 1;
        thresh_obsval = allvals[idx];
    }
    free(allvals);

    for (int i = 0; i < n; i++) {
        out_bw[i] = has_wts ? wts[i] : 1.0;
        if (obs[i] == blank_val) out_bw[i] = 0.0;
        if (mod[i] == blank_val) out_bw[i] = 0.0;
        if (is_gt && obs[i] < thresh_obsval) out_bw[i] = 0.0;
        if (is_lt && obs[i] > thresh_obsval) out_bw[i] = 0.0;
    }
}

/* --- Metric implementations --- */

static double m_nash_sutcliffe(const double *o, const double *m, const double *bw, int n) {
    double avg = 0, N = 0;
    for (int i = 0; i < n; i++) { avg += bw[i] * o[i]; N += bw[i]; }
    if (N > 0) avg /= N;
    double s1 = 0, s2 = 0;
    for (int i = 0; i < n; i++) {
        double d1 = o[i] - m[i], d2 = o[i] - avg;
        s1 += bw[i] * d1 * d1;
        s2 += bw[i] * d2 * d2;
    }
    return (N > 0 && s2 != 0) ? 1.0 - s1 / s2 : -ALMOST_INF;
}

static double m_daily_nse(const double *o, const double *m, const double *bw, int n, double ts) {
    int freq = (int)(1.0 / ts + 0.5);
    double avgobs = 0, N = 0;
    for (int i = 0; i < n; i++) { avgobs += bw[i] * o[i]; N += bw[i]; }
    if (N > 0) avgobs /= N;
    double s1 = 0, s2 = 0, od = 0, md = 0, dN = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i];
        od += w * o[i]; md += w * m[i]; dN += w;
        if ((i % freq) == (freq - 1)) {
            if (dN > 0) {
                od /= dN; md /= dN;
                s1 += (od - md) * (od - md) * w;
                s2 += (od - avgobs) * (od - avgobs) * w;
            }
            od = md = dN = 0;
        }
    }
    return (N > 0 && s2 != 0) ? 1.0 - s1 / s2 : -ALMOST_INF;
}

static double m_nse_der(const double *o, const double *m, const double *bw, int n, double dt) {
    int e2 = n - 1;
    double avg = 0, N = 0;
    for (int i = 0; i < e2; i++) {
        double w = bw[i + 1] * bw[i];
        avg += w * (o[i + 1] - o[i]) / dt;
        N += w;
    }
    if (N > 0) avg /= N;
    double s1 = 0, s2 = 0;
    for (int i = 0; i < e2; i++) {
        double w = bw[i + 1] * bw[i];
        double od = (o[i + 1] - o[i]) / dt, md = (m[i + 1] - m[i]) / dt;
        s1 += w * (od - md) * (od - md);
        s2 += w * (od - avg) * (od - avg);
    }
    return (N > 0 && s2 != 0) ? 1.0 - s1 / s2 : -ALMOST_INF;
}

static double m_nse_run(const double *o, const double *m, const double *bw, int n, int width) {
    if (width < 2 || width * 2 > n) return -ALMOST_INF;
    int ss = width, ee = n - width;
    int front = width / 2, back = (width % 2 == 1) ? front : front - 1;

    double avg = 0, N = 0;
    for (int i = ss; i < ee; i++) {
        double oavg = 0, w = bw[i];
        for (int k = i - front; k <= i + back; k++) { oavg += o[k]; w *= bw[k]; }
        avg += (oavg / width) * w;
        N += w;
    }
    if (N > 0) avg /= N;

    double sum1 = 0, sum2 = 0;
    for (int i = ss; i < ee; i++) {
        double oavg = 0, mavg = 0, w = bw[i];
        for (int k = i - front; k <= i + back; k++) { oavg += o[k]; mavg += m[k]; w *= bw[k]; }
        double ov = oavg / width, mv = mavg / width;
        sum1 += (ov - mv) * (ov - mv) * w;
        sum2 += (ov - avg) * (ov - avg) * w;
    }
    return (N > 0 && sum2 != 0) ? 1.0 - sum1 / sum2 : -ALMOST_INF;
}

static double m_log_nash(const double *o, const double *m, const double *bw, int n, double bv) {
    double avg = 0, N = 0;
    for (int i = 0; i < n; i++) {
        double ov = o[i], mv = m[i], w = bw[i];
        if (ov <= 0.0 || ov == bv) ov = bv; else ov = log(ov);
        if (mv <= 0.0 || ov == bv) mv = bv; else mv = log(mv);
        if (ov == bv) w = 0;
        if (mv == bv) w = 0;
        avg += ov * w; N += w;
    }
    if (N > 0) avg /= N;
    double s1 = 0, s2 = 0;
    for (int i = 0; i < n; i++) {
        double ov = o[i], mv = m[i], w = bw[i];
        if (ov <= 0.0 || ov == bv) ov = bv; else ov = log(ov);
        if (mv <= 0.0 || ov == bv) mv = bv; else mv = log(mv);
        if (ov == bv) w = 0;
        if (mv == bv) w = 0;
        s1 += (ov - mv) * (ov - mv) * w;
        s2 += (ov - avg) * (ov - avg) * w;
    }
    return (N > 0 && s2 != 0) ? 1.0 - s1 / s2 : -ALMOST_INF;
}

static double m_nse4(const double *o, const double *m, const double *bw, int n) {
    double avg = 0, N = 0;
    for (int i = 0; i < n; i++) { avg += bw[i] * o[i]; N += bw[i]; }
    if (N > 0) avg /= N;
    double s1 = 0, s2 = 0;
    for (int i = 0; i < n; i++) {
        double d1 = o[i] - m[i], d2 = o[i] - avg;
        s1 += bw[i] * d1 * d1 * d1 * d1;
        s2 += bw[i] * d2 * d2 * d2 * d2;
    }
    return (N > 0 && s2 != 0) ? 1.0 - s1 / s2 : -ALMOST_INF;
}

static double m_fuzzy_nash(const double *o, const double *m, const double *bw, int n, int width) {
    int pct = width / 100;
    double avg = 0, N = 0;
    for (int i = 0; i < n; i++) { avg += bw[i] * o[i]; N += bw[i]; }
    if (N > 0) avg /= N;
    double s1 = 0, s2 = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i], ov = o[i], mv = m[i];
        double e1 = fmax(mv - ov * (1.0 + pct), 0.0) + fmax(ov * (1.0 - pct) - mv, 0.0);
        double e2 = fmax(avg - ov * (1.0 + pct), 0.0) + fmax(avg * (1.0 - pct) - mv, 0.0);
        s1 += w * e1 * e1;
        s2 += w * e2 * e2;
    }
    return (N > 0 && s2 > 0) ? 1.0 - s1 / s2 : -ALMOST_INF;
}

static double m_rmse(const double *o, const double *m, const double *bw, int n) {
    double t = 0, N = 0;
    for (int i = 0; i < n; i++) { t += bw[i] * (o[i] - m[i]) * (o[i] - m[i]); N += bw[i]; }
    return (N > 0) ? sqrt(t / N) : -ALMOST_INF;
}

static double m_rmse_der(const double *o, const double *m, const double *bw, int n, double dt) {
    double t = 0, N = 0;
    for (int i = 0; i < n - 1; i++) {
        double w = bw[i] * bw[i + 1];
        double od = (o[i + 1] - o[i]) / dt, md = (m[i + 1] - m[i]) / dt;
        t += w * (od - md) * (od - md);
        N += w;
    }
    return (N > 0) ? sqrt(t / N) : -ALMOST_INF;
}

/* KGE type: 0=standard, 1=prime, 2=deviation */
static double m_kge(const double *o, const double *m, const double *bw, int n, int type) {
    double OS = 0, MS = 0, N = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i]; OS += o[i] * w; MS += m[i] * w; N += w;
    }
    if (N <= 0) return -ALMOST_INF;
    double OA = OS / N, MA = MS / N;
    double Ostd = 0, Mstd = 0, Cov = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i];
        Ostd += (o[i] - OA) * (o[i] - OA) * w;
        Mstd += (m[i] - MA) * (m[i] - MA) * w;
        Cov += (o[i] - OA) * (m[i] - MA) * w;
    }
    Ostd = sqrt(Ostd / N); Mstd = sqrt(Mstd / N); Cov /= N;
    double r = Cov / Ostd / Mstd;
    double Beta = MA / OA;
    double Alpha = Mstd / Ostd;
    if (type == 2) Beta = 1.0;
    if (type == 1 && Beta != 0.0) Alpha /= Beta;
    if ((N > 0) && ((OA != 0.0) || (Beta == 1.0)) && (Ostd != 0.0) && (Mstd != 0.0))
        return 1.0 - sqrt((r - 1) * (r - 1) + (Alpha - 1) * (Alpha - 1) + (Beta - 1) * (Beta - 1));
    return -ALMOST_INF;
}

static double m_kge_der(const double *o, const double *m, const double *bw, int n, double dt) {
    int e2 = n - 1;
    double OS = 0, MS = 0, N = 0;
    for (int i = 0; i < e2; i++) {
        double w = bw[i] * bw[i + 1];
        OS += ((o[i + 1] - o[i]) / dt) * w;
        MS += ((m[i + 1] - m[i]) / dt) * w;
        N += w;
    }
    if (N <= 0) return -ALMOST_INF;
    double OA = OS / N, MA = MS / N;
    double Ostd = 0, Mstd = 0, Cov = 0;
    for (int i = 0; i < e2; i++) {
        double w = bw[i] * bw[i + 1];
        double ov = (o[i + 1] - o[i]) / dt, mv = (m[i + 1] - m[i]) / dt;
        Ostd += (ov - OA) * (ov - OA) * w;
        Mstd += (mv - MA) * (mv - MA) * w;
        Cov += (ov - OA) * (mv - MA) * w;
    }
    Ostd = sqrt(Ostd / N); Mstd = sqrt(Mstd / N); Cov /= N;
    double r = Cov / Ostd / Mstd;
    double Beta = MA / OA, Alpha = Mstd / Ostd;
    if ((N > 0) && (OA != 0.0) && (Ostd != 0.0) && (Mstd != 0.0))
        return 1.0 - sqrt((r - 1) * (r - 1) + (Alpha - 1) * (Alpha - 1) + (Beta - 1) * (Beta - 1));
    return -ALMOST_INF;
}

static double m_daily_kge(const double *o, const double *m, const double *bw, int n, double ts) {
    int freq = (int)(1.0 / ts + 0.5);
    double avgO = 0, avgM = 0, N = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i]; avgO += w * o[i]; avgM += w * m[i]; N += w;
    }
    if (N > 0) { avgO /= N; avgM /= N; }
    double ostd = 0, mstd = 0, cov = 0, od = 0, md = 0, dN = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i];
        od += w * o[i]; md += w * m[i]; dN += w;
        if ((i % freq) == (freq - 1)) {
            if (dN > 0) {
                od /= dN; md /= dN;
                ostd += w * (od - avgO) * (od - avgO);
                mstd += w * (md - avgM) * (md - avgM);
                cov += w * (od - avgO) * (md - avgM);
            }
            od = md = dN = 0;
        }
    }
    if (N > 0) { ostd = sqrt(ostd / N); mstd = sqrt(mstd / N); cov /= N; }
    if (ostd == 0 || mstd == 0 || avgO == 0) return -ALMOST_INF;
    double r = cov / ostd / mstd;
    double beta = avgM / avgO, alpha = mstd / ostd;
    return (N > 0) ? 1.0 - sqrt((r - 1) * (r - 1) + (alpha - 1) * (alpha - 1) + (beta - 1) * (beta - 1)) : -ALMOST_INF;
}

static double m_pct_bias(const double *o, const double *m, const double *bw, int n) {
    double s1 = 0, s2 = 0, N = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i]; s1 += w * (m[i] - o[i]); s2 += w * o[i]; N += w;
    }
    return (N > 0) ? 100.0 * s1 / s2 : ALMOST_INF;
}

static double m_abs_pct_bias(const double *o, const double *m, const double *bw, int n) {
    double s1 = 0, s2 = 0, N = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i]; s1 += w * (m[i] - o[i]); s2 += w * o[i]; N += w;
    }
    return (N > 0) ? fabs(100.0 * s1 / s2) : ALMOST_INF;
}

static double m_abserr(const double *o, const double *m, const double *bw, int n) {
    double t = 0, N = 0;
    for (int i = 0; i < n; i++) { t += bw[i] * fabs(o[i] - m[i]); N += bw[i]; }
    return (N > 0) ? t / N : -ALMOST_INF;
}

static double m_abserr_run(const double *o, const double *m, const double *bw, int n, int width) {
    if (width < 2 || width * 2 > n) return -ALMOST_INF;
    int ss = width, ee = n - width;
    int front = width / 2, back = (width % 2 == 1) ? front : front - 1;
    double N = 0, sum1 = 0;
    for (int i = ss; i < ee; i++) {
        double oavg = 0, mavg = 0, w = bw[i];
        for (int k = i - front; k <= i + back; k++) { oavg += o[k]; mavg += m[k]; w *= bw[k]; }
        N += w;
        sum1 += fabs(oavg / width - mavg / width) * w;
    }
    return (N > 0) ? sum1 : -ALMOST_INF;
}

static double m_absmax(const double *o, const double *m, const double *bw, int n) {
    double mx = -ALMOST_INF, N = 0;
    for (int i = 0; i < n; i++) {
        if (bw[i] > 0) {
            double e = fabs(o[i] - m[i]);
            if (e > mx) mx = e;
            N += bw[i];
        }
    }
    return (N > 0) ? mx : -ALMOST_INF;
}

static double m_pdiff(const double *o, const double *m, const double *bw, int n) {
    double maxO = 0, maxM = 0, N = 0;
    for (int i = 0; i < n; i++) {
        if (bw[i] > 0) {
            if (o[i] > maxO) maxO = o[i];
            if (m[i] > maxM) maxM = m[i];
            N += bw[i];
        }
    }
    return (N > 0) ? maxM - maxO : -ALMOST_INF;
}

static double m_pct_pdiff(const double *o, const double *m, const double *bw, int n) {
    double maxO = 0, maxM = 0, N = 0;
    for (int i = 0; i < n; i++) {
        if (bw[i] > 0) {
            if (o[i] > maxO) maxO = o[i];
            if (m[i] > maxM) maxM = m[i];
            N += bw[i];
        }
    }
    return (N > 0 && maxO != 0) ? 100.0 * (maxM - maxO) / maxO : -ALMOST_INF;
}

static double m_abs_pct_pdiff(const double *o, const double *m, const double *bw, int n) {
    double maxO = 0, maxM = 0, N = 0;
    for (int i = 0; i < n; i++) {
        if (bw[i] > 0) {
            if (o[i] > maxO) maxO = o[i];
            if (m[i] > maxM) maxM = m[i];
            N += bw[i];
        }
    }
    return (N > 0 && maxO != 0) ? fabs(100.0 * (maxM - maxO) / maxO) : -ALMOST_INF;
}

static double m_tmvol(const double *o, const double *m, const double *bw, int n,
                      int sy, int sm, int sd, double ts) {
    int mon = 1;
    for (int i = 0; i < n; i++) {
        if (bw[i] != 0) { mon = get_month(i, sy, sm, sd, ts); break; }
    }
    double ndays = 0, tmvol = 0, tsum = 0, N = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i];
        if (w != 0) {
            int cm = get_month(i, sy, sm, sd, ts);
            if (cm != mon) {
                mon = cm;
                if (ndays > 0) tmvol += (tsum / ndays) * (tsum / ndays);
                ndays = 0; tsum = 0;
            }
            tsum += (m[i] - o[i]) * w;
            ndays += w;
        }
        N += w;
    }
    if (ndays > 0) tmvol += (tsum / ndays) * (tsum / ndays);
    return (N > 0) ? tmvol : -ALMOST_INF;
}

static double m_tmvol_mare(const double *o, const double *m, const double *bw, int n,
                           int sy, int sm, int sd, double ts) {
    int mon = 1, mc = 0;
    for (int i = 0; i < n; i++) {
        if (bw[i] != 0) { mon = get_month(i, sy, sm, sd, ts); break; }
    }
    double tma = 0, tsum = 0, osum = 0, N = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i];
        if (w != 0) {
            int cm = get_month(i, sy, sm, sd, ts);
            if (cm != mon) {
                if (osum > 0) { tma += fabs(tsum / osum) * 100.0; mc++; }
                mon = cm; tsum = 0; osum = 0;
            }
            tsum += (m[i] - o[i]) * w;
            osum += o[i] * w;
        }
        N += w;
    }
    if (osum > 0) { tma += fabs(tsum / osum) * 100.0; mc++; }
    return (mc > 0) ? tma / mc : -ALMOST_INF;
}

static double m_rcoef(const double *o, const double *m, const double *bw, int n) {
    double MS = 0, OS = 0, N = 0;
    for (int i = 0; i < n - 1; i++) {
        double w = bw[i] * bw[i + 1];
        MS += w * m[i]; OS += w * o[i]; N += w;
    }
    if (N <= 0) return -ALMOST_INF;
    double MA = MS / N, OA = OS / N;
    double TS = 0, MDS = 0, ODS = 0;
    for (int i = 0; i < n - 1; i++) {
        double w = bw[i] * bw[i + 1];
        TS += w * (m[i + 1] - o[i + 1]) * (m[i] - o[i]);
        MDS += w * (m[i] - MA) * (m[i] - MA);
        ODS += w * (o[i] - OA) * (o[i] - OA);
    }
    double mstd = sqrt(MDS / N), ostd = sqrt(ODS / N);
    return (N > 0 && ostd != 0 && mstd != 0) ? TS / N / (mstd * ostd) : -ALMOST_INF;
}

static double m_nsc(const double *o, const double *m, const double *bw, int n) {
    double nsc = 0, N = 0;
    for (int i = 0; i < n - 1; i++) {
        double w = bw[i] * bw[i + 1];
        if (w > 0) {
            double v1 = ceil((o[i] - m[i]) * 1000) / 1000;
            double v2 = ceil((o[i + 1] - m[i + 1]) * 1000) / 1000;
            if (v1 * v2 < 0) nsc += 1;
        }
        N += w;
    }
    return (N > 0) ? nsc : ALMOST_INF;
}

static double m_rsr(const double *o, const double *m, const double *bw, int n) {
    double OS = 0, N = 0;
    for (int i = 0; i < n; i++) { OS += o[i] * bw[i]; N += bw[i]; }
    if (N <= 0) return -ALMOST_INF;
    double OA = OS / N, TS = 0, BS = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i];
        TS += (o[i] - m[i]) * (o[i] - m[i]) * w;
        BS += (o[i] - OA) * (o[i] - OA) * w;
    }
    return (N > 0 && BS != 0 && OS != 0) ? sqrt(TS / BS) : -ALMOST_INF;
}

static double m_r2(const double *o, const double *m, const double *bw, int n) {
    double OS = 0, MS = 0, N = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i]; OS += o[i] * w; MS += m[i] * w; N += w;
    }
    if (N <= 0) return -ALMOST_INF;
    double OA = OS / N, MA = MS / N;
    double xy = 0, xx = 0, yy = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i];
        xy += w * (m[i] - MA) * (o[i] - OA);
        xx += w * (m[i] - MA) * (m[i] - MA);
        yy += w * (o[i] - OA) * (o[i] - OA);
    }
    xy /= N; xx /= N; yy /= N;
    return (N > 0 && xx != 0 && yy != 0) ? xy * xy / (xx * yy) : -ALMOST_INF;
}

static double m_mbf(const double *o, const double *m, const double *bw, int n) {
    double t = 0, N = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i], d = (m[i] - o[i]) / (2.0 * o[i]);
        t += w / (1.0 + d * d);
        N += w;
    }
    return (N > 0) ? t : -ALMOST_INF;
}

static double m_r4ms4e(const double *o, const double *m, const double *bw, int n) {
    double t = 0, N = 0;
    for (int i = 0; i < n; i++) {
        double d = o[i] - m[i]; t += bw[i] * d * d * d * d; N += bw[i];
    }
    return (N > 0) ? pow(t / N, 0.25) : -ALMOST_INF;
}

static double m_rtrmse(const double *o, const double *m, const double *bw, int n) {
    double t = 0, N = 0;
    for (int i = 0; i < n; i++) {
        double d = sqrt(o[i]) - sqrt(m[i]);
        t += bw[i] * d * d; N += bw[i];
    }
    return (N > 0) ? sqrt(t / N) : -ALMOST_INF;
}

static double m_rabserr(const double *o, const double *m, const double *bw, int n) {
    double avg = 0, N = 0;
    for (int i = 0; i < n; i++) { avg += bw[i] * o[i]; N += bw[i]; }
    if (N > 0) avg /= N;
    double s1 = 0, s2 = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i];
        s1 += w * fabs(o[i] - m[i]);
        s2 += w * fabs(avg - m[i]);
    }
    return (N > 0 && s2 != 0) ? s1 / s2 : -ALMOST_INF;
}

static double m_persindex(const double *o, const double *m, const double *bw, int n) {
    double s1 = 0, s2 = 0, N = 0;
    for (int i = 1; i < n; i++) {
        double w = bw[i] * bw[i - 1];
        s1 += w * (m[i] - o[i]) * (m[i] - o[i]);
        s2 += w * (m[i] - m[i - 1]) * (m[i] - m[i - 1]);
        N += w;
    }
    return (N > 0 && s2 != 0) ? 1.0 - s1 / s2 : -ALMOST_INF;
}

static double m_years_of_record(const double *o, const double *m, const double *bw, int n, double ts) {
    double N = 0;
    for (int i = 0; i < n; i++) {
        double w = bw[i];
        if (w > 0) w = 1.0;
        N += w;
    }
    return N / 365.0 / ts;
}

static double m_spearman(const double *o, const double *m, const double *bw, int n, double bv) {
    double *mv = (double *)malloc(n * sizeof(double));
    double *ov = (double *)malloc(n * sizeof(double));
    int cnt = 0;
    for (int i = 0; i < n; i++) {
        if (o[i] != bv && bw[i] > 0) { ov[cnt] = o[i]; mv[cnt] = m[i]; cnt++; }
    }
    double result;
    if (cnt > 1) {
        int *r1 = (int *)malloc(cnt * sizeof(int));
        int *r2 = (int *)malloc(cnt * sizeof(int));
        get_ranks(mv, cnt, r1);
        get_ranks(ov, cnt, r2);
        double m1 = 0, m2 = 0;
        for (int i = 0; i < cnt; i++) { m1 += (double)r1[i] / cnt; m2 += (double)r2[i] / cnt; }
        double std1 = 0, std2 = 0, cv = 0;
        for (int i = 0; i < cnt; i++) {
            std1 += (r1[i] - m1) * (r1[i] - m1) / cnt;
            std2 += (r2[i] - m2) * (r2[i] - m2) / cnt;
            cv += (r1[i] - m1) * (r2[i] - m2) / cnt;
        }
        result = (std1 > 0 && std2 > 0) ? cv / sqrt(std1) / sqrt(std2) : 0.0;
        free(r1); free(r2);
    } else if (cnt > 0) {
        result = 0.0;
    } else {
        result = -ALMOST_INF;
    }
    free(mv); free(ov);
    return result;
}

/* --- Public: compute_metric --- */

double compute_metric(const char *name, int width,
                      const double *obs, const double *mod, const double *bw,
                      int n, double timestep,
                      int start_year, int start_month, int start_day,
                      double blank_val) {
    if (strcmp(name, "NASH_SUTCLIFFE") == 0) return m_nash_sutcliffe(obs, mod, bw, n);
    if (strcmp(name, "DAILY_NSE") == 0) return m_daily_nse(obs, mod, bw, n, timestep);
    if (strcmp(name, "NASH_SUTCLIFFE_DER") == 0) return m_nse_der(obs, mod, bw, n, timestep);
    if (strcmp(name, "NASH_SUTCLIFFE_RUN") == 0) return m_nse_run(obs, mod, bw, n, width);
    if (strcmp(name, "LOG_NASH") == 0) return m_log_nash(obs, mod, bw, n, blank_val);
    if (strcmp(name, "NSE4") == 0) return m_nse4(obs, mod, bw, n);
    if (strcmp(name, "FUZZY_NASH") == 0) return m_fuzzy_nash(obs, mod, bw, n, width);
    if (strcmp(name, "RMSE") == 0) return m_rmse(obs, mod, bw, n);
    if (strcmp(name, "RMSE_DER") == 0) return m_rmse_der(obs, mod, bw, n, timestep);
    if (strcmp(name, "KLING_GUPTA") == 0) return m_kge(obs, mod, bw, n, 0);
    if (strcmp(name, "KGE_PRIME") == 0) return m_kge(obs, mod, bw, n, 1);
    if (strcmp(name, "KLING_GUPTA_DEVIATION") == 0) return m_kge(obs, mod, bw, n, 2);
    if (strcmp(name, "KLING_GUPTA_DER") == 0) return m_kge_der(obs, mod, bw, n, timestep);
    if (strcmp(name, "DAILY_KGE") == 0) return m_daily_kge(obs, mod, bw, n, timestep);
    if (strcmp(name, "PCT_BIAS") == 0) return m_pct_bias(obs, mod, bw, n);
    if (strcmp(name, "ABS_PCT_BIAS") == 0) return m_abs_pct_bias(obs, mod, bw, n);
    if (strcmp(name, "ABSERR") == 0) return m_abserr(obs, mod, bw, n);
    if (strcmp(name, "ABSERR_RUN") == 0) return m_abserr_run(obs, mod, bw, n, width);
    if (strcmp(name, "ABSMAX") == 0) return m_absmax(obs, mod, bw, n);
    if (strcmp(name, "PDIFF") == 0) return m_pdiff(obs, mod, bw, n);
    if (strcmp(name, "PCT_PDIFF") == 0) return m_pct_pdiff(obs, mod, bw, n);
    if (strcmp(name, "ABS_PCT_PDIFF") == 0) return m_abs_pct_pdiff(obs, mod, bw, n);
    if (strcmp(name, "TMVOL") == 0) return m_tmvol(obs, mod, bw, n, start_year, start_month, start_day, timestep);
    if (strcmp(name, "TMVOL_MARE") == 0) return m_tmvol_mare(obs, mod, bw, n, start_year, start_month, start_day, timestep);
    if (strcmp(name, "RCOEF") == 0) return m_rcoef(obs, mod, bw, n);
    if (strcmp(name, "NSC") == 0) return m_nsc(obs, mod, bw, n);
    if (strcmp(name, "RSR") == 0) return m_rsr(obs, mod, bw, n);
    if (strcmp(name, "R2") == 0) return m_r2(obs, mod, bw, n);
    if (strcmp(name, "MBF") == 0) return m_mbf(obs, mod, bw, n);
    if (strcmp(name, "R4MS4E") == 0) return m_r4ms4e(obs, mod, bw, n);
    if (strcmp(name, "RTRMSE") == 0) return m_rtrmse(obs, mod, bw, n);
    if (strcmp(name, "RABSERR") == 0) return m_rabserr(obs, mod, bw, n);
    if (strcmp(name, "PERSINDEX") == 0) return m_persindex(obs, mod, bw, n);
    if (strcmp(name, "YEARS_OF_RECORD") == 0) return m_years_of_record(obs, mod, bw, n, timestep);
    if (strcmp(name, "SPEARMAN") == 0) return m_spearman(obs, mod, bw, n, blank_val);
    return 0.0;
}

#ifdef __cplusplus
}
#endif
