
// Adaptive convection-diffusion solver.
// Detects physical regime via grid Peclet number, selects discretization
// and solver/preconditioner per regime, writes strategy.json.

#include <Eigen/Sparse>
#include <Eigen/IterativeLinearSolvers>
#include <iostream>
#include <fstream>
#include <cmath>
#include <string>
#include <vector>
#include <iomanip>
#include <sstream>

struct Config {
    int id;
    double epsilon;
    double bx, by;
    int n;
};

struct StrategyEntry {
    int config_id;
    double grid_peclet;
    std::string discretization;
    std::string solver;
    std::string preconditioner;
    std::string rationale;
};

void assemble_system(const Config& cfg, bool use_upwind,
                     Eigen::SparseMatrix<double>& A,
                     Eigen::VectorXd& rhs,
                     Eigen::VectorXd& u_exact) {
    int n = cfg.n;
    int N = n * n;
    double h = 1.0 / (n + 1);
    double h2 = h * h;

    std::vector<Eigen::Triplet<double>> triplets;
    rhs.resize(N);
    u_exact.resize(N);

    for (int j = 0; j < n; j++) {
        for (int i = 0; i < n; i++) {
            int idx = j * n + i;
            double x = (i + 1) * h;
            double y = (j + 1) * h;

            u_exact(idx) = sin(M_PI * x) * sin(M_PI * y);

            double f = cfg.epsilon * 2.0 * M_PI * M_PI * sin(M_PI * x) * sin(M_PI * y)
                     + cfg.bx * M_PI * cos(M_PI * x) * sin(M_PI * y)
                     + cfg.by * M_PI * sin(M_PI * x) * cos(M_PI * y);

            // Diffusion stencil: -eps * laplacian
            double diag = 4.0 * cfg.epsilon / h2;
            double left_c  = -cfg.epsilon / h2;
            double right_c = -cfg.epsilon / h2;
            double bot_c   = -cfg.epsilon / h2;
            double top_c   = -cfg.epsilon / h2;

            if (use_upwind) {
                // First-order upwind differencing for convection
                if (cfg.bx > 0) {
                    diag   += cfg.bx / h;
                    left_c -= cfg.bx / h;
                } else if (cfg.bx < 0) {
                    diag    -= cfg.bx / h;   // adds |bx|/h
                    right_c += cfg.bx / h;   // subtracts |bx|/h
                }
                if (cfg.by > 0) {
                    diag  += cfg.by / h;
                    bot_c -= cfg.by / h;
                } else if (cfg.by < 0) {
                    diag  -= cfg.by / h;
                    top_c += cfg.by / h;
                }
            } else {
                // Central differences for convection (second-order but unstable at high Pe)
                double cx = cfg.bx / (2.0 * h);
                double cy = cfg.by / (2.0 * h);
                right_c += cx;
                left_c  -= cx;
                top_c   += cy;
                bot_c   -= cy;
            }

            triplets.push_back({idx, idx, diag});
            if (i > 0)   triplets.push_back({idx, idx - 1, left_c});
            if (i < n-1) triplets.push_back({idx, idx + 1, right_c});
            if (j > 0)   triplets.push_back({idx, idx - n, bot_c});
            if (j < n-1) triplets.push_back({idx, idx + n, top_c});

            rhs(idx) = f;
        }
    }

    A.resize(N, N);
    A.setFromTriplets(triplets.begin(), triplets.end());
}

static std::string escape_json_str(const std::string& s) {
    std::string out;
    for (char c : s) {
        if (c == '"')       out += "\\\"";
        else if (c == '\\') out += "\\\\";
        else if (c == '\n') out += "\\n";
        else out += c;
    }
    return out;
}

