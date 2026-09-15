/*
 * if97_core.c - IAPWS-IF97 forward property equations
 * Ported from reference implementation.
 *
 */

#include <math.h>
#include "if97_core.h"

static const double R = 0.461526;    /* kJ/(kg*K) */
static const double TC = 647.096;    /* K */
static const double PC = 22.064;     /* MPa */
static const double RHOC = 322.0;    /* kg/m^3 */

/* ================================================================
 * Saturation curve (Eqs 30, 31)
 * ================================================================ */
static const double nsat[10] = {
     0.11670521452767e4,
    -0.72421316703206e6,
    -0.17073846940092e2,
     0.12020824702470e5,
    -0.32325550322333e7,
     0.14915108613530e2,
    -0.48232657361591e4,
     0.40511340542057e6,
     0.65017534844798e3,
    -0.23855557567849e0
};

double saturation_pressure(double T) {
    const double *n = nsat;
    double th = T + n[8] / (T - n[9]);
    double A = th*th + n[0]*th + n[1];
    double B = n[2]*th*th + n[3]*th + n[4];
    double C = n[5]*th*th + n[6]*th + n[7];
    return pow(2.0*C / (-B + sqrt(B*B - 4.0*A*C)), 4);
}

double saturation_temperature(double p) {
    const double *n = nsat;
    double b = pow(p, 0.25);
    double E = b*b + n[2]*b + n[5];
    double F = n[0]*b*b + n[3]*b + n[6];
    double G = n[1]*b*b + n[4]*b + n[7];
    double D = 2.0*G / (-F - sqrt(F*F - 4.0*E*G));
    return (n[9] + D - sqrt((n[9]+D)*(n[9]+D) - 4.0*(n[8] + n[9]*D))) / 2.0;
}

/* ================================================================
 * B23 boundary
 * ================================================================ */
static double b23_p(double T) {
    return 348.05185628969 - 1.1671859879975*T + 0.0010192970039326*T*T;
}

/* ================================================================
 * Region detection
 * ================================================================ */
int determine_region(double T, double p) {
    if (T > 1073.15 && T <= 2273.15 && p > 0 && p <= 50)
        return 5;
    if (T > 1073.15 || T < 273.15 || p <= 0 || p > 100)
        return -1;
    if (T <= 623.15) {
        double ps = saturation_pressure(T);
        return (p > ps) ? 1 : 2;
    }
    return (p > b23_p(T)) ? 3 : 2;
}

/* ================================================================
 * Region 1 (Eq 7) - Gibbs free energy
 * pi = p/16.53, tau = 1386/T, gamma(pi-7.1, tau-1.222)
 * ================================================================ */
#define N_R1 34
static const int r1_I[N_R1] = {
    0,0,0,0,0,0,0,0,
    1,1,1,1,1,1,
    2,2,2,2,2,
    3,3,3,
    4,4,4,
    5,
    8,8,
    21,23,29,30,31,32
};
static const int r1_J[N_R1] = {
    -2,-1,0,1,2,3,4,5,
    -9,-7,-1,0,1,3,
    -3,0,1,3,17,
    -4,0,6,
    -5,-2,10,
    -8,
    -11,-6,
    -29,-31,-38,-39,-40,-41
};
static const double r1_n[N_R1] = {
     0.14632971213167e0,
    -0.84548187169114e0,
    -3.756360367204e0,
     3.3855169168385e0,
    -0.95791963387872e0,
     0.15772038513228e0,
    -0.016616417199501e0,
     0.00081214629983568e0,
    -0.00028319080123804e0,
     0.00060706301565874e0,
     0.018990068218419e0,
     0.032529748770505e0,
    -0.021841717175414e0,
     0.00005283835796993e0,
    -0.00047184321073267e0,
    -0.00030001780793026e0,
     0.000047661393906987e0,
    -4.4141845330846e-06,
    -7.2694996297594e-16,
     0.000031679644845054e0,
     2.8270797985312e-06,
     8.5205128120103e-10,
    -2.2425281908e-06,
    -6.5171222895601e-07,
    -1.4341729937924e-13,
     4.0516996860117e-07,
    -1.2734301741641e-09,
    -1.7424871230634e-10,
     6.8762131295531e-19,
    -1.4478307828521e-20,
    -2.6335781662795e-23,
    -1.1947622640071e-23,
    -1.8228094581404e-24,
    -9.3537087292458e-26
};

