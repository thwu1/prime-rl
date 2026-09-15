#include "solver.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <iomanip>
#include <cstdlib>


// ---------------------------------------------------------------
// Read an ESRI ASCII raster file
// ---------------------------------------------------------------
Grid read_dem(const std::string& filename)
{
    Grid grid;
    std::ifstream f(filename);
    if (!f.is_open()) {
        std::cerr << "ERROR: cannot open DEM file: " << filename << std::endl;
        std::exit(1);
    }

    std::string key;
    f >> key >> grid.ncols;
    f >> key >> grid.nrows;
    f >> key >> grid.xllcorner;
    f >> key >> grid.yllcorner;
    f >> key >> grid.dx;
    f >> key >> grid.nodata_value;

    int n = grid.nrows * grid.ncols;
    grid.dem.resize(n);
    for (int k = 0; k < n; k++) {
        f >> grid.dem[k];
    }
    f.close();

    // Initialise water depth and flux arrays to zero
    grid.h.assign(n, 0.0);
    grid.Qx.assign(grid.nrows * (grid.ncols + 1), 0.0);
    grid.Qy.assign((grid.nrows + 1) * grid.ncols, 0.0);
    grid.qx_old.assign(grid.nrows * (grid.ncols + 1), 0.0);
    grid.qy_old.assign((grid.nrows + 1) * grid.ncols, 0.0);

    return grid;
}

// ---------------------------------------------------------------
// Write water depth as an ESRI ASCII raster
// ---------------------------------------------------------------
void write_depth_ascii(const std::string& filename, const Grid& grid)
{
    std::ofstream f(filename);
    f << "ncols " << grid.ncols << "\n";
    f << "nrows " << grid.nrows << "\n";
    f << std::fixed << std::setprecision(6);
    f << "xllcorner " << grid.xllcorner << "\n";
    f << "yllcorner " << grid.yllcorner << "\n";
    f << "cellsize " << grid.dx << "\n";
    f << "NODATA_value " << grid.nodata_value << "\n";

    for (int j = 0; j < grid.nrows; j++) {
        for (int i = 0; i < grid.ncols; i++) {
            if (i > 0) f << " ";
            f << grid.h[cell_idx(j, i, grid.ncols)];
        }
        f << "\n";
    }
    f.close();
}

