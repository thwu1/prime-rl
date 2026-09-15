#include "if97_core.h"
#include <math.h>

/* ===================== Region 1 ===================== */
/* IAPWS-IF97 Table 2: 34 polynomial terms for gamma(pi, tau) */

static const int R1_I[34] = {
    0,0,0,0,0,0,0,0,1,1,1,1,1,1,2,2,2,2,2,3,3,3,4,4,4,5,8,8,21,23,29,30,31,32
};
static const int R1_J[34] = {
    -2,-1,0,1,2,3,4,5,-9,-7,-1,0,1,3,-3,0,1,3,17,-4,0,6,-5,-2,10,-8,-11,-6,-29,-31,-38,-39,-40,-41
};
static const double R1_n[34] = {
     0.14632971213167e+00,
    -0.84548187169114e+00,
    -0.37563603672040e+01,
     0.33855169168385e+01,
    -0.95791963387872e+00,
    -0.15772038513228e+00,
    -0.16616417199501e-01,
     0.81214629983568e-03,
     0.28319080123804e-03,
    -0.60706301565874e-03,
    -0.18990068218419e-01,
    -0.32529748770505e-01,
    -0.21841717175414e-01,
    -0.52838357969930e-04,
    -0.47184321073267e-03,
    -0.30001780793026e-03,
     0.47661393906987e-04,
    -0.44141845330846e-05,
    -0.72694996297594e-15,
    -0.31679644845054e-04,
    -0.28270797985312e-05,
    -0.85205128120103e-09,
    -0.22425281908000e-05,
    -0.65171222895601e-06,
    -0.14341729937924e-12,
    -0.40516996860117e-06,
    -0.12734301741641e-08,
    -0.17424871230634e-09,
    -0.68762131295531e-18,
     0.14478307828521e-19,
     0.26335781662795e-22,
    -0.11947622640071e-22,
     0.18228094581404e-23,
    -0.93537087292458e-25
};

void if97_gamma1(double pi, double tau,
                 double *g, double *gp, double *gpp,
                 double *gt, double *gtt, double *gpt)
{
    double t1 = 7.1 - pi;
    double t2 = tau - 1.222;
    double sg = 0, sgp = 0, sgpp = 0;
    double sgt = 0, sgtt = 0, sgpt = 0;
    int k;

    for (k = 0; k < 34; k++) {
        int Ik = R1_I[k];
        int Jk = R1_J[k];
        double nk = R1_n[k];
        double t1_Ik = pow(t1, Ik);
        double t2_Jk = pow(t2, Jk);
        double val = nk * t1_Ik * t2_Jk;

        sg += val;

        if (Ik != 0) {
            double gp_term = -nk * Ik * pow(t1, Ik - 1) * t2_Jk;
            sgp += gp_term;
            if (Ik >= 2)
                sgpp += nk * Ik * (Ik - 1) * pow(t1, Ik - 2) * t2_Jk;
        }
        if (Jk != 0) {
            sgt += nk * Jk * t1_Ik * pow(t2, Jk - 1);
            if (Jk != 0 && Jk != 1)
                sgtt += nk * Jk * (Jk - 1) * t1_Ik * pow(t2, Jk - 2);
        }
        if (Ik != 0 && Jk != 0)
            sgpt += -nk * Ik * Jk * pow(t1, Ik - 1) * pow(t2, Jk - 1);
    }

    *g = sg;
    *gp = sgp;
    *gpp = sgpp;
    *gt = sgt;
    *gtt = sgtt;
    *gpt = sgpt;
}

/* ===================== Region 2 ===================== */
/* Ideal: 9 terms, IAPWS-IF97 Table 10 */

static const int R2_J0[9] = {0, 1, -5, -4, -3, -2, -1, 2, 3};
static const double R2_n0[9] = {
    -0.96927686500217e+01,  0.10086655968018e+02, -0.56087911283020e-02,
     0.71452738081455e-01, -0.40710498223928e+00,  0.14240819171444e+01,
    -0.43839511319450e+01, -0.28408632460772e+00,  0.21268463753307e-01
};

/* Residual: 43 terms, IAPWS-IF97 Table 11 */
static const int R2_Ir[43] = {
    1,1,1,1,1,2,2,2,2,2,3,3,3,3,3,4,4,4,5,6,6,6,7,7,7,8,8,9,10,10,10,16,16,18,20,20,20,21,22,23,24,24,24
};
static const int R2_Jr[43] = {
    0,1,2,3,6,1,2,4,7,36,0,1,3,6,35,1,2,3,7,3,16,35,0,11,25,8,36,13,4,10,14,29,50,57,20,35,48,21,53,39,26,40,58
};
static const double R2_nr[43] = {
    -0.17731742473213e-02,
    -0.17834862292358e-01,
    -0.45996013696365e-01,
    -0.57581259083432e-01,
    -0.50325278727930e-01,
    -0.33032641670203e-04,
    -0.18948987516315e-03,
    -0.39392777243355e-02,
    -0.43797295650573e-01,
    -0.26674547914087e-04,
     0.20481737692309e-07,
     0.43870667284435e-06,
    -0.32277677238570e-04,
    -0.15033924542148e-02,
    -0.40668253562649e-01,
    -0.78847309559367e-09,
     0.12790717852285e-07,
     0.48225372718507e-06,
     0.22922076337661e-05,
    -0.16714766451061e-10,
    -0.21171472321355e-02,
    -0.23895741934104e+02,
    -0.59059564324271e-17,
    -0.12621808899101e-05,
    -0.38946842435739e-01,
     0.11256211360459e-10,
    -0.82198102652998e+01,
     0.19809712802088e-07,
     0.10406965210174e-18,
    -0.10234747095929e-12,
    -0.10018179379512e-08,
    -0.80882908646985e-10,
     0.10693031879409e+00,
    -0.33662250574171e+00,
     0.89185845355421e-24,
     0.30629316876232e-12,
    -0.42002467698208e-05,
    -0.59056029685639e-25,
     0.37826947613457e-05,
    -0.12768608934681e-14,
     0.73087610595061e-28,
     0.55414715350778e-16,
    -0.94369707241210e-06
};