IF97Props region1_props(double T, double p) {
    double tau = 1386.0 / T;
    double pi = p / 16.53;
    double pr = pi - 7.1;
    double tr = tau - 1.222;
    double g=0, gp=0, gpp=0, gt=0, gtt=0, gpt=0;
    int k;
    for (k = 0; k < N_R1; k++) {
        int I = r1_I[k], J = r1_J[k];
        double n = r1_n[k];
        double pI = (I == 0) ? 1.0 : pow(pr, I);
        double tJ = (J == 0) ? 1.0 : pow(tr, J);
        g += n * pI * tJ;
        if (I >= 1) gp += n * I * pow(pr, I-1) * tJ;
        if (I >= 2) gpp += n * I * (I-1) * pow(pr, I-2) * tJ;
        if (J != 0) gt += n * pI * J * pow(tr, J-1);
        if (J != 0 && J != 1) gtt += n * pI * J * (J-1) * pow(tr, J-2);
        if (I >= 1 && J != 0) gpt += n * I * pow(pr, I-1) * J * pow(tr, J-1);
    }
    IF97Props res;
    res.v = pi * gp * R * T / p / 1000.0;
    res.h = tau * gt * R * T;
    res.s = R * (tau * gt - g);
    res.cp = -R * tau * tau * gtt;
    double tmp = gp - tau * gpt;
    res.w = sqrt(R * T * 1000.0 * gp * gp / (tmp * tmp / (tau * tau * gtt) - gpp));
    res.u = res.h - p * res.v * 1000.0;
    res.p = p;
    return res;
}

/* ================================================================
 * Region 2 (Eqs 15-17) - Gibbs free energy
 * pi = p (MPa), tau = 540/T
 * ================================================================ */
#define N_R2O 9
static const int r2o_J[N_R2O] = {0, 1, -5, -4, -3, -2, -1, 2, 3};
static const double r2o_n[N_R2O] = {
    -9.6927686500217e0,
     10.086655968018e0,
    -0.0056087911283020e0,
     0.071452738081455e0,
    -0.40710498223928e0,
     1.4240819171444e0,
    -4.3839511319450e0,
    -0.28408632460772e0,
     0.021268463753307e0
};

#define N_R2R 43
static const int r2r_I[N_R2R] = {
    1,1,1,1,1,
    2,2,2,2,2,
    3,3,3,3,3,
    4,4,4,
    5,
    6,6,6,
    7,7,7,
    8,8,
    9,
    10,10,10,
    16,16,
    18,
    20,20,20,
    21,
    22,
    23,
    24,24,24
};
static const int r2r_J[N_R2R] = {
    0,1,2,3,6,
    1,2,4,7,36,
    0,1,3,6,35,
    1,2,3,
    7,
    3,16,35,
    0,11,25,
    8,36,
    13,
    4,10,14,
    29,50,
    57,
    20,35,48,
    21,
    53,
    39,
    26,40,58
};
static const double r2r_n[N_R2R] = {
    -0.0017731742473213e0,
    -0.017834862292358e0,
    -0.045996013696365e0,
    -0.057581259083432e0,
     0.05032527872793e0,
    -0.000033032641670203e0,
    -0.00018948987516315e0,
    -0.0039392777243355e0,
    -0.043797295650573e0,
    -0.000026674547914087e0,
     2.0481737692309e-08,
     4.3870667284435e-07,
    -0.00003227767723857e0,
    -0.0015033924542148e0,
    -0.040668253562649e0,
    -7.8847309559367e-10,
     1.2790717852285e-08,
     4.8225372718507e-07,
     2.2922076337661e-06,
    -1.6714766451061e-11,
    -0.0021171472321355e0,
    -23.895741934104e0,
    -5.905956432427e-18,
    -1.2621808899101e-06,
    -0.038946842435739e0,
     1.1256211360459e-11,
    -8.2311340897998e0,
     1.9809712802088e-08,
     1.0406965210174e-19,
    -1.0234747095929e-13,
    -1.0018179379511e-09,
    -8.0882908646985e-11,
     0.10693031879409e0,
    -0.33662250574171e0,
     8.9185845355421e-25,
     3.0629316876232e-13,
    -4.2002467698208e-06,
    -5.9056029685639e-26,
     3.7826947613457e-06,
    -1.2768608934681e-15,
     7.3087610595061e-29,
     5.5414715350778e-17,
    -9.436970724121e-07
};

