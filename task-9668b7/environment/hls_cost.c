/*
 * HLS Cost Model Implementation.
 *
 * Approximates Vitis HLS synthesis for a representative compute kernel
 * on a Xilinx Artix-7 xc7a200tffv1156-1 FPGA.
 *
 */

#include "hls_cost.h"

void hls_evaluate(const HLSConfig *config, HLSMetrics *metrics) {
    double luts = 500.0;
    double cycles = 1000.0;
    double clock_ns = config->clock_period_ns;
    double freq_ghz = 1.0 / clock_ns;

    /* Unrolling: area scales linearly, cycles scale inversely */
    int uf = config->unroll_factor;
    luts *= uf;
    cycles /= uf;

    /* Array partitioning: mux LUT overhead, reduced memory latency */
    int pf = config->array_partition_factor;
    luts += 80.0 * (pf - 1);
    if (pf > 1)
        cycles *= (1.0 - 0.08 * (pf - 1));

    /* Pipelining: register overhead, reduced effective cycles */
    if (config->enable_pipeline) {
        int ii = config->pipeline_ii;
        luts *= 1.3;
        cycles = cycles * 0.7 * ii;
    }

    /* Dataflow: task-level parallelism */
    if (config->enable_dataflow) {
        luts *= 1.5;
        cycles *= 0.55;
    }

    /* Allocation limiting: trade area for latency */
    int alloc = config->allocation_limit_add;
    if (alloc > 0) {
        luts *= (1.0 - 0.05 * alloc);
        cycles *= (1.0 + 0.1 * alloc);
    }

    /* DSP full register pipelining */
    if (config->dsp_full_reg)
        cycles *= 0.95;

    /* Vivado implementation strategy */
    int strat = config->vivado_strategy;
    if (strat == 1) {          /* Performance_Explore */
        cycles *= 0.9;
        luts *= 1.1;
    } else if (strat == 2) {   /* Area_Explore */
        luts *= 0.85;
        cycles *= 1.05;
    }

    /* Derived metrics */
    metrics->area_luts = luts;
    metrics->latency_ns = cycles * clock_ns;
    metrics->power_mw = 50.0 * (luts / 500.0) * freq_ghz;
    if (config->dsp_full_reg)
        metrics->power_mw *= 1.08;
}

void hls_evaluate_batch(const HLSConfig *configs, int n, HLSMetrics *results) {
    for (int i = 0; i < n; i++)
        hls_evaluate(&configs[i], &results[i]);
}
