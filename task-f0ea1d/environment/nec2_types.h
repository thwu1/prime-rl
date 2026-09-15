#ifndef NEC2_TYPES_H
#define NEC2_TYPES_H


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <ctype.h>

#define MAX_SEGMENTS 2000
#define MAX_PATTERN  10000
#define MAX_WIRES    200
#define MAX_LINE     512
#define GAIN_SENTINEL -999.0
#define Z0_REF       50.0

typedef struct {
    int tag;
    int seg;
    double v_real, v_imag;
    double i_real, i_imag;
    double z_real, z_imag;
    double y_real, y_imag;
    double power;
} InputParams;

typedef struct {
    int seg_no;
    int tag;
    double x, y, z;
    double seg_length;
    double i_real, i_imag;
    double i_mag, i_phase;
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
    double gain_vert_db;
    double gain_hor_db;
    double gain_total_db;
    double e_theta_mag, e_theta_phase;
    double e_phi_mag, e_phi_phase;
} PatternEntry;

typedef struct {
    double frequency_mhz;
    double wavelength_m;
    InputParams input;
    CurrentEntry currents[MAX_SEGMENTS];
    int n_currents;
    PowerBudget power;
    PatternEntry pattern[MAX_PATTERN];
    int n_pattern;
    double avg_power_gain;
    double solid_angle_factor;
    int total_segments;
    int has_input;
    int has_currents;
    int has_power;
    int has_pattern;
    int has_avg_gain;
} SimRun;

typedef struct {
    int tag;
    int n_segments;
    double x1, y1, z1;
    double x2, y2, z2;
    double radius;
} WireDef;

typedef struct {
    WireDef wires[MAX_WIRES];
    int n_wires;
    int total_segments;
    int ex_type;
    int ex_tag;
    int ex_seg;
    double frequency_mhz;
    int has_frequency;
    int has_excitation;
} DeckData;

typedef struct {
    int segments_match;
    int excitation_match;
    int segments_deck;
    int segments_output;
    int ex_tag_deck, ex_seg_deck;
    int ex_tag_output, ex_seg_output;
} ValidationResult;

#endif
