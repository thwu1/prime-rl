FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    curl \
    bzip2 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install micromamba (lightweight conda-forge package manager)
ENV MAMBA_ROOT_PREFIX=/opt/conda
RUN curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | \
    tar -xvj -C /usr/local bin/micromamba

# Create conda environment with FEniCSx/DOLFINx and full dependency chain
# (PETSc, MPI, Basix, UFL, FFCx, mpi4py, petsc4py, etc.)
RUN /usr/local/bin/micromamba create -y -p /opt/fenics \
    -c conda-forge \
    fenics-dolfinx=0.10.0 \
    python=3.12 \
    pip \
    && /usr/local/bin/micromamba clean -ya

# Make the conda environment the default runtime
ENV PATH="/opt/fenics/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/fenics/lib:${LD_LIBRARY_PATH}"

# Copy utility library into the working directory
COPY utils.py /app/utils.py
WORKDIR /app
