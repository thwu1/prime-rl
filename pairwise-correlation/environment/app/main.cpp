// Weighted pairwise-complete Pearson correlation.
// See spec.md for full specification.
//

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <vector>
#include <algorithm>

int main(int argc, char* argv[]) {
    if (argc != 5) {
        fprintf(stderr, "Usage: %s <input.bin> <K> <min_samples> <output.bin>\n", argv[0]);
        return 1;
    }

    const char* input_path = argv[1];
    int K = atoi(argv[2]);
    int min_samples = atoi(argv[3]);
    const char* output_path = argv[4];

    // Implement according to spec.md

    return 0;
}