IF97Props region2_props(double T, double p) {
    double tau = 540.0 / T;
    double pi = p;
    /* Ideal part */
    double go = log(pi), gop = 1.0/pi, gopp = -1.0/(pi*pi);
    double got = 0, gott = 0;
    int k;
    for (k = 0; k < N_R2O; k++) {
        int J = r2o_J[k];
        double n = r2o_n[k];
        go += n * pow(tau, J);
        if (J != 0) got += n * J * pow(tau, J-1);
        if (J != 0 && J != 1) gott += n * J * (J-1) * pow(tau, J-2);
    }
    /* Residual part */
    double tr = tau - 0.5;
    double gr=0, grp=0, grpp=0, grt=0, grtt=0, grpt=0;
    for (k = 0; k < N_R2R; k++) {
        int I = r2r_I[k], J = r2r_J[k];
        double n = r2r_n[k];
        double pI = pow(pi, I);
        double tJ = (J == 0) ? 1.0 : pow(tr, J);
        gr += n * pI * tJ;
        grp += n * I * pow(pi, I-1) * tJ;
        if (I >= 2) grpp += n * I * (I-1) * pow(pi, I-2) * tJ;
        if (J != 0) grt += n * pI * J * pow(tr, J-1);
        if (J != 0 && J != 1) grtt += n * pI * J * (J-1) * pow(tr, J-2);
        if (J != 0) grpt += n * I * pow(pi, I-1) * J * pow(tr, J-1);
    }
    double gp_t = gop+grp, gpp_t = gopp+grpp;
    double gt_t = got+grt, gtt_t = gott+grtt, gpt_t = grpt;

    IF97Props res;
    res.v = pi * gp_t * R * T / p / 1000.0;
    res.h = tau * gt_t * R * T;
    res.s = R * (tau * gt_t - (go + gr));
    res.cp = -R * tau * tau * gtt_t;
    double tmp = gp_t - tau * gpt_t;
    res.w = sqrt(R * T * 1000.0 * gp_t * gp_t / (tmp * tmp / (tau * tau * gtt_t) - gpp_t));
    res.u = res.h - p * res.v * 1000.0;
    res.p = p;
    return res;
}

/* ================================================================
 * Region 3 (Eq 28) - Helmholtz free energy
 * delta = rho/rhoc, tau = Tc/T
 * ================================================================ */
#define N_R3 40
static const int r3_I[N_R3] = {
    0,0,0,0,0,0,0,0,
    1,1,1,1,
    2,2,2,2,2,2,
    3,3,3,3,3,
    4,4,4,4,
    5,5,5,
    6,6,6,
    7,
    8,
    9,9,
    10,10,
    11
};
static const int r3_J[N_R3] = {
    0,0,1,2,7,10,12,23,
    2,6,15,17,
    0,2,6,7,22,26,
    0,2,4,16,26,
    0,2,4,26,
    1,3,26,
    0,2,26,
    2,
    26,
    2,26,
    0,1,
    26
};
static const double r3_n[N_R3] = {
     0.10658070028513e1,
    -0.15732845290239e2,
     0.20944396974307e2,
    -0.76867707878716e1,
     0.26185947787954e1,
    -0.28080781148620e1,
     0.12053369696517e1,
    -0.84566812812502e-2,
    -0.12654315477714e1,
    -0.11524407806681e1,
     0.88521043984318e0,
    -0.64207765181607e0,
     0.38493460186671e0,
    -0.85214708824206e0,
     0.48972281541877e1,
    -0.30502617256965e1,
     0.39420536879154e-1,
     0.12558408424308e0,
    -0.27999329698710e0,
     0.13899799569460e1,
    -0.20189915023570e1,
    -0.82147637173963e-2,
    -0.47596035734923e0,
     0.43984074473500e-1,
    -0.44476435428739e0,
     0.90572070719733e0,
     0.70522450087967e0,
     0.10770512626332e0,
    -0.32913623258954e0,
    -0.50871062041158e0,
    -0.22175400873096e-1,
     0.94260751665092e-1,
     0.16436278447961e0,
    -0.13503372241348e-1,
    -0.14834345352472e-1,
     0.57922953628084e-3,
     0.32308904703711e-2,
     0.80964802996215e-4,
    -0.16557679795037e-3,
    -0.44923899061815e-4
};

