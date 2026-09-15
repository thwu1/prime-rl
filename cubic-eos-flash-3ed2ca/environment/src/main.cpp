#include "flash_engine.h"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <vector>


struct Problem {
    std::string name;
    double T;   // K
    double P;   // Pa
    std::vector<int> comp;
    std::vector<double> z;
};

int main() {
    std::vector<Problem> problems = {
        {"michelsen_7comp",
         200.0, 4.0e6,
         {0, 1, 2, 3, 4, 5, 7},
         {0.9430, 0.0270, 0.0074, 0.0049, 0.0027, 0.0010, 0.0140}},

        {"ch4_co2_binary",
         220.0, 3.0e6,
         {0, 8},
         {0.5, 0.5}},

        {"ch4_c10_asymmetric",
         310.0, 2.0e6,
         {0, 6},
         {0.7, 0.3}},

        {"nitrogen_supercrit",
         200.0, 1.0e6,
         {7},
         {1.0}},

        {"co2_supercrit",
         350.0, 1.0e7,
         {8},
         {1.0}},

        {"ternary_flash",
         190.0, 2.5e6,
         {0, 1, 2},
         {0.70, 0.20, 0.10}},
    };

    std::ofstream out("/app/results.txt");
    if (!out.is_open()) {
        std::cerr << "Error: cannot open /app/results.txt for writing" << std::endl;
        return 1;
    }
    out << std::setprecision(15);

    for (auto& prob : problems) {
        auto res = run_flash(prob.name, prob.comp, prob.z, prob.T, prob.P);

        out << "PROBLEM: " << res.problem_name << "\n";
        out << "STATUS: " << (res.converged ? "converged" : "failed") << "\n";
        out << "PHASE: " << (res.two_phase ? "two_phase" : "single_phase") << "\n";
        out << "NC: " << prob.comp.size() << "\n";
        out << "COMP:";
        for (int c : prob.comp) out << " " << c;
        out << "\n";
        out << "FEED:";
        for (double zi : prob.z) out << " " << zi;
        out << "\n";

        if (res.two_phase) {
            out << "V: " << res.V << "\n";
            out << "LIQUID:";
            for (double xi : res.x) out << " " << xi;
            out << "\n";
            out << "VAPOR:";
            for (double yi : res.y) out << " " << yi;
            out << "\n";
            out << "LN_PHI_L:";
            for (double p : res.ln_phi_L) out << " " << p;
            out << "\n";
            out << "LN_PHI_V:";
            for (double p : res.ln_phi_V) out << " " << p;
            out << "\n";
            out << "Z_L: " << res.Z_L << "\n";
            out << "Z_V: " << res.Z_V << "\n";
        } else {
            out << "LN_PHI:";
            for (double p : res.ln_phi_L) out << " " << p;
            out << "\n";
            out << "Z_FACTOR: " << res.Z_L << "\n";
        }

        out << "END\n\n";
    }

    out.close();
    std::cout << "Results written to /app/results.txt" << std::endl;
    return 0;
}
