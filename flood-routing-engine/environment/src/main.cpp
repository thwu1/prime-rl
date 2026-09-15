#include "geometry.h"
#include "routing.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <cmath>
#include <cstdlib>


struct Scenario {
    double timestep = 0;
    double total_duration = 0;
    double baseflow = 0;
    double peak_flow = 0;
    double rise_time = 0;
    double fall_time = 0;

    struct ReachDef {
        std::string name;
        double length = 0, slope = 0, manning_n = 0;
        double bottom_width = 0, side_slope = 0;
    };
    std::vector<ReachDef> reaches;

    struct ReservoirDef {
        std::string name;
        std::vector<std::pair<double, double>> storage_outflow;
    };
    std::vector<ReservoirDef> reservoirs;

    std::vector<std::string> route_order;
};

Scenario parse_scenario(const std::string& filename) {
    Scenario sc;
    std::ifstream fin(filename);
    if (!fin.is_open()) {
        std::cerr << "Cannot open " << filename << std::endl;
        std::exit(1);
    }
    std::string line;
    while (std::getline(fin, line)) {
        if (line.empty() || line[0] == '#') continue;
        std::istringstream iss(line);
        std::string token;
        iss >> token;

        if (token == "TIMESTEP") {
            iss >> sc.timestep;
        } else if (token == "TOTAL_DURATION") {
            iss >> sc.total_duration;
        } else if (token == "HYDROGRAPH") {
            while (std::getline(fin, line)) {
                if (line.find("END") != std::string::npos) break;
                std::istringstream hss(line);
                std::string key;
                hss >> key;
                if (key == "BASEFLOW") hss >> sc.baseflow;
                else if (key == "PEAK_FLOW") hss >> sc.peak_flow;
                else if (key == "RISE_TIME") hss >> sc.rise_time;
                else if (key == "FALL_TIME") hss >> sc.fall_time;
            }
        } else if (token == "REACH") {
            Scenario::ReachDef rd;
            iss >> rd.name;
            while (std::getline(fin, line)) {
                if (line.find("END") != std::string::npos) break;
                std::istringstream rss(line);
                std::string key;
                rss >> key;
                if (key == "LENGTH") rss >> rd.length;
                else if (key == "SLOPE") rss >> rd.slope;
                else if (key == "MANNING_N") rss >> rd.manning_n;
                else if (key == "BOTTOM_WIDTH") rss >> rd.bottom_width;
                else if (key == "SIDE_SLOPE") rss >> rd.side_slope;
            }
            sc.reaches.push_back(rd);
        } else if (token == "RESERVOIR") {
            Scenario::ReservoirDef res;
            iss >> res.name;
            while (std::getline(fin, line)) {
                if (line.empty() || line[0] == '#') continue;
                if (line.find("END") != std::string::npos) break;
                std::istringstream rss(line);
                double s, o;
                if (rss >> s >> o) {
                    res.storage_outflow.push_back({s, o});
                }
                // Non-numeric lines (e.g. STORAGE_OUTFLOW keyword) are skipped
            }
            sc.reservoirs.push_back(res);
        } else if (token == "ROUTE") {
            std::string elem;
            while (iss >> elem) {
                sc.route_order.push_back(elem);
            }
        }
    }
    return sc;
}

std::vector<double> generate_hydrograph(const Scenario& sc) {
    int n = static_cast<int>(sc.total_duration / sc.timestep) + 1;
    std::vector<double> Q(n);
    for (int i = 0; i < n; ++i) {
        double t = i * sc.timestep;
        if (t <= sc.rise_time) {
            Q[i] = sc.baseflow + (sc.peak_flow - sc.baseflow) * t / sc.rise_time;
        } else if (t <= sc.rise_time + sc.fall_time) {
            Q[i] = sc.peak_flow - (sc.peak_flow - sc.baseflow) *
                   (t - sc.rise_time) / sc.fall_time;
        } else {
            Q[i] = sc.baseflow;
        }
    }
    return Q;
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        std::cerr << "Usage: " << argv[0] << " <scenario.txt> <output.csv>"
                  << std::endl;
        return 1;
    }

    Scenario sc = parse_scenario(argv[1]);
    std::vector<double> flow = generate_hydrograph(sc);
    double dt = sc.timestep;

    // Route through elements in specified order
    for (const auto& elem_name : sc.route_order) {
        bool found = false;
        for (const auto& rd : sc.reaches) {
            if (rd.name == elem_name) {
                TrapezoidalChannel ch;
                ch.bottom_width = rd.bottom_width;
                ch.side_slope = rd.side_slope;
                ch.manning_n = rd.manning_n;
                ch.bed_slope = rd.slope;

                MuskingumCungeRouter router;
                router.channel = ch;
                router.reach_length = rd.length;

                std::vector<double> outflow;
                router.route(flow, dt, outflow);
                flow = outflow;
                found = true;
                break;
            }
        }
        if (!found) {
            for (const auto& res : sc.reservoirs) {
                if (res.name == elem_name) {
                    ModifiedPulsRouter router;
                    router.storage_outflow = res.storage_outflow;

                    std::vector<double> outflow;
                    router.route(flow, dt, outflow);
                    flow = outflow;
                    found = true;
                    break;
                }
            }
        }
        if (!found) {
            std::cerr << "Unknown element: " << elem_name << std::endl;
            return 1;
        }
    }

    // Write output CSV
    std::ofstream fout(argv[2]);
    if (!fout.is_open()) {
        std::cerr << "Cannot open output file: " << argv[2] << std::endl;
        return 1;
    }
    fout << "time_s,flow_m3s" << std::endl;
    for (size_t i = 0; i < flow.size(); ++i) {
        fout << static_cast<int>(i * dt) << "," << flow[i] << std::endl;
    }

    return 0;
}
