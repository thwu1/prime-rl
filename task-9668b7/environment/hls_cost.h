/* HLS Cost Model - Shared Library Interface
 *
 * Analytical cost model for HLS design space exploration.
 * Maps configuration parameters to estimated PPA metrics
 * for a Xilinx Artix-7 FPGA target.
 *
 */

#ifndef HLS_COST_H
#define HLS_COST_H

/*
 * HLS configuration struct.
 *   Boolean fields: 0 = false, 1 = true.
 *   vivado_strategy: 0 = Default, 1 = Performance_Explore, 2 = Area_Explore.
 */
typedef struct {
    double clock_period_ns;
    int enable_pipeline;
    int pipeline_ii;
    int enable_dataflow;
    int unroll_factor;
    int array_partition_factor;
    int allocation_limit_add;
    int dsp_full_reg;
    int vivado_strategy;
} HLSConfig;

/* PPA (Power, Performance, Area) metrics returned by the evaluator. */
typedef struct {
    double area_luts;
    double latency_ns;
    double power_mw;
} HLSMetrics;

/* Evaluate a single HLS configuration. */
void hls_evaluate(const HLSConfig *config, HLSMetrics *metrics);

/* Batch-evaluate n configurations (configs and results are arrays of length n). */
void hls_evaluate_batch(const HLSConfig *configs, int n, HLSMetrics *results);

#endif /* HLS_COST_H */
