#include "solver.h"
#include <cmath>
#include <algorithm>


// ---------------------------------------------------------------
// Compute x-direction flux at interface between cell (j,i-1) and (j,i).
// Returns total discharge Q [m^3/s], positive eastward.
// Uses the local inertial formulation with q-centered weighting.
// ---------------------------------------------------------------
static double flux_x(int j, int i, Grid& grid, const SimConfig& cfg, double dt)
{
    int nc = grid.ncols;
    int p0 = cell_idx(j, i - 1, nc);
    int p1 = cell_idx(j, i, nc);

    double z0 = grid.dem[p0], z1 = grid.dem[p1];
    double h0 = grid.h[p0],   h1 = grid.h[p1];
    double q0 = grid.qx_old[qx_idx(j, i, nc)];
    double g  = cfg.g;
    double fn = cfg.manning_n;

    double y0 = z0 + h0;
    double y1 = z1 + h1;
    double dh = y0 - y1;
    double Sf = -dh / grid.dx;

    // Effective flow depth at the interface
    double hflow = hmax(y0, y1) - hmax(z0, z1);
    hflow = hmax(hflow, 0.0);
    hflow = hmin(hflow, cfg.max_hflow);

    if (hflow <= cfg.depth_thresh) return 0.0;

    // Neighbouring old fluxes for the q-centered weighting
    double qup   = grid.qx_old[qx_idx(j, i - 1, nc)];
    double qdown = grid.qx_old[qx_idx(j, i + 1, nc)];
    double theta = cfg.theta;

    // Friction denominator
    double denom = 1.0 + g * dt * hflow * fn * fabs(q0)
                   / pow(hflow, 7.0 / 3.0);

    // Q-centered scheme
    double Q_num = (theta * q0 + 0.5 * (1.0 - theta) * (qup + qdown))
                   - g * dt * hflow * Sf;
    double Q = Q_num / denom * grid.dx;

    // Stability correction: zero out flux opposing head gradient
    if (Q * dh < 0.0) {
        Q = 0.0;
    }

    return Q;
}

// ---------------------------------------------------------------
// Compute y-direction flux at interface between cell (j-1,i) and (j,i).
// Returns total discharge Q [m^3/s], positive southward.
// ---------------------------------------------------------------
static double flux_y(int j, int i, Grid& grid, const SimConfig& cfg, double dt)
{
    int nc = grid.ncols;
    int p0 = cell_idx(j - 1, i, nc);
    int p1 = cell_idx(j, i, nc);

    double z0 = grid.dem[p0], z1 = grid.dem[p1];
    double h0 = grid.h[p0],   h1 = grid.h[p1];
    double q0 = grid.qy_old[qy_idx(j, i, nc)];
    double g  = cfg.g;
    double fn = cfg.manning_n;

    double y0 = z0 + h0;
    double y1 = z1 + h1;
    double dh = y0 - y1;
    double Sf = -dh / grid.dx;

    double hflow = hmax(y0, y1) - hmax(z0, z1);
    hflow = hmax(hflow, 0.0);
    hflow = hmin(hflow, cfg.max_hflow);

    if (hflow <= cfg.depth_thresh) return 0.0;

    double qup   = grid.qy_old[qy_idx(j - 1, i, nc)];
    double qdown = grid.qy_old[qy_idx(j + 1, i, nc)];
    double theta = cfg.theta;

    double denom = 1.0 + g * dt * hflow * fn * fabs(q0)
                   / pow(hflow, 7.0 / 3.0);

    double Q_num = (theta * q0 + 0.5 * (1.0 - theta) * (qup + qdown))
                   - g * dt * hflow * Sf;
    double Q = Q_num / denom * grid.dx;

    // Stability correction: zero out flux opposing head gradient
    if (Q * dh < 0.0) {
        Q = 0.0;
    }

    return Q;
}

