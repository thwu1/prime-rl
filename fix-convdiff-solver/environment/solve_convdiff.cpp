
// Solves the 2D steady-state convection-diffusion equation
//   -eps * laplacian(u) + b . grad(u) = f
// on [0,1]^2 with homogeneous Dirichlet boundary conditions.
// Manufactured exact solution: u(x,y) = sin(pi*x)*sin(pi*y)
//
// Four parameter configurations test different physical regimes.
// Current implementation uses the SAME discretization and solver
// for all configurations.

#include <Eigen/Sparse>
#include <Eigen/IterativeLinearSolvers>
#include <iostream>
#include <fstream>
#include <cmath>
#include <string>
#include <vector>

struct Config {
    int id;
    double epsilon;
    double bx, by;
    int n;  // interior grid points per direction
};

void assemble_system(const Config& cfg,
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

            // Manufactured RHS: f = eps*2*pi^2*sin(pi*x)*sin(pi*y)
            //                     + bx*pi*cos(pi*x)*sin(pi*y)
            //                     + by*pi*sin(pi*x)*cos(pi*y)
            double f = cfg.epsilon * 2.0 * M_PI * M_PI * sin(M_PI * x) * sin(M_PI * y)
                     + cfg.bx * M_PI * cos(M_PI * x) * sin(M_PI * y)
                     + cfg.by * M_PI * sin(M_PI * x) * cos(M_PI * y);

            // Diffusion: 5-point stencil for -eps*laplacian
            double diag = 4.0 * cfg.epsilon / h2;
            double off = -cfg.epsilon / h2;

            // Convection: central differences for b . grad(u)
            double cx = cfg.bx / (2.0 * h);
            double cy = cfg.by / (2.0 * h);

            triplets.push_back({idx, idx, diag});
            if (i > 0)   triplets.push_back({idx, idx - 1, off - cx});  // left
            if (i < n-1) triplets.push_back({idx, idx + 1, off + cx});  // right
            if (j > 0)   triplets.push_back({idx, idx - n, off - cy});  // bottom
            if (j < n-1) triplets.push_back({idx, idx + n, off + cy});  // top

            rhs(idx) = f;
        }
    }

    A.resize(N, N);
    A.setFromTriplets(triplets.begin(), triplets.end());
}

int main() {
    // Four configurations spanning diffusion-dominated to convection-dominated
    std::vector<Config> configs = {
        {1, 1.0,    1.0, 0.0,   50},   // regime A
        {2, 1e-4,   1.0, 0.0,   50},   // regime B
        {3, 0.01,   0.707, 0.707, 50},  // regime C
        {4, 1e-6,   0.0, 1.0,   50},   // regime D
    };

    bool all_pass = true;

    for (const auto& cfg : configs) {
        Eigen::SparseMatrix<double> A;
        Eigen::VectorXd rhs, u_exact;
        assemble_system(cfg, A, rhs, u_exact);

        // Single solver strategy for all configurations:
        // BiCGSTAB with diagonal (Jacobi) preconditioner
        Eigen::BiCGSTAB<Eigen::SparseMatrix<double>,
                        Eigen::DiagonalPreconditioner<double>> solver;
        solver.setMaxIterations(1000);
        solver.setTolerance(1e-10);
        solver.compute(A);
        Eigen::VectorXd x = solver.solve(rhs);

        double residual = (A * x - rhs).norm();
        double l2_error = (x - u_exact).norm() / u_exact.norm();
        int iterations = solver.iterations();
        bool converged = (solver.info() == Eigen::Success);

        std::string filename = "/app/output_" + std::to_string(cfg.id) + ".txt";
        std::ofstream out(filename);
        out << "config_id=" << cfg.id << "\n"
            << "epsilon=" << cfg.epsilon << "\n"
            << "bx=" << cfg.bx << "\n"
            << "by=" << cfg.by << "\n"
            << "n=" << cfg.n << "\n"
            << "iterations=" << iterations << "\n"
            << "residual_norm=" << residual << "\n"
            << "l2_error=" << l2_error << "\n"
            << "converged=" << (converged ? "true" : "false") << "\n";
        out.close();

        std::cout << "Config " << cfg.id
                  << ": eps=" << cfg.epsilon
                  << " iters=" << iterations
                  << " residual=" << residual
                  << " l2_error=" << l2_error
                  << " converged=" << converged << "\n";

        if (!converged || residual > 1e-6 || l2_error > 0.15) {
            all_pass = false;
        }
    }

    return all_pass ? 0 : 1;
}
