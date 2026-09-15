"""Machine configuration parameters for roofline analysis.

Reference machine parameters for a generic modern HPC server node.
These values are used as inputs to the roofline model and scaling analysis.
"""


MACHINE = {
    "name": "GenericHPC",
    "peak_flops": 1000e9,       # 1 TFLOP/s double-precision peak
    "dram_bandwidth": 200e9,    # 200 GB/s DRAM bandwidth
    "l3_bandwidth": 500e9,      # 500 GB/s aggregate L3 bandwidth
    "l2_bandwidth": 1000e9,     # 1 TB/s aggregate L2 bandwidth
    "l3_size": 30 * 1024**2,    # 30 MB shared L3 cache
    "l2_size": 1 * 1024**2,     # 1 MB L2 cache per core
    "elem_size": 8,             # 8 bytes per double-precision float
}