int main() {
    std::vector<Config> configs = {
        {1, 1.0,    1.0, 0.0,   50},
        {2, 1e-4,   1.0, 0.0,   50},
        {3, 0.01,   0.707, 0.707, 50},
        {4, 1e-6,   0.0, 1.0,   50},
    };

    std::vector<StrategyEntry> strategies;
    bool all_pass = true;

    for (const auto& cfg : configs) {
        double h = 1.0 / (cfg.n + 1);
        double b_max = std::max(std::abs(cfg.bx), std::abs(cfg.by));
        double pe = b_max * h / (2.0 * cfg.epsilon);
        bool use_upwind = (pe > 1.0);

        Eigen::SparseMatrix<double> A;
        Eigen::VectorXd rhs, u_exact;
        assemble_system(cfg, use_upwind, A, rhs, u_exact);

        int iters;
        double residual, l2_error;
        bool converged;
        std::string solver_name, precond_name;

        if (pe > 1.0) {
            // Convection-dominated: robust preconditioner needed
            Eigen::BiCGSTAB<Eigen::SparseMatrix<double>,
                            Eigen::IncompleteLUT<double>> solver;
            solver.preconditioner().setDroptol(1e-4);
            solver.preconditioner().setFillfactor(30);
            solver.setMaxIterations(1000);
            solver.setTolerance(1e-10);
            solver.compute(A);
            Eigen::VectorXd x = solver.solve(rhs);
            iters = solver.iterations();
            residual = (A * x - rhs).norm();
            l2_error = (x - u_exact).norm() / u_exact.norm();
            converged = (solver.info() == Eigen::Success);
            solver_name = "BiCGSTAB";
            precond_name = "IncompleteLUT";
        } else {
            // Diffusion-dominated: lightweight preconditioner sufficient
            Eigen::BiCGSTAB<Eigen::SparseMatrix<double>,
                            Eigen::DiagonalPreconditioner<double>> solver;
            solver.setMaxIterations(1000);
            solver.setTolerance(1e-10);
            solver.compute(A);
            Eigen::VectorXd x = solver.solve(rhs);
            iters = solver.iterations();
            residual = (A * x - rhs).norm();
            l2_error = (x - u_exact).norm() / u_exact.norm();
            converged = (solver.info() == Eigen::Success);
            solver_name = "BiCGSTAB";
            precond_name = "DiagonalPreconditioner";
        }

        // Write per-config output
        std::string fname = "/app/output_" + std::to_string(cfg.id) + ".txt";
        std::ofstream out(fname);
        out << "config_id=" << cfg.id << "\n"
            << "epsilon=" << cfg.epsilon << "\n"
            << "bx=" << cfg.bx << "\n"
            << "by=" << cfg.by << "\n"
            << "n=" << cfg.n << "\n"
            << "iterations=" << iters << "\n"
            << "residual_norm=" << std::scientific << std::setprecision(10) << residual << "\n"
            << "l2_error=" << std::scientific << std::setprecision(10) << l2_error << "\n"
            << "converged=" << (converged ? "true" : "false") << "\n";
        out.close();

        std::cout << "Config " << cfg.id
                  << ": eps=" << cfg.epsilon
                  << " Pe=" << std::fixed << std::setprecision(2) << pe
                  << " disc=" << (use_upwind ? "upwind" : "central")
                  << " prec=" << precond_name
                  << " iters=" << iters
                  << " residual=" << std::scientific << residual
                  << " l2_err=" << l2_error
                  << " ok=" << converged << "\n";

        std::ostringstream rat;
        if (pe > 1.0) {
            rat << "Grid Peclet number Pe_h=" << std::fixed << std::setprecision(2) << pe
                << " >> 1 indicates convection-dominated flow. "
                << "Central differences lose the M-matrix property when Pe_h>1, "
                << "producing spurious oscillations that corrupt the solution. "
                << "First-order upwind differencing restores diagonal dominance "
                << "and eliminates oscillations at the cost of O(h) numerical diffusion. "
                << "IncompleteLUT preconditioner with controlled fill-in accelerates "
                << "convergence of BiCGSTAB for the resulting nonsymmetric system.";
        } else {
            rat << "Grid Peclet number Pe_h=" << std::fixed << std::setprecision(4) << pe
                << " < 1 indicates diffusion-dominated flow. "
                << "Central differences are stable (all off-diagonals negative, M-matrix preserved) "
                << "and provide second-order spatial accuracy. "
                << "The well-conditioned system converges rapidly with a simple diagonal preconditioner.";
        }

        strategies.push_back({cfg.id, pe, use_upwind ? "upwind" : "central",
                              solver_name, precond_name, rat.str()});

        if (!converged || residual > 1e-6 || l2_error > 0.15) {
            all_pass = false;
        }
    }

    // Write strategy.json documenting the per-regime analysis
    std::ofstream sj("/app/strategy.json");
    sj << "{\n  \"configurations\": [\n";
    for (size_t k = 0; k < strategies.size(); k++) {
        const auto& s = strategies[k];
        sj << "    {\n"
           << "      \"config_id\": " << s.config_id << ",\n"
           << "      \"grid_peclet_number\": " << std::fixed << std::setprecision(4) << s.grid_peclet << ",\n"
           << "      \"discretization\": \"" << s.discretization << "\",\n"
           << "      \"solver\": \"" << s.solver << "\",\n"
           << "      \"preconditioner\": \"" << s.preconditioner << "\",\n"
           << "      \"rationale\": \"" << escape_json_str(s.rationale) << "\"\n"
           << "    }";
        if (k < strategies.size() - 1) sj << ",";
        sj << "\n";
    }
    sj << "  ]\n}\n";
    sj.close();

    return all_pass ? 0 : 1;
}