IF97Props region3_props(double T, double rho) {
    double delta = rho / RHOC;
    double tau = T / TC;
    /* First coefficient is special: n1*ln(delta) */
    double n1 = r3_n[0];
    double f = n1 * log(delta);
    double fd = n1 / delta;
    double fdd = -n1 / (delta * delta);
    double ft = 0, ftt = 0, fdt = 0;
    int k;
    for (k = 1; k < N_R3; k++) {
        int I = r3_I[k], J = r3_J[k];
        double n = r3_n[k];
        double dI = (I == 0) ? 1.0 : pow(delta, I);
        double tJ = (J == 0) ? 1.0 : pow(tau, J);
        f += n * dI * tJ;
        if (I >= 1) fd += n * I * pow(delta, I-1) * tJ;
        if (I >= 2) fdd += n * I * (I-1) * pow(delta, I-2) * tJ;
        if (J >= 1) ft += n * dI * J * pow(tau, J-1);
        if (J >= 2) ftt += n * dI * J * (J-1) * pow(tau, J-2);
        if (I >= 1 && J >= 1) fdt += n * I * pow(delta, I-1) * J * pow(tau, J-1);
    }
    IF97Props res;
    res.p = delta * fd * rho * R * T / 1000.0;
    res.v = 1.0 / rho;
    res.u = tau * ft * R * T;
    res.h = (tau * ft + delta * fd) * R * T;
    res.s = R * (tau * ft - f);
    double cv = -R * tau * tau * ftt;
    double dfd = delta * fd - delta * tau * fdt;
    res.cp = cv + R * dfd * dfd / (2.0 * delta * fd + delta * delta * fdd);
    res.w = sqrt(R * T * 1000.0 * (2.0*delta*fd + delta*delta*fdd
            - dfd * dfd / (tau * tau * ftt)));
    return res;
}

/* ================================================================
 * Region 5 (Eqs 32-34) - Gibbs free energy
 * pi = p (MPa), tau = 1000/T
 * ================================================================ */
#define N_R5O 6
static const int r5o_J[N_R5O] = {0, 1, -3, -2, -1, 2};
static const double r5o_n[N_R5O] = {
    -13.179983674201e0,
      6.8540841634434e0,
    -0.024805148933466e0,
     0.36901534980333e0,
    -3.1161318213925e0,
    -0.32961626538917e0
};

#define N_R5R 6
static const int r5r_I[N_R5R] = {1,1,1,2,2,3};
static const int r5r_J[N_R5R] = {1,2,3,3,9,7};
static const double r5r_n[N_R5R] = {
     0.0015736404855259e0,
     0.00090153761673944e0,
    -0.0050270077677648e0,
     0.0000022440037409485e0,
    -0.0000041163275453471e0,
     3.7919454822955e-08
};

IF97Props region5_props(double T, double p) {
    double tau = 1000.0 / T;
    double pi = p;
    double go = log(pi), gop = 1.0/pi, gopp = -1.0/(pi*pi);
    double got = 0, gott = 0;
    int k;
    for (k = 0; k < N_R5O; k++) {
        int J = r5o_J[k];
        double n = r5o_n[k];
        go += n * pow(tau, J);
        if (J != 0) got += n * J * pow(tau, J-1);
        if (J != 0 && J != 1) gott += n * J * (J-1) * pow(tau, J-2);
    }
    double gr=0, grp=0, grpp=0, grt=0, grtt=0, grpt=0;
    for (k = 0; k < N_R5R; k++) {
        int I = r5r_I[k], J = r5r_J[k];
        double n = r5r_n[k];
        double pI = pow(pi, I);
        double tJ = pow(tau, J);
        gr += n * pI * tJ;
        grp += n * I * pow(pi, I-1) * tJ;
        if (I >= 2) grpp += n * I * (I-1) * pow(pi, I-2) * tJ;
        grt += n * pI * J * pow(tau, J-1);
        if (J >= 2) grtt += n * pI * J * (J-1) * pow(tau, J-2);
        grpt += n * I * pow(pi, I-1) * J * pow(tau, J-1);
    }
    double gp_t = gop+grp, gpp_t = gopp+grpp;
    double gt_t = got+grt, gtt_t = gott+grtt, gpt_t = grpt;

    IF97Props res;
    res.v = pi * gp_t * R * T / p / 1000.0;
    res.h = tau * gt_t * R * T;
    res.s = R * (tau * gt_t - (go + gr));
    res.cp = -R * tau * tau * gtt_t;
    double tmp = gp_t - tau * gpt_t;
    res.w = sqrt(R * T * 1000.0 * gp_t * gp_t / (tmp * tmp / (tau * tau * gtt_t) - gpp_t));
    res.u = res.h - p * res.v * 1000.0;
    res.p = p;
    return res;
}