// ---------------------------------------------------------------
// Read simulation configuration
// ---------------------------------------------------------------
SimConfig read_config(const std::string& filename)
{
    SimConfig cfg;
    // Defaults
    cfg.sim_time = 1800.0;
    cfg.initial_dt = 1.0;
    cfg.max_dt = 10.0;
    cfg.manning_n = 0.035;
    cfg.depth_thresh = 1e-3;
    cfg.cfl = 0.7;
    cfg.max_hflow = 10.0;
    cfg.g = 9.81;
    cfg.theta = 0.9;
    cfg.output_interval = 60.0;
    cfg.ps_row = 0;
    cfg.ps_col = 0;
    cfg.output_prefix = "results";

    std::ifstream f(filename);
    if (!f.is_open()) {
        std::cerr << "ERROR: cannot open config file: " << filename << std::endl;
        std::exit(1);
    }

    std::string line;
    while (std::getline(f, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream iss(line);
        std::string token;
        iss >> token;

        if (token == "sim_time")         iss >> cfg.sim_time;
        else if (token == "initial_dt")  iss >> cfg.initial_dt;
        else if (token == "max_dt")      iss >> cfg.max_dt;
        else if (token == "manning_n")   iss >> cfg.manning_n;
        else if (token == "depth_thresh") iss >> cfg.depth_thresh;
        else if (token == "cfl")         iss >> cfg.cfl;
        else if (token == "max_hflow")   iss >> cfg.max_hflow;
        else if (token == "g")           iss >> cfg.g;
        else if (token == "theta")       iss >> cfg.theta;
        else if (token == "output_interval") iss >> cfg.output_interval;
        else if (token == "output_prefix")   iss >> cfg.output_prefix;
        else if (token == "log_file") {
            std::string lf;
            if (iss >> lf) {
                cfg.log_file = lf;
            }
        }
        else if (token == "point_source") {
            iss >> cfg.ps_row >> cfg.ps_col;
        }
        else if (token == "inflow_start") {
            cfg.inflow_hydrograph.clear();
            while (std::getline(f, line)) {
                if (line.find("inflow_end") != std::string::npos) break;
                if (line.empty() || line[0] == '#') continue;
                std::istringstream iss2(line);
                InflowPoint pt;
                iss2 >> pt.time >> pt.discharge;
                cfg.inflow_hydrograph.push_back(pt);
            }
        }
        else if (token == "gauge") {
            GaugePoint gp;
            iss >> gp.row >> gp.col >> gp.name;
            cfg.gauges.push_back(gp);
        }
    }
    f.close();
    return cfg;
}

// ---------------------------------------------------------------
// Main driver
// ---------------------------------------------------------------
int main(int argc, char* argv[])
{
    std::string config_file = "data/sim.cfg";
    if (argc > 1) config_file = argv[1];

    SimConfig cfg = read_config(config_file);
    Grid grid = read_dem("data/valley.dem");

    int nc = grid.ncols, nr = grid.nrows;

    // Open gauge time-series file
    std::ofstream gauge_file(cfg.output_prefix + "_gauges.csv");
    gauge_file << "time";
    for (auto& gp : cfg.gauges) gauge_file << "," << gp.name;
    gauge_file << "\n";

    // Mass tracking
    double total_inflow  = 0.0;
    double total_outflow = 0.0;

    double t = 0.0;
    double next_output = 0.0;
    int step = 0;

    while (t < cfg.sim_time) {
        double dt = calc_adaptive_timestep(grid, cfg);
        if (t + dt > cfg.sim_time) dt = cfg.sim_time - t;
        if (dt <= 0.0) break;

        // Compute inter-cell fluxes
        compute_fluxes(grid, cfg, dt);

        // Track outflow at south boundary
        for (int i = 0; i < nc; i++) {
            double qout = grid.Qy[qy_idx(nr, i, nc)];
            if (qout > 0.0) total_outflow += qout * dt;
        }

        // Inject point-source inflow
        double Q_in = interpolate_inflow(cfg, t);
        total_inflow += Q_in * dt;
        apply_point_source(grid, cfg, t, dt);

        // Update water depths (continuity)
        update_water_depths(grid, cfg, dt);

        // Outflow boundary (south edge)
        enforce_outflow_boundary(grid);

        // Advance old fluxes
        copy_new_fluxes_to_old(grid);

        t += dt;
        step++;

        // Periodic output
        if (t >= next_output) {
            gauge_file << std::fixed << std::setprecision(6) << t;
            for (auto& gp : cfg.gauges) {
                int p = cell_idx(gp.row, gp.col, nc);
                gauge_file << "," << grid.h[p];
            }
            gauge_file << "\n";
            next_output += cfg.output_interval;
        }

        // Safety cap on iterations
        if (step > 5000000) {
            std::cerr << "WARNING: exceeded 5M steps, stopping early at t=" << t << std::endl;
            break;
        }
    }

    gauge_file.close();

    // Write final depth map
    write_depth_ascii(cfg.output_prefix + "_final.asc", grid);

    // Compute and write mass balance summary
    double final_volume = 0.0;
    for (int k = 0; k < nr * nc; k++) {
        final_volume += grid.h[k] * grid.dx * grid.dx;
    }
    double mass_err = total_inflow - total_outflow - final_volume;
    double mass_err_pct = (total_inflow > 0.0)
        ? fabs(mass_err) / total_inflow * 100.0
        : 0.0;

    std::ofstream mf(cfg.output_prefix + "_mass.txt");
    mf << std::fixed << std::setprecision(6);
    mf << "total_inflow_m3 "  << total_inflow  << "\n";
    mf << "total_outflow_m3 " << total_outflow << "\n";
    mf << "final_volume_m3 "  << final_volume  << "\n";
    mf << "mass_error_m3 "    << mass_err       << "\n";
    mf << "mass_error_pct "   << mass_err_pct   << "\n";
    mf << "steps "            << step            << "\n";
    mf.close();

    std::cout << "Simulation complete: " << step << " steps, t="
              << std::fixed << std::setprecision(2) << t << " s\n";
    std::cout << "Mass balance: inflow=" << total_inflow
              << " m3, outflow=" << total_outflow
              << " m3, stored=" << final_volume << " m3\n";
    std::cout << "Mass error: " << mass_err_pct << "%\n";

    // Optional diagnostic log
    if (cfg.log_file) {
        std::ofstream lf(*cfg.log_file);
        lf << "steps " << step << "\n";
        lf << "final_t " << std::fixed << std::setprecision(2) << t << "\n";
        lf.close();
    }

    return 0;
}