// ---------------------------------------------------------------
// Compute all inter-cell fluxes
// ---------------------------------------------------------------
void compute_fluxes(Grid& grid, const SimConfig& cfg, double dt)
{
    int nc = grid.ncols, nr = grid.nrows;

    std::fill(grid.Qx.begin(), grid.Qx.end(), 0.0);
    std::fill(grid.Qy.begin(), grid.Qy.end(), 0.0);

    // Interior x-fluxes (interfaces 1 .. ncols-1)
    for (int j = 0; j < nr; j++) {
        for (int i = 1; i < nc; i++) {
            if (grid.h[cell_idx(j, i - 1, nc)] > cfg.depth_thresh ||
                grid.h[cell_idx(j, i, nc)]     > cfg.depth_thresh)
            {
                grid.Qx[qx_idx(j, i, nc)] = flux_x(j, i, grid, cfg, dt);
            }
        }
    }

    // Interior y-fluxes (interfaces 1 .. nrows-1)
    for (int j = 1; j < nr; j++) {
        for (int i = 0; i < nc; i++) {
            if (grid.h[cell_idx(j - 1, i, nc)] > cfg.depth_thresh ||
                grid.h[cell_idx(j, i, nc)]     > cfg.depth_thresh)
            {
                grid.Qy[qy_idx(j, i, nc)] = flux_y(j, i, grid, cfg, dt);
            }
        }
    }
}

// ---------------------------------------------------------------
// Adaptive CFL time-step based on maximum water depth
// ---------------------------------------------------------------
double calc_adaptive_timestep(const Grid& grid, const SimConfig& cfg)
{
    double max_h = 0.0;
    int n = grid.nrows * grid.ncols;
    for (int k = 0; k < n; k++) {
        if (grid.h[k] > max_h) max_h = grid.h[k];
    }

    double dt;
    if (max_h > cfg.depth_thresh) {
        dt = cfg.cfl * grid.dx / (sqrt(cfg.g) * max_h);
    } else {
        dt = cfg.initial_dt;
    }
    return hmin(dt, cfg.max_dt);
}

// ---------------------------------------------------------------
// Update water depths from flux divergence (continuity equation)
// ---------------------------------------------------------------
void update_water_depths(Grid& grid, const SimConfig& cfg, double dt)
{
    int nc = grid.ncols, nr = grid.nrows;
    double dA = grid.dx * grid.dx;

    for (int j = 0; j < nr; j++) {
        for (int i = 0; i < nc; i++) {
            int p = cell_idx(j, i, nc);

            // Volume change: sum of fluxes into the cell
            //   x: Qx[left] - Qx[right]   (in from west, out to east)
            //   y: Qy[top]  - Qy[bottom]   (in from north, out to south)
            double dV = dt * (
                grid.Qx[qx_idx(j, i, nc)]     - grid.Qx[qx_idx(j, i + 1, nc)]
              + grid.Qy[qy_idx(j + 1, i, nc)] - grid.Qy[qy_idx(j, i, nc)]
            );

            grid.h[p] += dV / dA;
            if (grid.h[p] < 0.0) grid.h[p] = 0.0;
        }
    }
}

// ---------------------------------------------------------------
// Copy current-step discharges to old flux arrays (unit: m^2/s)
// ---------------------------------------------------------------
void copy_new_fluxes_to_old(Grid& grid)
{
    int nc = grid.ncols, nr = grid.nrows;
    double dx_inv = 1.0 / grid.dx;

    for (int j = 0; j < nr; j++)
        for (int i = 0; i <= nc; i++)
            grid.qx_old[qx_idx(j, i, nc)] = grid.Qx[qx_idx(j, i, nc)] * dx_inv;

    for (int j = 0; j <= nr; j++)
        for (int i = 0; i < nc; i++)
            grid.qy_old[qy_idx(j, i, nc)] = grid.Qy[qy_idx(j, i, nc)] * dx_inv;
}

// ---------------------------------------------------------------
// Linearly interpolate inflow discharge at time t
// ---------------------------------------------------------------
double interpolate_inflow(const SimConfig& cfg, double t)
{
    const auto& hyd = cfg.inflow_hydrograph;
    if (hyd.empty()) return 0.0;
    if (t <= hyd.front().time) return hyd.front().discharge;
    if (t >= hyd.back().time)  return hyd.back().discharge;

    for (size_t k = 0; k + 1 < hyd.size(); k++) {
        if (t >= hyd[k].time && t <= hyd[k + 1].time) {
            double frac = (t - hyd[k].time) / (hyd[k + 1].time - hyd[k].time);
            return hyd[k].discharge + frac * (hyd[k + 1].discharge - hyd[k].discharge);
        }
    }
    return 0.0;
}

// ---------------------------------------------------------------
// Inject point-source discharge as a depth increment
// ---------------------------------------------------------------
void apply_point_source(Grid& grid, const SimConfig& cfg, double t, double dt)
{
    double Q = interpolate_inflow(cfg, t);
    if (Q <= 0.0) return;
    int p = cell_idx(cfg.ps_row, cfg.ps_col, grid.ncols);
    double dA = grid.dx * grid.dx;
    grid.h[p] += Q * dt / dA;
}
