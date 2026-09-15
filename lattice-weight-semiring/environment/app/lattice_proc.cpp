// lattice_proc.cpp — Binary lattice arc processor
// Implement the stats, text, binary, and normalize commands to process lattice arc files.
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

// Binary lattice arc format (all little-endian / native on x86):
// Header: uint32_t num_arcs
// Per arc:
//   uint32_t src_state
//   uint32_t dst_state
//   float weight_v1
//   float weight_v2
//   uint32_t string_length
//   string_length x int32_t string_elements

struct LatticeArc {
    uint32_t src;
    uint32_t dst;
    CompactLatticeWeight weight;
};

// TODO: Implement binary file reading
// TODO: Implement binary file writing
// TODO: Implement stats command
// TODO: Implement text command
// TODO: Implement binary command (read text from stdin, write binary to file)
// TODO: Implement normalize command (fold common divisor across all arcs,
//       then left-divide each arc weight by the result)

int main(int argc, char* argv[]) {
    if (argc < 3) {
        std::cerr << "Usage: " << argv[0] << " <command> <file>" << std::endl;
        std::cerr << "Commands: stats, text, binary, normalize" << std::endl;
        return 1;
    }

    std::string command = argv[1];
    std::string filename = argv[2];

    // TODO: dispatch to command implementations

    std::cerr << "Not implemented" << std::endl;
    return 1;
}
