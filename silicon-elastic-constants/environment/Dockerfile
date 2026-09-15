
FROM ghcr.io/laude-institute/t-bench/ubuntu-24-04:20250624
ENV PIP_BREAK_SYSTEM_PACKAGES=1

RUN apt-get update && apt-get install -y \
    lammps \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN if ! command -v lmp > /dev/null 2>&1; then \
      for name in lmp_serial lmp_mpi lmp_stable; do \
        if command -v "$name" > /dev/null 2>&1; then \
          ln -sf "$(which "$name")" /usr/local/bin/lmp; \
          break; \
        fi; \
      done; \
    fi

RUN mkdir -p /app/potentials /app/elastic_workflow

COPY Si.sw /app/potentials/Si.sw
COPY compute_elastic.py /app/elastic_workflow/compute_elastic.py

WORKDIR /app