void if97_gamma2_ideal(double pi, double tau,
                       double *g0, double *g0p, double *g0pp,
                       double *g0t, double *g0tt)
{
    double sg0 = log(pi);
    double sg0p = 1.0 / pi;
    double sg0pp = -1.0 / (pi * pi);
    double sg0t = 0;
    double sg0tt = 0;
    int k;

    for (k = 0; k < 9; k++) {
        int J0 = R2_J0[k];
        double n0 = R2_n0[k];
        sg0 += n0 * pow(tau, J0);
        if (J0 != 0) {
            sg0t += n0 * J0 * pow(tau, J0 - 1);
            if (J0 != 1)
                sg0tt += n0 * J0 * (J0 - 1) * pow(tau, J0 - 2);
        }
    }

    *g0 = sg0;
    *g0p = sg0p;
    *g0pp = sg0pp;
    *g0t = sg0t;
    *g0tt = sg0tt;
}

void if97_gamma2_res(double pi, double tau,
                     double *gr, double *grp, double *grpp,
                     double *grt, double *grtt, double *grpt)
{
    double t2 = tau - 0.5;
    double sgr = 0, sgrp = 0, sgrpp = 0;
    double sgrt = 0, sgrtt = 0, sgrpt = 0;
    int k;

    for (k = 0; k < 43; k++) {
        int Ik = R2_Ir[k];
        int Jk = R2_Jr[k];
        double nk = R2_nr[k];
        double pi_Ik = pow(pi, Ik);
        double t2_Jk = pow(t2, Jk);

        sgr += nk * pi_Ik * t2_Jk;
        if (Ik != 0) {
            sgrp += nk * Ik * pow(pi, Ik - 1) * t2_Jk;
            if (Ik >= 2)
                sgrpp += nk * Ik * (Ik - 1) * pow(pi, Ik - 2) * t2_Jk;
        }
        if (Jk != 0) {
            sgrt += nk * Jk * pi_Ik * pow(t2, Jk - 1);
            if (Jk != 1)
                sgrtt += nk * Jk * (Jk - 1) * pi_Ik * pow(t2, Jk - 2);
        }
        if (Ik != 0 && Jk != 0)
            sgrpt += nk * Ik * Jk * pow(pi, Ik - 1) * pow(t2, Jk - 1);
    }

    *gr = sgr;
    *grp = sgrp;
    *grpp = sgrpp;
    *grt = sgrt;
    *grtt = sgrtt;
    *grpt = sgrpt;
}

/* ===================== Saturation ===================== */
static const double SAT_n[11] = {
    0,
    0.11670521452767e+04, -0.72421316703206e+06, -0.17073846940092e+02,
    0.12020824702470e+05, -0.32325550322333e+07,  0.14915108613530e+02,
   -0.48232657361591e+04,  0.40511340542057e+06, -0.23855557567849e+00,
    0.65017534844798e+03
};

double if97_psat_t(double T)
{
    double tita = T + SAT_n[9] / (T - SAT_n[10]);
    double A = tita * tita + SAT_n[1] * tita + SAT_n[2];
    double B = SAT_n[3] * tita * tita + SAT_n[4] * tita + SAT_n[5];
    double C = SAT_n[6] * tita * tita + SAT_n[7] * tita + SAT_n[8];
    double val = 2.0 * C / (-B + sqrt(B * B - 4.0 * A * C));
    return pow(val, 3);
}

double if97_tsat_p(double P)
{
    double beta = pow(P, 0.25);
    double E = beta * beta + SAT_n[3] * beta + SAT_n[6];
    double F = SAT_n[1] * beta * beta + SAT_n[4] * beta + SAT_n[7];
    double G = SAT_n[2] * beta * beta + SAT_n[5] * beta + SAT_n[8];
    double D = 2.0 * G / (-F - sqrt(F * F - 4.0 * E * G));
    return (SAT_n[10] + D - sqrt((SAT_n[10] + D) * (SAT_n[10] + D)
            - 4.0 * (SAT_n[9] + SAT_n[10] * D))) / 2.0;
}

/* ===================== Boundary 2-3 ===================== */
static const double B23_n[3] = {
    0.34805185628969e+03, -0.11671859879975e+01, 0.10192970039326e-02
};

double if97_p23_t(double T)
{
    return B23_n[0] + B23_n[1] * T + B23_n[2] * T * T;
}
