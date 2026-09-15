# Matrix multiplication workloads and kernel tuning configurations

WORKLOADS = [
    (4096, 4096, 4096),
    (2048, 4096, 1024),
    (1024, 1024, 8192),
    (768, 2048, 4096),
    (512, 512, 512),
    (256, 8192, 256),
]

CONFIGS = [
    {'BLOCK_M': 128, 'BLOCK_N': 128, 'BLOCK_K': 64,  'GROUP_SIZE_M': 8, 'num_stages': 3, 'num_warps': 4},
    {'BLOCK_M': 128, 'BLOCK_N': 256, 'BLOCK_K': 64,  'GROUP_SIZE_M': 8, 'num_stages': 3, 'num_warps': 8},
    {'BLOCK_M': 128, 'BLOCK_N': 128, 'BLOCK_K': 128, 'GROUP_SIZE_M': 8, 'num_stages': 4, 'num_warps': 4},
    {'BLOCK_M': 128, 'BLOCK_N': 256, 'BLOCK_K': 128, 'GROUP_SIZE_M': 8, 'num_stages': 2, 'num_warps': 8},
    {'BLOCK_M': 128, 'BLOCK_N': 128, 'BLOCK_K': 64,  'GROUP_SIZE_M': 8, 'num_stages': 2, 'num_warps': 8},
    {'BLOCK_M': 64,  'BLOCK_N': 64,  'BLOCK_K': 64,  'GROUP_SIZE_M': 8, 'num_stages': 4, 'num_warps': 4},
]
