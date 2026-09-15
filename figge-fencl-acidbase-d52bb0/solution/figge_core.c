
#include "figge_core.h"
#include <math.h>

double figge_albumin_net_charge(double pH, const FiggeParams* p) {
    /* N-to-B conformational transition: shifts domain-1 histidine pKa down */
    double NB = p->nb_magnitude *
                (1.0 - 1.0 / (1.0 + pow(10.0, pH - p->nb_midpoint)));

    double net = 0.0;

    /* 16 Histidine residues: domain-1 (NB-shifted) + standard */
    for (int i = 0; i < p->n_hist_nb; i++)
        net += 1.0 / (1.0 + pow(10.0, pH - (p->hist_nb_pka[i] - NB)));
    for (int i = 0; i < p->n_hist_std; i++)
        net += 1.0 / (1.0 + pow(10.0, pH - p->hist_std_pka[i]));

    /* 59 Lysine residues in 6 sub-groups */
    for (int i = 0; i < p->n_lys_groups; i++)
        net += (double)p->lys_count[i] /
               (1.0 + pow(10.0, pH - p->lys_pka[i]));

    /* 24 Arginine */
    net += (double)p->arg_count / (1.0 + pow(10.0, pH - p->arg_pka));

    /* Alpha amino terminus */
    net += (double)p->nh2_count / (1.0 + pow(10.0, pH - p->nh2_pka));

    /* Acidic groups: deprotonated form carries -1 charge */
    net -= (double)p->cooh_count / (1.0 + pow(10.0, p->cooh_pka - pH));
    net -= (double)p->asp_glu_count / (1.0 + pow(10.0, p->asp_glu_pka - pH));
    net -= (double)p->cys_count / (1.0 + pow(10.0, p->cys_pka - pH));
    net -= (double)p->tyr_count / (1.0 + pow(10.0, p->tyr_pka - pH));

    return net;
}

double figge_phosphate_charge(double phos_mmol, double pH,
                              const FiggeParams* p) {
    if (phos_mmol <= 0.0) return 0.0;

    double K1 = pow(10.0, -p->phos_pka1);
    double K2 = pow(10.0, -p->phos_pka2);
    double K3 = pow(10.0, -p->phos_pka3);
    double H  = pow(10.0, -pH);

    double d = H*H*H + K1*H*H + K1*K2*H + K1*K2*K3;
    double z = (K1*H*H + 2.0*K1*K2*H + 3.0*K1*K2*K3) / d;
    return phos_mmol * z;
}

double figge_solve_ph(double SID, double PCO2, double Pi_mmol,
                      double Alb_gdL, const FiggeParams* p) {
    double alb_mM = (Alb_gdL > 0.0)
                    ? (Alb_gdL * 10.0 / p->albumin_mw_kda)
                    : 0.0;

    double low = 1.0, high = 14.0;

    for (int iter = 0; iter < 200; iter++) {
        double mid = (low + high) / 2.0;
        double H = pow(10.0, -mid);

        /* Water dissociation */
        double water = H - p->kw / H;

        /* CO2-bicarbonate-carbonate system */
        double hco3_c = p->kc1 * PCO2 / H;
        double co3_c  = p->kc2 * hco3_c / H;

        /* Phosphate anionic contribution (mEq/L) */
        double pi_c = figge_phosphate_charge(Pi_mmol, mid, p);

        /* Albumin anionic contribution (mEq/L) */
        double alb_c = 0.0;
        if (Alb_gdL > 0.0) {
            double net = figge_albumin_net_charge(mid, p);
            alb_c = -net * alb_mM;
        }

        /* Electroneutrality: all terms in mEq/L */
        double nc = SID + 1000.0 * (water - hco3_c - co3_c)
                    - pi_c - alb_c;

        if (fabs(nc) < 1e-7) return mid;
        if (nc > 0.0) low = mid;
        else high = mid;
    }

    return (low + high) / 2.0;
}
