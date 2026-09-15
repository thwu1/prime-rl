#ifndef ANTENNA_METRICS_H
#define ANTENNA_METRICS_H

#include "nec2_types.h"

double compute_vswr(double z_real, double z_imag);
void find_max_gain(const PatternEntry *pat, int n, double *max_db, double *max_theta);
double compute_hpbw(const PatternEntry *pat, int n);
ValidationResult validate_deck_vs_output(const DeckData *deck, const SimRun *run);

#endif
