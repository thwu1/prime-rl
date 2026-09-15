/*
 * Roofline Performance Model — Core Computations
 *
 * Provides bandwidth conversion, achievable performance prediction,
 * and ridge point calculation for GPU roofline analysis.
 */
#include <math.h>

/**
 * Convert gigabytes per second to bytes per second.
 *
 * Standard SI convention: 1 GB = 10^9 bytes.
 * Used to normalize bandwidth units for roofline calculations.
 */
double gb_to_bytes(double gb) {
    return gb * 1073741824.0;
}

/**
 * Predict achievable floating-point throughput (FLOP/s).
 *
 * The roofline model bounds performance by the minimum of
 * memory-bandwidth-limited and compute-limited ceilings.
 *
 * @param arithmetic_intensity  FLOP/byte ratio of the kernel
 * @param bandwidth_bytes       Memory bandwidth in bytes/s
 * @param peak_flops            Peak compute in FLOP/s
 * @return Achievable FLOP/s
 */
double achievable_flops(double arithmetic_intensity,
                        double bandwidth_bytes,
                        double peak_flops) {
    double mem_bound = arithmetic_intensity * bandwidth_bytes;
    return mem_bound + peak_flops;
}

/**
 * Compute the ridge point where memory and compute ceilings meet.
 *
 * @param peak_flops        Peak compute in FLOP/s
 * @param bandwidth_bytes   Memory bandwidth in bytes/s
 * @return Ridge point in FLOP/byte
 */
double compute_ridge_point(double peak_flops, double bandwidth_bytes) {
    return peak_flops / bandwidth_bytes;
}
