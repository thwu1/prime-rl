#ifndef NEC2_ANALYZER_H
#define NEC2_ANALYZER_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <ctype.h>

#define MAX_SEGMENTS 1000
#define MAX_PATTERN  5000
#define MAX_LINE     512
#define Z0_REF       50.0


typedef struct {
    int tag, seg;
    double v_real, v_imag;
    double i_real, i_imag;
    double z_real, z_imag;
    double y_real, y_imag;
    double power;
} InputParams;

typedef struct {
    int tag;
    double x, y, z;
    double seg_length;
    double i_real, i_imag, i_mag, i_phase;
} CurrentEntry;

typedef struct {
    double input_power;
    double radiated_power;
    double structure_loss;
    double network_loss;
    double efficiency;
} PowerBudget;

typedef struct {
    double theta, phi;
    double gain_vert_db, gain_hor_db, gain_total_db;
    double e_theta_mag, e_theta_phase;
    double e_phi_mag, e_phi_phase;
} PatternEntry;

typedef struct {
    InputParams input;
    CurrentEntry currents[MAX_SEGMENTS];
    int n_currents;
    PowerBudget power;
    PatternEntry pattern[MAX_PATTERN];
    int n_pattern;
    double avg_power_gain;
    int has_input;
    int has_currents;
    int has_power;
    int has_pattern;
    int has_avg_gain;
} RunData;

#endif
