FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    bzip2 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Miniforge3 (includes mamba + conda-forge defaults)
RUN curl -fsSL https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -o /tmp/miniforge.sh && \
    bash /tmp/miniforge.sh -b -p /opt/conda && \
    rm /tmp/miniforge.sh

ENV PATH="/opt/conda/bin:$PATH"

# Install DOLFINx with PETSc wrappers, MUMPS, and pip via mamba (fast resolver)
RUN mamba install -y fenics-dolfinx pip && conda clean -afy

# Verify installation: PETSc wrappers importable, MUMPS available
RUN python3 -c "from mpi4py import MPI; from petsc4py import PETSc; import dolfinx; from dolfinx.fem.petsc import assemble_matrix, assemble_vector, apply_lifting; print('DOLFINx', dolfinx.__version__, '| MUMPS:', PETSc.Sys().hasExternalPackage('mumps'))"

WORKDIR /app
COPY kovasznay.py /app/kovasznay.py
