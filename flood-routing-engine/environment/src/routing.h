#ifndef ROUTING_H
#define ROUTING_H


#include "geometry.h"
#include <vector>
#include <utility>

struct MuskingumCungeRouter {
    TrapezoidalChannel channel;
    double reach_length;

    void route(const std::vector<double>& inflow, double dt,
               std::vector<double>& outflow) const;
};

struct ModifiedPulsRouter {
    std::vector<std::pair<double, double>> storage_outflow;

    double interp_outflow(double S) const;
    double interp_storage(double O) const;
    void route(const std::vector<double>& inflow, double dt,
               std::vector<double>& outflow) const;
};

#endif
