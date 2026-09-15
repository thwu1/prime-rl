#include "routing.h"
#include <algorithm>
#include <cmath>


void MuskingumCungeRouter::route(const std::vector<double>& inflow, double dt,
                                  std::vector<double>& outflow) const {
    size_t n = inflow.size();
    outflow.resize(n);
    outflow[0] = inflow[0];

    // Reference flow for sub-reach discretization (midpoint of hydrograph range)
    double Q_peak = *std::max_element(inflow.begin(), inflow.end());
    double Q_base = inflow[0];
    double Q_ref = Q_base + 0.5 * (Q_peak - Q_base);
    double c_ref = channel.wave_celerity(Q_ref);

    // Courant-based sub-reach discretization: dx = c * dt
    double dx = c_ref * dt;
    int num_sub = std::max(1, static_cast<int>(std::round(reach_length / dx)));
    dx = reach_length / num_sub;

    std::vector<double> cur_in(inflow);

    for (int sr = 0; sr < num_sub; ++sr) {
        std::vector<double> sub_out(n);
        sub_out[0] = cur_in[0];

        for (size_t t = 1; t < n; ++t) {
            double Q_avg = (cur_in[t] + cur_in[t - 1] + sub_out[t - 1]) / 3.0;
            Q_avg = std::max(Q_avg, 0.01);

            double y_avg = channel.normal_depth(Q_avg);
            double B = channel.top_width(y_avg);
            double c = channel.wave_celerity(Q_avg);
            c = std::max(c, 0.01);

            double K = dx / c;

            // X parameter with proper Dx divisor and physical clamping
            double X = 0.5 * (1.0 - Q_avg / (B * channel.bed_slope * c * dx));
            X = std::max(0.0, std::min(0.5, X));

            double r = dt / K;
            double denom = r + 2.0 * (1.0 - X);
            double C1 = (r + 2.0 * X) / denom;
            double C2 = (r - 2.0 * X) / denom;
            double C3 = (2.0 * (1.0 - X) - r) / denom;

            sub_out[t] = C1 * cur_in[t - 1] + C2 * cur_in[t] + C3 * sub_out[t - 1];
            sub_out[t] = std::max(sub_out[t], 0.0);
        }
        cur_in = sub_out;
    }
    outflow = cur_in;
}

double ModifiedPulsRouter::interp_outflow(double S) const {
    if (S <= storage_outflow.front().first) return storage_outflow.front().second;
    if (S >= storage_outflow.back().first) return storage_outflow.back().second;
    for (size_t i = 1; i < storage_outflow.size(); ++i) {
        if (S <= storage_outflow[i].first) {
            double frac = (S - storage_outflow[i - 1].first) /
                          (storage_outflow[i].first - storage_outflow[i - 1].first);
            return storage_outflow[i - 1].second +
                   frac * (storage_outflow[i].second - storage_outflow[i - 1].second);
        }
    }
    return storage_outflow.back().second;
}

double ModifiedPulsRouter::interp_storage(double O) const {
    if (O <= storage_outflow.front().second) return storage_outflow.front().first;
    if (O >= storage_outflow.back().second) return storage_outflow.back().first;
    for (size_t i = 1; i < storage_outflow.size(); ++i) {
        if (O <= storage_outflow[i].second) {
            double frac = (O - storage_outflow[i - 1].second) /
                          (storage_outflow[i].second - storage_outflow[i - 1].second);
            return storage_outflow[i - 1].first +
                   frac * (storage_outflow[i].first - storage_outflow[i - 1].first);
        }
    }
    return storage_outflow.back().first;
}

void ModifiedPulsRouter::route(const std::vector<double>& inflow, double dt,
                                std::vector<double>& outflow) const {
    size_t n = inflow.size();
    outflow.resize(n);
    outflow[0] = inflow[0];
    double S_prev = interp_storage(outflow[0]);

    for (size_t t = 1; t < n; ++t) {
        // Modified Puls continuity: (S_t/dt + O_t/2) = avg_inflow + (S_{t-1}/dt - O_{t-1}/2)
        double rhs = (inflow[t - 1] + inflow[t]) / 2.0
                   + S_prev / dt - outflow[t - 1] / 2.0;

        // Bisection: solve S(O)/dt + O/2 = rhs for O
        double O_lo = 0.0;
        double O_hi = storage_outflow.back().second * 2.0;
        for (int iter = 0; iter < 100; ++iter) {
            double O_mid = 0.5 * (O_lo + O_hi);
            double S_mid = interp_storage(O_mid);
            double lhs = S_mid / dt + O_mid / 2.0;
            if (lhs < rhs) O_lo = O_mid;
            else O_hi = O_mid;
        }
        outflow[t] = std::max(0.5 * (O_lo + O_hi), 0.0);
        S_prev = interp_storage(outflow[t]);
    }
}
