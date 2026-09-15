#include "geometry.h"
#include <cmath>
#include <algorithm>


double TrapezoidalChannel::area(double depth) const {
    return (bottom_width + side_slope * depth) * depth;
}

double TrapezoidalChannel::wetted_perimeter(double depth) const {
    // Correct: Pythagorean theorem for the sloped side length
    return bottom_width + 2.0 * depth * std::sqrt(1.0 + side_slope * side_slope);
}

double TrapezoidalChannel::top_width(double depth) const {
    return bottom_width + 2.0 * side_slope * depth;
}

double TrapezoidalChannel::hydraulic_radius(double depth) const {
    double A = area(depth);
    double P = wetted_perimeter(depth);
    if (P < 1e-12) return 0.0;
    return A / P;
}

double TrapezoidalChannel::discharge(double depth) const {
    if (depth <= 0.0) return 0.0;
    double A = area(depth);
    double R = hydraulic_radius(depth);
    return (1.0 / manning_n) * A * std::pow(R, 2.0 / 3.0) * std::sqrt(bed_slope);
}

double TrapezoidalChannel::normal_depth(double Q) const {
    if (Q <= 0.0) return 0.0;
    double lo = 0.0, hi = 50.0;
    for (int i = 0; i < 100; ++i) {
        double mid = 0.5 * (lo + hi);
        if (discharge(mid) < Q) lo = mid;
        else hi = mid;
    }
    return 0.5 * (lo + hi);
}

double TrapezoidalChannel::wave_celerity(double Q) const {
    // Kinematic wave celerity: dQ/dA via finite difference
    if (Q <= 0.0) return 0.01;
    double y = normal_depth(Q);
    if (y < 1e-8) return 0.01;
    double dy = std::max(y * 0.001, 1e-6);
    double Q1 = discharge(y);
    double Q2 = discharge(y + dy);
    double A1 = area(y);
    double A2 = area(y + dy);
    double dA = A2 - A1;
    if (std::abs(dA) < 1e-15) return 0.01;
    double c = (Q2 - Q1) / dA;
    return std::max(c, 0.01);
}
