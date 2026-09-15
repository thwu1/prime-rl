# GPU Hardware Configuration (NVIDIA A100-80GB SXM)
GPU_CONFIG = {
    'name': 'A100-80GB',
    'num_sms': 108,
    'shared_mem_per_sm': 167936,            # 164 KB total per SM
    'max_shared_mem_per_block': 167936,      # 164 KB (with opt-in)
    'max_warps_per_sm': 64,
    'max_blocks_per_sm': 32,
    'fp16_peak_tflops': 312.0,              # FP16 Tensor Core peak
    'memory_bw_gbps': 2039.0,              # HBM2e bandwidth
}
