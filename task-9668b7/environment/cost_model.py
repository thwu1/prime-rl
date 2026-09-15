"""
Analytical cost model for HLS Design Space Exploration.
Maps HLS configuration parameters to estimated PPA (Power, Performance, Area) metrics.

This model approximates the behavior of Vitis HLS synthesis for a representative
compute kernel on a Xilinx Artix-7 xc7a200tffv1156-1 FPGA.

DO NOT MODIFY THIS FILE.
"""



def evaluate(config):
    """
    Evaluate a single HLS configuration and return estimated PPA metrics.

    Args:
        config: dict with keys:
            - clock_period_ns (float): Target clock period in nanoseconds
            - enable_pipeline (bool): Whether to enable loop/function pipelining
            - pipeline_ii (int): Pipeline initiation interval (only used if enable_pipeline is True)
            - enable_dataflow (bool): Whether to enable task-level dataflow parallelism
            - unroll_factor (int): Loop unroll factor
            - array_partition_factor (int): Memory array partition factor
            - allocation_limit_add (int): Operator allocation limit (0 = disabled)
            - dsp_full_reg (bool): Whether to enable full DSP register pipelining
            - vivado_strategy (str): Vivado implementation strategy

    Returns:
        dict with keys:
            - area_luts (float): Estimated LUT utilization
            - latency_ns (float): Estimated total latency in nanoseconds
            - power_mw (float): Estimated dynamic power in milliwatts
    """
    BASE_LUTS = 500.0
    BASE_CYCLES = 1000.0
    BASE_POWER_MW = 50.0

    clock_ns = config['clock_period_ns']
    freq_ghz = 1.0 / clock_ns

    luts = BASE_LUTS
    cycles = BASE_CYCLES

    # Unrolling: area scales linearly with unroll factor, cycles scale inversely
    uf = config['unroll_factor']
    luts *= uf
    cycles /= uf

    # Array partitioning: additional mux LUTs, reduced memory access latency
    pf = config['array_partition_factor']
    luts += 80.0 * (pf - 1)
    if pf > 1:
        cycles *= (1.0 - 0.08 * (pf - 1))

    # Pipelining: register overhead increases area, reduces effective cycle count
    if config['enable_pipeline']:
        ii = config.get('pipeline_ii', 1)
        luts *= 1.3
        cycles = cycles * 0.7 * ii

    # Dataflow: task-level parallelism increases area significantly, reduces cycles
    if config['enable_dataflow']:
        luts *= 1.5
        cycles *= 0.55

    # Allocation limiting: constrains operator instances, trades area for latency
    alloc = config['allocation_limit_add']
    if alloc > 0:
        luts *= (1.0 - 0.05 * alloc)
        cycles *= (1.0 + 0.1 * alloc)

    # DSP full register: slight latency improvement from pipelining DSP ops
    if config['dsp_full_reg']:
        cycles *= 0.95

    # Vivado implementation strategy affects both area and timing
    strategy = config['vivado_strategy']
    if strategy == 'Performance_Explore':
        cycles *= 0.9
        luts *= 1.1
    elif strategy == 'Area_Explore':
        luts *= 0.85
        cycles *= 1.05

    # Derived metrics
    latency_ns = cycles * clock_ns
    power_mw = BASE_POWER_MW * (luts / BASE_LUTS) * freq_ghz

    if config['dsp_full_reg']:
        power_mw *= 1.08

    return {
        'area_luts': round(luts, 4),
        'latency_ns': round(latency_ns, 4),
        'power_mw': round(power_mw, 4)
    }
