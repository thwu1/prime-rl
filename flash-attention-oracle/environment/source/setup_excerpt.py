# Excerpted from flash-attention setup.py (Tri Dao, 2024)
# Build configuration logic for CUDA gencode flags and compilation parallelism.

import os
import functools

# Environment variable for NVCC parallel threads
NVCC_THREADS = os.getenv("NVCC_THREADS") or "4"

@functools.lru_cache(maxsize=None)
def cuda_archs():
    return os.getenv("FLASH_ATTN_CUDA_ARCHS", "80;90;100;110;120").split(";")


def add_cuda_gencodes(cc_flag, archs, bare_metal_version):
    """
    Adds -gencode flags based on nvcc capabilities:
      - sm_80/90 (regular)
      - sm_100/120 on CUDA >= 12.8
      - Use 100f on CUDA >= 12.9 (Blackwell family-specific)
      - Map requested 110 -> 101 if CUDA < 13.0 (Thor rename)
      - Embed PTX for newest arch for forward compatibility
    """
    # Always-regular 80
    if "80" in archs:
        cc_flag += ["-gencode", "arch=compute_80,code=sm_80"]

    # Hopper 9.0 needs >= 11.8
    if bare_metal_version >= Version("11.8") and "90" in archs:
        cc_flag += ["-gencode", "arch=compute_90,code=sm_90"]

    # Blackwell 10.x requires >= 12.8
    if bare_metal_version >= Version("12.8"):
        if "100" in archs:
            # CUDA 12.9 introduced "family-specific" for Blackwell (100f)
            if bare_metal_version >= Version("12.9"):
                cc_flag += ["-gencode", "arch=compute_100f,code=sm_100"]
            else:
                cc_flag += ["-gencode", "arch=compute_100,code=sm_100"]

        if "120" in archs:
            # sm_120 is supported in CUDA 12.8/12.9+ toolkits
            if bare_metal_version >= Version("12.9"):
                cc_flag += ["-gencode", "arch=compute_120f,code=sm_120"]
            else:
                cc_flag += ["-gencode", "arch=compute_120,code=sm_120"]

        # Thor rename: 12.9 uses sm_101; 13.0+ uses sm_110
        if "110" in archs:
            if bare_metal_version >= Version("13.0"):
                cc_flag += ["-gencode", "arch=compute_110f,code=sm_110"]
            else:
                # Provide Thor support for CUDA 12.9 via sm_101
                if bare_metal_version >= Version("12.8"):
                    cc_flag += ["-gencode", "arch=compute_101,code=sm_101"]
                # else: no Thor support in older toolkits

    # PTX for newest requested arch (forward-compat)
    numeric = [a for a in archs if a.isdigit()]
    if numeric:
        newest = max(numeric, key=int)
        cc_flag += ["-gencode", f"arch=compute_{newest},code=compute_{newest}"]

    return cc_flag


# From NinjaBuildExtension.__init__:
# Logic for computing optimal MAX_JOBS for parallel compilation.
#
#   nvcc_threads = max(1, int(NVCC_THREADS))
#   max_num_jobs_cores = max(1, os.cpu_count() // 2)
#   free_memory_gb = psutil.virtual_memory().available / (1024 ** 3)
#   max_num_jobs_memory = max(1, int(free_memory_gb / (5 * nvcc_threads)))
#   max_jobs = max(1, min(max_num_jobs_cores, max_num_jobs_memory))
