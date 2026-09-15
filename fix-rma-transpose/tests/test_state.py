
import subprocess
import os
import re
import pytest

# MCA params to avoid CMA/RDMA failures in containers
MPI_BASE = [
    "mpiexec", "--oversubscribe", "--allow-run-as-root",
    "--mca", "osc", "pt2pt",
    "--mca", "btl_vader_single_copy_mechanism", "none",
]

TOLERANCE = 1e-4


def compile_src(src, binary, compiler="mpicc", extra_flags=None):
    """Compile a C source file."""
    cmd = [compiler, "-Wall", "-O2", "-o", binary, src]
    if extra_flags:
        cmd.extend(extra_flags)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def run_seq(binary, timeout=120):
    """Run a sequential program."""
    return subprocess.run([binary], capture_output=True, text=True, timeout=timeout)


def run_mpi(binary, nprocs, timeout=180):
    """Run an MPI program with the given number of processes."""
    return subprocess.run(
        MPI_BASE + ["-n", str(nprocs), binary],
        capture_output=True, text=True, timeout=timeout,
    )


def parse_output(stdout):
    """Extract CHECKSUM and MAXVAL from program output."""
    checksum = None
    maxval = None
    for line in stdout.strip().split("\n"):
        if line.startswith("CHECKSUM:"):
            checksum = float(line.split(":")[1].strip())
        elif line.startswith("MAXVAL:"):
            maxval = float(line.split(":")[1].strip())
    return checksum, maxval


def get_reference(n_flag=None):
    """Compile and run the sequential reference, return (checksum, maxval)."""
    extra = [f"-DN={n_flag}"] if n_flag else None
    suffix = f"_{n_flag}" if n_flag else ""
    binary = f"/app/jacobi_seq{suffix}"
    res = compile_src("/app/jacobi_seq.c", binary, compiler="gcc", extra_flags=extra)
    assert res.returncode == 0, f"Seq compile failed: {res.stderr}"
    out = run_seq(binary)
    assert out.returncode == 0, f"Seq run failed: {out.stderr}"
    ck, mv = parse_output(out.stdout)
    assert ck is not None, f"No CHECKSUM in seq output: {out.stdout}"
    assert mv is not None, f"No MAXVAL in seq output: {out.stdout}"
    return ck, mv


def compile_parallel(n_flag=None):
    """Compile the parallel implementation."""
    extra = [f"-DN={n_flag}"] if n_flag else None
    suffix = f"_{n_flag}" if n_flag else ""
    binary = f"/app/jacobi_rma{suffix}"
    res = compile_src("/app/jacobi_rma.c", binary, extra_flags=extra)
    assert res.returncode == 0, f"Par compile failed:\nstdout: {res.stdout}\nstderr: {res.stderr}"
    return binary


def run_parallel(binary, nprocs):
    """Run the parallel implementation and return (checksum, maxval)."""
    out = run_mpi(binary, nprocs)
    assert out.returncode == 0, (
        f"Par run failed ({nprocs} procs):\nstdout: {out.stdout}\nstderr: {out.stderr}"
    )
    ck, mv = parse_output(out.stdout)
    assert ck is not None, f"No CHECKSUM in par output: {out.stdout}"
    assert mv is not None, f"No MAXVAL in par output: {out.stdout}"
    return ck, mv


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestJacobiRMA:

    def test_source_exists(self):
        """The parallel source file must exist."""
        assert os.path.isfile("/app/jacobi_rma.c"), "/app/jacobi_rma.c not found"

    def test_compiles(self):
        """The parallel program must compile with mpicc."""
        compile_parallel()

    def test_correct_with_4_procs(self):
        """Parallel results with 4 procs must match sequential reference."""
        seq_ck, seq_mv = get_reference()
        binary = compile_parallel()
        par_ck, par_mv = run_parallel(binary, 4)

        assert abs(seq_ck - par_ck) < TOLERANCE, (
            f"Checksum mismatch (4 procs): seq={seq_ck}, par={par_ck}"
        )
        assert abs(seq_mv - par_mv) < TOLERANCE, (
            f"Maxval mismatch (4 procs): seq={seq_mv}, par={par_mv}"
        )

    def test_correct_with_6_procs(self):
        """Parallel results with 6 procs must match sequential reference."""
        seq_ck, _ = get_reference()
        binary = compile_parallel()
        par_ck, _ = run_parallel(binary, 6)

        assert abs(seq_ck - par_ck) < TOLERANCE, (
            f"Checksum mismatch (6 procs): seq={seq_ck}, par={par_ck}"
        )

    def test_uses_rma_passive_target(self):
        """Source must use passive target synchronization."""
        with open("/app/jacobi_rma.c") as f:
            code = f.read()
        has_lock_all = "MPI_Win_lock_all" in code
        has_lock = "MPI_Win_lock(" in code and "MPI_Win_unlock(" in code
        assert has_lock_all or has_lock, (
            "Must use passive target synchronization "
            "(MPI_Win_lock_all or MPI_Win_lock/MPI_Win_unlock)"
        )

    def test_uses_derived_datatypes(self):
        """Source must use MPI derived datatypes for column halos."""
        with open("/app/jacobi_rma.c") as f:
            code = f.read()
        has_vector = "MPI_Type_vector" in code
        has_subarray = "MPI_Type_create_subarray" in code
        assert has_vector or has_subarray, (
            "Must use derived datatypes (MPI_Type_vector or MPI_Type_create_subarray)"
        )

    def test_uses_rma_operations(self):
        """Source must use MPI RMA operations for data transfer."""
        with open("/app/jacobi_rma.c") as f:
            code = f.read()
        has_win = "MPI_Win_create" in code or "MPI_Win_allocate" in code
        assert has_win, "Must create an MPI window (MPI_Win_create or MPI_Win_allocate)"
        has_put = "MPI_Put" in code
        has_get = "MPI_Get" in code
        assert has_put or has_get, "Must use MPI_Put or MPI_Get for halo exchange"

    def test_no_point_to_point_for_data(self):
        """Source must not use MPI point-to-point for data exchange."""
        with open("/app/jacobi_rma.c") as f:
            code = f.read()
        # Strip comments to avoid false positives
        clean = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
        clean = re.sub(r"//.*", "", clean)
        for func in ["MPI_Send(", "MPI_Isend(", "MPI_Recv(", "MPI_Irecv(",
                      "MPI_Sendrecv(", "MPI_Sendrecv_replace("]:
            assert func not in clean, (
                f"Must not use {func.rstrip('(')} -- use RMA operations instead"
            )

    def test_different_grid_size(self):
        """Anti-cheat: must work with N=48 (not just hardcoded for N=60)."""
        seq_ck, seq_mv = get_reference(n_flag=48)
        binary = compile_parallel(n_flag=48)
        par_ck, par_mv = run_parallel(binary, 4)

        assert abs(seq_ck - par_ck) < TOLERANCE, (
            f"Checksum mismatch (N=48, 4 procs): seq={seq_ck}, par={par_ck}"
        )
        assert abs(seq_mv - par_mv) < TOLERANCE, (
            f"Maxval mismatch (N=48, 4 procs): seq={seq_mv}, par={par_mv}"
        )

    def test_different_grid_size_6_procs(self):
        """Anti-cheat: must work with N=48 and 6 processes."""
        seq_ck, _ = get_reference(n_flag=48)
        binary = compile_parallel(n_flag=48)
        par_ck, _ = run_parallel(binary, 6)

        assert abs(seq_ck - par_ck) < TOLERANCE, (
            f"Checksum mismatch (N=48, 6 procs): seq={seq_ck}, par={par_ck}"
        )
