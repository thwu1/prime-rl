#include "correlate.h"
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <random>
#include <vector>

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "Usage: %s <n> <d> [output_file]\n", argv[0]);
        return 1;
    }

    int n = std::atoi(argv[1]);
    int d = std::atoi(argv[2]);
    const char* outfile = (argc > 3) ? argv[3] : nullptr;

    // Generate reproducible random input
    std::mt19937 gen(42);
    std::normal_distribution<float> dist(0.0f, 1.0f);

    std::vector<float> input(static_cast<size_t>(n) * d);
    for (auto& x : input) x = dist(gen);

    std::vector<float> output(static_cast<size_t>(n) * n, 0.0f);

    // Time the computation
    auto start = std::chrono::high_resolution_clock::now();
    correlate(n, d, input.data(), output.data());
    auto end = std::chrono::high_resolution_clock::now();

    double elapsed = std::chrono::duration<double>(end - start).count();
    std::printf("TIME:%.6f\n", elapsed);

    // Optionally save output as raw float32 binary
    if (outfile) {
        std::ofstream ofs(outfile, std::ios::binary);
        ofs.write(reinterpret_cast<const char*>(output.data()),
                  static_cast<std::streamsize>(static_cast<size_t>(n) * n * sizeof(float)));
    }

    return 0;
}
