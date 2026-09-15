#include "solver.hpp"
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>


static Problem read_problem(const char* path)
{
    Problem p = {298.15, 0.0, 0.0, 0.0, 0.0, 0.0};
    std::ifstream f(path);
    if (!f) { std::fprintf(stderr, "Cannot open %s\n", path); std::exit(2); }
    std::string key; double val;
    while (f >> key >> val) {
        if      (key == "temperature") p.T        = val;
        else if (key == "total_Na")    p.total_Na = val;
        else if (key == "total_Cl")    p.total_Cl = val;
        else if (key == "total_Ca")    p.total_Ca = val;
        else if (key == "total_C")     p.total_C  = val;
        else if (key == "total_S")     p.total_S  = val;
    }
    return p;
}

static void write_result(const char* path, const Result& r)
{
    FILE* f = std::fopen(path, "w");
    if (!f) { std::fprintf(stderr, "Cannot write %s\n", path); std::exit(2); }
    std::fprintf(f, "pH %.15e\n",              r.pH);
    std::fprintf(f, "ionic_strength %.15e\n",  r.ionic_strength);
    std::fprintf(f, "m_H %.15e\n",             r.m[SP_H]);
    std::fprintf(f, "m_OH %.15e\n",            r.m[SP_OH]);
    std::fprintf(f, "m_Na %.15e\n",            r.m[SP_NA]);
    std::fprintf(f, "m_Cl %.15e\n",            r.m[SP_CL]);
    std::fprintf(f, "m_Ca %.15e\n",            r.m[SP_CA]);
    std::fprintf(f, "m_SO4 %.15e\n",           r.m[SP_SO4]);
    std::fprintf(f, "m_CO2 %.15e\n",           r.m[SP_CO2]);
    std::fprintf(f, "m_HCO3 %.15e\n",          r.m[SP_HCO3]);
    std::fprintf(f, "m_CO3 %.15e\n",           r.m[SP_CO3]);
    std::fprintf(f, "m_CaCO3aq %.15e\n",       r.m[SP_CACO3AQ]);
    std::fprintf(f, "m_NaClaq %.15e\n",        r.m[SP_NACLAQ]);
    std::fprintf(f, "m_CaSO4aq %.15e\n",       r.m[SP_CASO4AQ]);
    std::fprintf(f, "charge_balance %.15e\n",  r.charge_balance);
    std::fprintf(f, "calcite_SI %.15e\n",      r.calcite_SI);
    std::fprintf(f, "gypsum_SI %.15e\n",       r.gypsum_SI);
    std::fprintf(f, "n_calcite %.15e\n",       r.n_calcite);
    std::fprintf(f, "n_gypsum %.15e\n",        r.n_gypsum);
    std::fprintf(f, "converged %d\n",          r.converged ? 1 : 0);
    std::fprintf(f, "iterations %d\n",         r.iterations);
    std::fclose(f);
}

int main(int argc, char* argv[])
{
    const char* inp = "/app/problem_1.txt";
    const char* out = "/app/results_1.txt";
    if (argc > 1) inp = argv[1];
    if (argc > 2) out = argv[2];

    Problem p = read_problem(inp);
    Result  r = solve(p);
    write_result(out, r);

    std::printf("pH=%.4f I=%.6f conv=%s iter=%d n_cal=%.4e n_gyp=%.4e\n",
                r.pH, r.ionic_strength,
                r.converged ? "yes" : "no", r.iterations,
                r.n_calcite, r.n_gypsum);
    return r.converged ? 0 : 1;
}
