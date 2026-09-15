// lattice_proc.cpp — Binary lattice arc processor (reference implementation)
//

#include "lattice_weight.h"
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <set>
#include <sstream>
#include <string>
#include <vector>

struct LatticeArc {
    uint32_t src;
    uint32_t dst;
    CompactLatticeWeight weight;
};

static std::vector<LatticeArc> read_binary(const std::string& filename) {
    std::ifstream in(filename, std::ios::binary);
    if (!in) {
        std::cerr << "Cannot open " << filename << std::endl;
        exit(1);
    }

    uint32_t num_arcs;
    in.read(reinterpret_cast<char*>(&num_arcs), sizeof(uint32_t));

    std::vector<LatticeArc> arcs(num_arcs);
    for (uint32_t i = 0; i < num_arcs; i++) {
        in.read(reinterpret_cast<char*>(&arcs[i].src), sizeof(uint32_t));
        in.read(reinterpret_cast<char*>(&arcs[i].dst), sizeof(uint32_t));

        float v1, v2;
        in.read(reinterpret_cast<char*>(&v1), sizeof(float));
        in.read(reinterpret_cast<char*>(&v2), sizeof(float));

        uint32_t str_len;
        in.read(reinterpret_cast<char*>(&str_len), sizeof(uint32_t));

        std::vector<int32_t> str(str_len);
        if (str_len > 0) {
            in.read(reinterpret_cast<char*>(str.data()),
                    str_len * sizeof(int32_t));
        }

        arcs[i].weight = CompactLatticeWeight(LatticeWeight(v1, v2), str);
    }
    return arcs;
}

static void write_binary(const std::string& filename,
                         const std::vector<LatticeArc>& arcs) {
    std::ofstream out(filename, std::ios::binary);
    if (!out) {
        std::cerr << "Cannot open " << filename << " for writing" << std::endl;
        exit(1);
    }

    uint32_t num_arcs = static_cast<uint32_t>(arcs.size());
    out.write(reinterpret_cast<const char*>(&num_arcs), sizeof(uint32_t));

    for (const auto& arc : arcs) {
        out.write(reinterpret_cast<const char*>(&arc.src), sizeof(uint32_t));
        out.write(reinterpret_cast<const char*>(&arc.dst), sizeof(uint32_t));

        float v1 = arc.weight.Weight().Value1();
        float v2 = arc.weight.Weight().Value2();
        out.write(reinterpret_cast<const char*>(&v1), sizeof(float));
        out.write(reinterpret_cast<const char*>(&v2), sizeof(float));

        uint32_t str_len = static_cast<uint32_t>(arc.weight.String().size());
        out.write(reinterpret_cast<const char*>(&str_len), sizeof(uint32_t));

        if (str_len > 0) {
            out.write(
                reinterpret_cast<const char*>(arc.weight.String().data()),
                str_len * sizeof(int32_t));
        }
    }
}

static void cmd_stats(const std::string& filename) {
    auto arcs = read_binary(filename);

    CompactLatticeWeight times_result = CompactLatticeWeight::One();
    CompactLatticeWeight plus_result = CompactLatticeWeight::Zero();

    std::set<std::string> quantized_set;

    for (const auto& arc : arcs) {
        times_result = Times(times_result, arc.weight);
        plus_result = Plus(plus_result, arc.weight);

        std::ostringstream oss;
        oss << arc.weight.Quantize();
        quantized_set.insert(oss.str());
    }

    std::cout << "arcs: " << arcs.size() << std::endl;
    std::cout << "times_fold: " << times_result << std::endl;
    std::cout << "plus_fold: " << plus_result << std::endl;
    std::cout << "distinct_quantized: " << quantized_set.size() << std::endl;
}

static void cmd_text(const std::string& filename) {
    auto arcs = read_binary(filename);
    for (const auto& arc : arcs) {
        std::cout << arc.src << " " << arc.dst << " " << arc.weight
                  << std::endl;
    }
}

static void cmd_binary(const std::string& filename) {
    std::vector<LatticeArc> arcs;
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) break;
        std::istringstream iss(line);
        LatticeArc arc;
        iss >> arc.src >> arc.dst >> arc.weight;
        if (!iss.fail()) {
            arcs.push_back(arc);
        }
    }
    write_binary(filename, arcs);
}

static void cmd_normalize(const std::string& filename) {
    auto arcs = read_binary(filename);
    if (arcs.empty()) return;

    CompactLatticeWeightCommonDivisor cd_op;
    CompactLatticeWeight cd = arcs[0].weight;
    for (size_t i = 1; i < arcs.size(); i++) {
        cd = cd_op(cd, arcs[i].weight);
    }

    for (const auto& arc : arcs) {
        CompactLatticeWeight norm = Divide(arc.weight, cd, DIVIDE_LEFT);
        std::cout << arc.src << " " << arc.dst << " " << norm << std::endl;
    }
}

int main(int argc, char* argv[]) {
    if (argc < 3) {
        std::cerr << "Usage: " << argv[0] << " <command> <file>" << std::endl;
        std::cerr << "Commands: stats, text, binary, normalize" << std::endl;
        return 1;
    }

    std::string command = argv[1];
    std::string filename = argv[2];

    if (command == "stats") {
        cmd_stats(filename);
    } else if (command == "text") {
        cmd_text(filename);
    } else if (command == "binary") {
        cmd_binary(filename);
    } else if (command == "normalize") {
        cmd_normalize(filename);
    } else {
        std::cerr << "Unknown command: " << command << std::endl;
        return 1;
    }

    return 0;
}
