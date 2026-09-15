FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1


RUN apt-get update && apt-get install -y \
    python3-pip \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Miniforge (pinned version)
RUN wget -q https://github.com/conda-forge/miniforge/releases/download/24.7.1-2/Miniforge3-24.7.1-2-Linux-x86_64.sh -O /tmp/miniforge.sh && \
    bash /tmp/miniforge.sh -b -p /opt/conda && \
    rm /tmp/miniforge.sh

ENV PATH=/opt/conda/bin:$PATH
ENV LD_LIBRARY_PATH=/opt/conda/lib:$LD_LIBRARY_PATH

# Install FEniCSx (DOLFINx) with PETSc/MUMPS and MPI
RUN mamba install -y -c conda-forge fenics-dolfinx=0.9.0 && \
    mamba clean -a -y

WORKDIR /app
COPY problem_spec.py /app/problem_spec.py
