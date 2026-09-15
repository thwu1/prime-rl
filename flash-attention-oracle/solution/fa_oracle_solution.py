
"""
Flash Attention Build Configuration and Performance Oracle.

Implements five functions that replicate logic from the Flash Attention codebase
for FLOPS computation, CUDA gencode flag generation, kernel block size selection,
build parallelism optimization, and memory analysis.
"""


def _parse_version(version_str):
    """Parse a version string like '12.9.0' into a comparable tuple of ints."""
    parts = version_str.strip().split(".")
    return tuple(int(p) for p in parts)


def _version_gte(version_str, target):
    """Check if version_str >= target (both as dotted strings)."""
    return _parse_version(version_str) >= _parse_version(target)


def compute_flops(batch, seqlen, headdim, nheads, causal, mode="fwd"):
    """Compute theoretical FLOPs for attention forward/backward passes.

    Args:
        batch: batch size
        seqlen: sequence length
        headdim: head dimension
        nheads: number of attention heads
        causal: whether causal masking is used (halves FLOPs)
        mode: one of "fwd", "bwd", "fwd_bwd"

    Returns:
        int for "fwd", float for "bwd" and "fwd_bwd"
    """
    assert mode in ["fwd", "bwd", "fwd_bwd"]
    f = 4 * batch * seqlen ** 2 * nheads * headdim // (2 if causal else 1)
    return f if mode == "fwd" else (2.5 * f if mode == "bwd" else 3.5 * f)


def generate_gencodes(cuda_version, archs):
    """Generate NVCC -gencode flags for Flash Attention compilation.

    Args:
        cuda_version: CUDA toolkit version string, e.g. "12.9.0"
        archs: list of architecture strings, e.g. ["80", "90", "100"]

    Returns:
        list of strings forming the -gencode flag arguments
    """
    archs = set(archs)
    cc_flag = []

    # Ampere sm_80: always supported
    if "80" in archs:
        cc_flag += ["-gencode", "arch=compute_80,code=sm_80"]

    # Hopper sm_90: requires CUDA >= 11.8
    if _version_gte(cuda_version, "11.8") and "90" in archs:
        cc_flag += ["-gencode", "arch=compute_90,code=sm_90"]

    # Blackwell and beyond: requires CUDA >= 12.8
    if _version_gte(cuda_version, "12.8"):
        # sm_100 (Blackwell)
        if "100" in archs:
            if _version_gte(cuda_version, "12.9"):
                cc_flag += ["-gencode", "arch=compute_100f,code=sm_100"]
            else:
                cc_flag += ["-gencode", "arch=compute_100,code=sm_100"]

        # sm_120
        if "120" in archs:
            if _version_gte(cuda_version, "12.9"):
                cc_flag += ["-gencode", "arch=compute_120f,code=sm_120"]
            else:
                cc_flag += ["-gencode", "arch=compute_120,code=sm_120"]

        # Thor: sm_110 on CUDA 13.0+, remapped to sm_101 on CUDA 12.8-12.9
        if "110" in archs:
            if _version_gte(cuda_version, "13.0"):
                cc_flag += ["-gencode", "arch=compute_110f,code=sm_110"]
            else:
                if _version_gte(cuda_version, "12.8"):
                    cc_flag += ["-gencode", "arch=compute_101,code=sm_101"]

    # PTX for newest requested architecture (forward compatibility)
    numeric = [a for a in archs if a.isdigit()]
    if numeric:
        newest = max(numeric, key=int)
        cc_flag += ["-gencode", f"arch=compute_{newest},code=compute_{newest}"]

    return cc_flag


def get_block_size_n(compute_capability, head_dim, is_dropout, is_causal):
    """Determine kBlockN tile size for the Flash Attention CUDA kernel.

    Args:
        compute_capability: (major, minor) tuple, e.g. (8, 0) for A100
        head_dim: head dimension (must be <= 256)
        is_dropout: whether dropout is enabled
        is_causal: whether causal masking is used

    Returns:
        kBlockN tile size (int)
    """
    assert head_dim <= 256
    major, minor = compute_capability
    is_sm8x = major == 8 and minor > 0  # sm86, sm89 only; excludes sm80

    if head_dim <= 32:
        return 128
    if head_dim <= 64:
        return 128 if not is_dropout else 64
    elif head_dim <= 96:
        return 64
    elif head_dim <= 128:
        if is_sm8x:
            return 64 if (not is_dropout and is_causal) else 32
        else:
            return 64 if not is_dropout else 32
    elif head_dim <= 192:
        return 64
    elif head_dim <= 224:
        return 64
    elif head_dim <= 256:
        return 64


def compute_max_jobs(cpu_count, free_memory_gb, nvcc_threads):
    """Compute optimal MAX_JOBS for parallel CUDA compilation.

    Args:
        cpu_count: number of CPU cores
        free_memory_gb: available memory in GB
        nvcc_threads: number of NVCC parallel threads per job

    Returns:
        optimal MAX_JOBS value (int, >= 1)
    """
    nvcc_threads = max(1, int(nvcc_threads))
    max_num_jobs_cores = max(1, cpu_count // 2)
    max_num_jobs_memory = max(1, int(free_memory_gb / (5 * nvcc_threads)))
    max_jobs = max(1, min(max_num_jobs_cores, max_num_jobs_memory))
    return max_jobs


def memory_analysis(batch, seqlen, nheads, headdim, dtype_bytes):
    """Compare memory footprints of standard vs flash attention.

    Args:
        batch: batch size
        seqlen: sequence length
        nheads: number of attention heads
        headdim: head dimension
        dtype_bytes: bytes per element (2 for fp16/bf16, 4 for fp32)

    Returns:
        dict with "standard_bytes" and "flash_bytes"
    """
    # Q, K, V, O: each batch * seqlen * nheads * headdim * dtype_bytes
    qkvo_bytes = 4 * batch * seqlen * nheads * headdim * dtype_bytes

    # Standard attention: full N×N attention score matrix
    attn_matrix_bytes = batch * nheads * seqlen * seqlen * dtype_bytes
    standard_bytes = qkvo_bytes + attn_matrix_bytes

    # Flash attention: only per-row logsumexp (always float32 = 4 bytes)
    softmax_lse_bytes = batch * nheads * seqlen * 4
    flash_bytes = qkvo_bytes + softmax_lse_bytes

    return {
        "standard_bytes": standard_bytes,
        "flash_bytes": flash_bytes,
    }
