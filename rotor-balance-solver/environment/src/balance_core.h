#ifndef BALANCE_CORE_H
#define BALANCE_CORE_H

typedef struct {
    double mass_kg;
    double angle_deg;
} CorrectionResult;

typedef struct {
    double residual_mr;
    double residual_mrx;
} ResidualResult;

/*
 * Compute correction masses for two-plane rotating balance.
 * known_* arrays have n_known elements.
 * corr1 is the lower axial position correction plane,
 * corr2 is the higher axial position correction plane.
 * Returns 0 on success, -1 on error.
 */
int rotating_balance(
    int n_known,
    const double *known_masses,
    const double *known_radii,
    const double *known_angles_deg,
    const double *known_positions,
    double corr1_position, double corr1_radius,
    double corr2_position, double corr2_radius,
    CorrectionResult *corr1_out,
    CorrectionResult *corr2_out,
    ResidualResult *residual_out
);

/*
 * Compute primary and secondary force/moment resultant magnitudes
 * for an inline reciprocating engine.
 * Returns 0 on success, -1 on error.
 */
int reciprocating_balance(
    int n_cyl,
    const double *masses,
    const double *crank_radii,
    const double *rod_lengths,
    const double *crank_angles_deg,
    const double *axial_positions,
    double ref_plane,
    double *pf_mr,
    double *sf_mr_n,
    double *pm_mrx,
    double *sm_mrx_n
);

/*
 * Compute flywheel energy analysis: mean torque, total energy per cycle,
 * and maximum energy fluctuation via trapezoidal numerical integration.
 * Returns 0 on success, -1 on error.
 */
int flywheel_analysis(
    int n_points,
    const double *angles,
    const double *torques,
    double cycle_angle,
    double *mean_torque,
    double *energy_per_cycle,
    double *max_fluctuation
);

#endif /* BALANCE_CORE_H */
