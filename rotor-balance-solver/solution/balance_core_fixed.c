#include "balance_core.h"
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static double deg2rad(double deg) {
    return deg * M_PI / 180.0;
}

static double normalize_angle(double deg) {
    double a = fmod(deg, 360.0);
    if (a < 0.0) a += 360.0;
    return a;
}

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
) {
    double sum_fx = 0.0, sum_fy = 0.0;
    double sum_mx = 0.0, sum_my = 0.0;
    double x_ref = corr1_position;
    double d_other = corr2_position - x_ref;

    if (fabs(d_other) < 1e-12) return -1;

    for (int i = 0; i < n_known; i++) {
        double mr = known_masses[i] * known_radii[i];
        double angle = deg2rad(known_angles_deg[i]);
        double fx = mr * cos(angle);
        double fy = mr * sin(angle);
        double d = known_positions[i] - x_ref;

        sum_fx += fx;
        sum_fy += fy;
        sum_mx += fx * d;
        sum_my += fy * d;
    }

    /* Moment balance about reference plane -> correction at other plane */
    double mr_ox = -sum_mx / d_other;
    double mr_oy = -sum_my / d_other;
    double mass_other = sqrt(mr_ox * mr_ox + mr_oy * mr_oy) / corr2_radius;
    double angle_other = normalize_angle(atan2(mr_oy, mr_ox) * 180.0 / M_PI);

    /* Force balance -> correction at reference plane */
    double mr_rx = -(sum_fx + mr_ox);
    double mr_ry = -(sum_fy + mr_oy);
    double mass_ref = sqrt(mr_rx * mr_rx + mr_ry * mr_ry) / corr1_radius;
    double angle_ref = normalize_angle(atan2(mr_ry, mr_rx) * 180.0 / M_PI);

    corr1_out->mass_kg = mass_ref;
    corr1_out->angle_deg = angle_ref;
    corr2_out->mass_kg = mass_other;
    corr2_out->angle_deg = angle_other;

    /* Compute verification residuals */
    double total_fx = sum_fx + mr_rx + mr_ox;
    double total_fy = sum_fy + mr_ry + mr_oy;
    double total_mx = sum_mx + mr_ox * d_other;
    double total_my = sum_my + mr_oy * d_other;

    residual_out->residual_mr = sqrt(total_fx * total_fx + total_fy * total_fy);
    residual_out->residual_mrx = sqrt(total_mx * total_mx + total_my * total_my);

    return 0;
}

int reciprocating_balance(
    int n_cyl,
    const double *masses,
    const double *crank_radii,
    const double *rod_lengths,
    const double *crank_angles_deg,
    const double *axial_positions,
    double ref_plane,
    double *pf_mr, double *sf_mr_n,
    double *pm_mrx, double *sm_mrx_n
) {
    double pf_x = 0.0, pf_y = 0.0;
    double sf_x = 0.0, sf_y = 0.0;
    double pm_x = 0.0, pm_y = 0.0;
    double sm_x = 0.0, sm_y = 0.0;

    for (int i = 0; i < n_cyl; i++) {
        double m = masses[i];
        double R = crank_radii[i];
        double L = rod_lengths[i];
        double alpha = deg2rad(crank_angles_deg[i]);
        double d = axial_positions[i] - ref_plane;
        double n = L / R;

        double mr = m * R;
        double mr_n = mr / n;

        /* Primary force components at crank angle */
        double px = mr * cos(alpha);
        double py = mr * sin(alpha);

        /* Secondary force components at doubled crank angle */
        double sx = mr_n * cos(2.0 * alpha);
        double sy = mr_n * sin(2.0 * alpha);

        pf_x += px; pf_y += py;
        sf_x += sx; sf_y += sy;
        pm_x += px * d; pm_y += py * d;
        sm_x += sx * d; sm_y += sy * d;
    }

    *pf_mr = sqrt(pf_x * pf_x + pf_y * pf_y);
    *sf_mr_n = sqrt(sf_x * sf_x + sf_y * sf_y);
    *pm_mrx = sqrt(pm_x * pm_x + pm_y * pm_y);
    *sm_mrx_n = sqrt(sm_x * sm_x + sm_y * sm_y);

    return 0;
}

int flywheel_analysis(
    int n_points,
    const double *angles,
    const double *torques,
    double cycle_angle,
    double *mean_torque,
    double *energy_per_cycle,
    double *max_fluctuation
) {
    if (n_points < 2) return -1;

    /* Trapezoidal integration for total work */
    double total_work = 0.0;
    for (int i = 0; i < n_points - 1; i++) {
        double dtheta = angles[i + 1] - angles[i];
        total_work += (torques[i] + torques[i + 1]) / 2.0 * dtheta;
    }

    double mt = total_work / cycle_angle;

    /* Cumulative energy above/below mean */
    double cumulative = 0.0;
    double max_e = 0.0;
    double min_e = 0.0;

    for (int i = 0; i < n_points - 1; i++) {
        double dtheta = angles[i + 1] - angles[i];
        double excess1 = torques[i] - mt;
        double excess2 = torques[i + 1] - mt;
        cumulative += (excess1 + excess2) / 2.0 * dtheta;

        if (cumulative > max_e) max_e = cumulative;
        if (cumulative < min_e) min_e = cumulative;
    }

    *mean_torque = mt;
    *energy_per_cycle = total_work;
    *max_fluctuation = max_e - min_e;

    return 0;
}
