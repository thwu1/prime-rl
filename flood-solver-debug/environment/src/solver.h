#ifndef SOLVER_H
#define SOLVER_H


#include <vector>
#include <string>
#include <cmath>
#include <cstdlib>
#include <optional>

struct Grid {
    int ncols, nrows;
    double dx;
    double xllcorner, yllcorner;
    double nodata_value;
    std::vector<double> dem;
    std::vector<double> h;
    std::vector<double> Qx;      // x-discharge at cell interfaces [nrows * (ncols+1)]
    std::vector<double> Qy;      // y-discharge at cell interfaces [(nrows+1) * ncols]
    std::vector<double> qx_old;  // previous x-flux per unit width  [nrows * (ncols+1)]
    std::vector<double> qy_old;  // previous y-flux per unit width  [(nrows+1) * ncols]
};

struct GaugePoint {
    int row, col;
    std::string name;
};

struct InflowPoint {
    double time;
    double discharge;
};

struct SimConfig {
    double sim_time;
    double initial_dt;
    double max_dt;
    double manning_n;
    double depth_thresh;
    double cfl;
    double max_hflow;
    double g;
    double theta;
    double output_interval;
    int ps_row, ps_col;
    std::vector<InflowPoint> inflow_hydrograph;
    std::vector<GaugePoint> gauges;
    std::string output_prefix;
    std::optional<std::string> log_file;  // optional diagnostic log path
};

// I/O functions (main.cpp)
Grid read_dem(const std::string& filename);
void write_depth_ascii(const std::string& filename, const Grid& grid);
SimConfig read_config(const std::string& filename);

// Solver functions (solver.cpp)
void compute_fluxes(Grid& grid, const SimConfig& cfg, double dt);
double calc_adaptive_timestep(const Grid& grid, const SimConfig& cfg);
void update_water_depths(Grid& grid, const SimConfig& cfg, double dt);
void copy_new_fluxes_to_old(Grid& grid);
double interpolate_inflow(const SimConfig& cfg, double t);
void apply_point_source(Grid& grid, const SimConfig& cfg, double t, double dt);

// Boundary functions (boundary.cpp)
void enforce_outflow_boundary(Grid& grid);

inline double hmax(double a, double b) { return a > b ? a : b; }
inline double hmin(double a, double b) { return a < b ? a : b; }
inline int cell_idx(int j, int i, int ncols) { return j * ncols + i; }
inline int qx_idx(int j, int i, int ncols) { return j * (ncols + 1) + i; }
inline int qy_idx(int j, int i, int ncols) { return j * ncols + i; }

#endif
