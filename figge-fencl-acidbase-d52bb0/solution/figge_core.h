#ifndef FIGGE_CORE_H
#define FIGGE_CORE_H


#define MAX_HIST_NB 5
#define MAX_HIST_STD 11
#define MAX_LYS_GROUPS 6

typedef struct {
    /* NB conformational transition */
    double nb_magnitude;
    double nb_midpoint;
    /* Histidine pKa arrays */
    double hist_nb_pka[MAX_HIST_NB];
    double hist_std_pka[MAX_HIST_STD];
    /* Lysine group pKas */
    double lys_pka[MAX_LYS_GROUPS];
    /* Other basic group pKas */
    double arg_pka;
    double nh2_pka;
    /* Acidic group pKas */
    double cooh_pka;
    double asp_glu_pka;
    double cys_pka;
    double tyr_pka;
    /* Phosphate pKas */
    double phos_pka1;
    double phos_pka2;
    double phos_pka3;
    /* CO2 system constants */
    double kc1;
    double kc2;
    double kw;
    double hh_pka;
    double hh_alpha;
    /* Albumin molecular weight in kDa */
    double albumin_mw_kda;
    /* Integer counts */
    int n_hist_nb;
    int n_hist_std;
    int n_lys_groups;
    int lys_count[MAX_LYS_GROUPS];
    int arg_count;
    int nh2_count;
    int cooh_count;
    int asp_glu_count;
    int cys_count;
    int tyr_count;
} FiggeParams;

double figge_albumin_net_charge(double pH, const FiggeParams* p);
double figge_phosphate_charge(double phos_mmol, double pH, const FiggeParams* p);
double figge_solve_ph(double SID, double PCO2, double Pi_mmol,
                      double Alb_gdL, const FiggeParams* p);

#endif
